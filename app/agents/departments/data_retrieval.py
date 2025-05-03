import asyncio
import logging
import uuid
from typing import Any
import random # Import random for jitter

from langchain.tools import BaseTool
from langchain_core.messages import AIMessage

# from langchain_openai import ChatOpenAI # Removed direct import
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession  # Import AsyncSession

from app.agents.constants import DEFAULT_RETRY_LIMIT, AgentTaskStatus
from app.agents.tools.shopify_tools import (
    get_all_shopify_tools,
)

# get_shopify_credentials_for_user, # No longer needed here
from app.agents.utils import aget_llm_client, update_agent_task_status  # Added helper

logger = logging.getLogger(__name__)


# --- Helper: Build Log Props --- #
def _get_dr_log_props(input_data: "DataRetrievalInput") -> dict:
    return {
        "task_id": str(input_data.task_id),
        "user_id": str(input_data.user_id),
        "analysis_request_id": str(input_data.analysis_request_id),
    }


# Keep retry helper using sync Session for now
async def _arun_tool_with_retry(
    db: AsyncSession,  # Expect AsyncSession
    user_id: uuid.UUID,
    task_id: uuid.UUID,
    tool: BaseTool,
    tool_input: dict[str, Any],
    max_retries: int = DEFAULT_RETRY_LIMIT,
) -> Any:
    """Run a LangChain tool asynchronously with retry logic and task status updates."""
    retry_count = 0
    last_error = None
    log_props = {
        "task_id": str(task_id),
        "user_id": str(user_id),
        "tool_name": tool.name,
    }

    # Add db, user_id, shop_domain required by our tool implementation
    # Pass AsyncSession to tool
    full_tool_input = {
        **tool_input,
        "db": db,
        "user_id": user_id,
    }

    while retry_count <= max_retries:
        try:
            log_props["retry_attempt"] = retry_count + 1
            logger.info(
                "Attempt %d/%d - Running tool '%s' async",
                retry_count + 1,
                max_retries + 1,
                tool.name,
                extra={"props": log_props},
            )
            # Update status asynchronously
            await update_agent_task_status(
                db,
                task_id,
                AgentTaskStatus.RUNNING
                if retry_count == 0
                else AgentTaskStatus.RETRYING,
                retry_count=retry_count,
            )

            result = await tool.ainvoke(
                full_tool_input#, config={"callbacks": [task_handler]} # Removed task_handler callback for now
            )

            # Error check remains the same
            if isinstance(result, str) and result.startswith(
                ("Error:", "An unexpected error occurred:")
            ):
                raise Exception(result)

            logger.info(
                "Tool '%s' completed successfully (async).",
                tool.name,
                extra={"props": log_props},
            )
            # Status is updated by the caller (_aroute_and_execute_tool) on success
            return result

        except Exception as e:
            last_error = e
            logger.warning(
                "Attempt %d failed for tool '%s': %s",
                retry_count + 1,
                tool.name,
                e,
                exc_info=True,  # Include traceback for warnings on retries
                extra={"props": log_props},
            )
            retry_count += 1
            if retry_count > max_retries:
                # Log final failure using exception, not error
                logger.exception(
                    "Tool '%s' failed after %d attempts (async). Final error: %s",
                    tool.name,
                    max_retries + 1,
                    last_error,
                    extra={"props": log_props},
                )
                # Update status to FAILED before raising
                try:
                    await update_agent_task_status(
                        db, task_id, AgentTaskStatus.FAILED, error_message=str(last_error)
                    )
                except Exception as update_err:
                     logger.error(
                        f"Failed to update status to FAILED after exhausting retries: {update_err}",
                        extra={"props": log_props}
                     )
                # Raise a generic exception to be caught by the caller
                raise Exception(
                    f"Tool '{tool.name}' failed after {max_retries + 1} attempts (async)."
                )

            # --- Exponential Backoff with Jitter --- #
            base_delay = 2 ** (retry_count - 1)  # Starts at 1, then 2, 4, 8...
            max_delay = 30 # Cap delay at 30 seconds
            delay = min(base_delay + random.uniform(0, 1), max_delay)
            # --- End Backoff --- #

            logger.info(
                "Retrying tool '%s' in %.2f seconds (async)...",
                tool.name,
                delay,
                extra={"props": log_props},
            )
            await asyncio.sleep(delay)

    # This part should ideally not be reached due to the raise in the loop
    raise Exception(
        f"Tool '{tool.name}' failed unexpectedly after retries. Last error: {last_error}"
    )


# --- New LLM-based Routing Logic ---
# NOTE: Assuming tool_descriptions is defined globally or passed appropriately
# Placeholder definition if not defined elsewhere
tool_descriptions = "\n".join([
    f"- {tool.name}: {tool.description}"
    for tool in get_all_shopify_tools()
])

prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an AI assistant selecting the best Shopify data retrieval tool.\n"
            "Available tools:\n{tools}\n\n"
            "Select the best tool for the user's request. Respond ONLY with the tool invocation JSON.",
        ),
        ("human", "User request: {request}"),
    ]
).partial(tools=tool_descriptions)

# Map tool names to tool objects for execution
tool_map = {tool.name: tool for tool in get_all_shopify_tools()}


class DataRetrievalInput(BaseModel):
    db: AsyncSession  # Expect AsyncSession
    user_id: uuid.UUID
    shop_domain: str
    task_id: uuid.UUID
    analysis_request_id: uuid.UUID | None = None
    task_details: dict[str, Any] = Field(
        ...,
        description="Details of the task, expected to contain a 'request' key with the natural language query for data.",
    )

    class Config:
        arbitrary_types_allowed = True  # Allow AsyncSession


# Keep main execution function async, but pass sync session
async def _aroute_and_execute_tool(input_data: DataRetrievalInput) -> dict[str, Any]:
    log_props = _get_dr_log_props(input_data)
    db_session = input_data.db  # AsyncSession now
    user_id = input_data.user_id
    shop_domain = input_data.shop_domain # Needed by tool context
    task_id = input_data.task_id
    task_request = input_data.task_details.get("request")

    if not task_request:
        error_msg = f"[Task: {task_id}] Missing 'request' in task_details."
        logger.error(error_msg, extra={"props": log_props})
        # Update status async
        try:
            await update_agent_task_status(
                db_session, task_id, AgentTaskStatus.FAILED, error_message=error_msg
            )
        except Exception as update_err:
            logger.error(
                f"Failed to update status after missing request detail: {update_err}"
            )
        return {"status": "error", "error_message": error_msg, "task_id": task_id}

    # Get LLM client (pass async session - with warning about preference loading)
    try:
        llm_client = await aget_llm_client(db=db_session, user_id=user_id, model_type="tool")
        llm_with_tools = llm_client.bind_tools(get_all_shopify_tools())
    except Exception as client_err:
        error_msg = f"[Task: {task_id}] Failed to initialize LLM client: {client_err}"
        logger.exception(error_msg, extra={"props": log_props})
        # Update status async
        try:
            await update_agent_task_status(
                db_session,
                task_id,
                AgentTaskStatus.FAILED,
                error_message=str(client_err),
            )
        except Exception as update_err:
            logger.error(f"Failed to update status after LLM init error: {update_err}")
        return {"status": "error", "error_message": str(client_err), "task_id": task_id}

    # TODO: Fix tool descriptions - should not be hardcoded/recomputed here
    # prompt_values = prompt.invoke(...)
    # Using llm_with_tools.ainvoke with just the request string for simplicity now
    # This relies on the LLM being fine-tuned or instructed well enough
    # to directly call the bound tools based on the request.

    try:
        logger.info(
            f"[Task: {task_id}] Invoking tool selection LLM ({llm_client.model_name}) async.",
            extra={"props": log_props},
        )
        ai_msg: AIMessage = await llm_with_tools.ainvoke(task_request)
    except Exception as e:
        error_msg = f"[Task: {task_id}] LLM invocation failed (async): {e}"
        logger.exception(error_msg, extra={"props": log_props})
        # Update status async
        try:
            await update_agent_task_status(
                db_session, task_id, AgentTaskStatus.FAILED, error_message=str(e)
            )
        except Exception as update_err:
            logger.error(
                f"Failed to update status after LLM invoke error: {update_err}"
            )
        return {"status": "error", "error_message": str(e), "task_id": task_id}

    if not ai_msg.tool_calls:
        error_msg = f"[Task: {task_id}] LLM did not select a tool for request (async): {task_request}"
        logger.error(error_msg, extra={"props": log_props})
        # Update status async
        try:
            await update_agent_task_status(
                db_session, task_id, AgentTaskStatus.FAILED, error_message=error_msg
            )
        except Exception as update_err:
            logger.error(
                f"Failed to update status after no tool selected: {update_err}"
            )
        return {
            "status": "error",
            "error_message": error_msg,
            "task_id": task_id,
            "llm_response": ai_msg.content,
        }

    # Assuming only one tool call for now
    if len(ai_msg.tool_calls) > 1:
        logger.warning(f"[Task: {task_id}] Multiple tool calls received, using only the first.", extra={"props": log_props})

    tool_call = ai_msg.tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    log_props["selected_tool"] = tool_name

    if tool_name not in tool_map:
        error_msg = f"[Task: {task_id}] LLM selected an unknown tool: {tool_name}"
        logger.error(error_msg, extra={"props": log_props})
        # Update status async
        try:
            await update_agent_task_status(
                db_session, task_id, AgentTaskStatus.FAILED, error_message=error_msg
            )
        except Exception as update_err:
            logger.error(
                f"Failed to update status after unknown tool selected: {update_err}"
            )
        return {"status": "error", "error_message": error_msg, "task_id": task_id}

    selected_tool = tool_map[tool_name]

    # Inject context required by the tool that isn't part of the LLM call args
    # Specifically, db session and user_id (shop_domain might be needed too)
    full_tool_args = {
        **tool_args,
        "db": db_session,
        "user_id": user_id,
        "shop_domain": shop_domain,
    }

    try:
        logger.info("Executing selected tool async.", extra={"props": log_props})
        # Call the async retry helper (expects AsyncSession)
        # Note: We now pass full_tool_args which includes db/user_id etc.
        result = await _arun_tool_with_retry(
            db=db_session,
            user_id=user_id,
            task_id=task_id,
            tool=selected_tool,
            tool_input=full_tool_args, # Pass the combined args
        )
        # Update status async on success
        await update_agent_task_status(
            db_session, task_id, AgentTaskStatus.COMPLETED, result=result
        )
        logger.info(
            "Data retrieval task finished successfully (async).",
            extra={"props": log_props},
        )
        return {"status": "success", "result": result, "task_id": task_id}
    except Exception as e:
        # Status should have been set to FAILED by _arun_tool_with_retry
        # Log the final error message received from the retry helper
        final_error_msg = str(e)
        logger.error(
            f"Tool execution failed after retries (async): {final_error_msg}",
            extra={"props": log_props},
        )
        # Ensure status is FAILED (in case retry helper failed to update)
        try:
            await update_agent_task_status(
                db_session, task_id, AgentTaskStatus.FAILED, error_message=final_error_msg
            )
        except Exception as final_update_err:
            logger.error(f"Failed to perform final status update check to FAILED: {final_update_err}")
        # Return error structure
        return {"status": "error", "error_message": final_error_msg, "task_id": task_id}


# Update the runnable to point to the async function
data_retrieval_runnable = RunnableLambda(_aroute_and_execute_tool).with_types(
    input_type=DataRetrievalInput
)
