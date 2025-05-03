import json
import logging
import re
import uuid
from typing import Any

# from langchain_openai import ChatOpenAI # Removed direct import
from langchain_core.output_parsers import (
    StrOutputParser,
)

# Or potentially JsonOutputParser/Pydantic for structured recommendations
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession

# from app.models.agent_task import AgentTask
# from app.services.database import SessionLocal
from app.agents.constants import AgentTaskStatus
from app.agents.prompts import (
    format_recommendation_generation_prompt,
)

# Need to create this prompt
from app.agents.utils import (
    aget_llm_client,
    update_agent_task_status,
)

# Use async helper
from app.services.action_service import create_proposed_action  # Keep async

# from app.agents.tools.shopify_tools import shopify_tools # May need tools later
# from app.agents.tools.hitl_tools import proposal_tool # May need HITL tool later

logger = logging.getLogger(__name__)


# --- Helper: Build Log Props --- #
def _get_rg_log_props(input_data: "RecommendationGenerationInput") -> dict:
    return {
        "task_id": str(input_data.task_id),
        "user_id": str(input_data.user_id),
        "analysis_request_id": str(input_data.analysis_request_id),
    }


class RecommendationGenerationInput(BaseModel):
    """Input schema for the Recommendation Generation Department runnable."""

    db: AsyncSession
    user_id: uuid.UUID
    analysis_request_id: uuid.UUID
    task_id: uuid.UUID
    shop_domain: str | None = None
    recommendation_prompt: str = Field(
        default="Generate recommendations based on the provided analysis."
    )
    # Expecting results from previous analysis steps (Quantitative, Qualitative)
    analysis_results: dict[str, Any] = Field(...)

    class Config:
        arbitrary_types_allowed = True


# Regex to find action blocks
ACTION_BLOCK_REGEX = re.compile(
    r"\[PROPOSED_ACTION\]\s*\n(.*?)\n\s*\[/PROPOSED_ACTION\]", re.DOTALL | re.IGNORECASE
)


def _parse_action_details(
    block_content: str,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Parses action_type, description, and parameters from the block content."""
    action_type = None
    description = None
    parameters = None
    try:
        lines = [line.strip() for line in block_content.strip().split("\n")]
        details = {}
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                details[key.strip()] = value.strip()

        action_type = details.get("action_type")
        description = details.get("description")
        params_str = details.get("parameters")
        if params_str:
            try:
                # Remove potential comments and parse JSON
                params_str_cleaned = re.sub(r"#.*$", "", params_str).strip()
                parameters = json.loads(params_str_cleaned)
            except json.JSONDecodeError as json_err:
                logger.warning(
                    f"Failed to parse parameters JSON: {params_str}. Error: {json_err}"
                )
                parameters = None
        else:
            parameters = {}

    except Exception as e:
        logger.error(
            f"Error parsing action block content: {e}\nContent:\n{block_content}"
        )
    return action_type, description, parameters


async def _generate_recommendations(
    input_data: RecommendationGenerationInput,
) -> dict[str, Any]:
    """Generates recommendations using an LLM based on prior analysis results.
    Updates task status via the placeholder _update_task_status function.
    Potentially uses tools for context or proposes HITL actions in the future.
    """
    log_props = _get_rg_log_props(input_data)
    db_session = input_data.db
    user_id = input_data.user_id
    analysis_request_id = input_data.analysis_request_id
    task_id = input_data.task_id
    recommendation_prompt_instr = input_data.recommendation_prompt
    analysis_results = input_data.analysis_results

    try:
        await update_agent_task_status(db_session, task_id, AgentTaskStatus.RUNNING)
        logger.info("Starting recommendation generation.", extra={"props": log_props})
    except Exception as update_err:
        logger.error(
            f"Failed to update status to RUNNING: {update_err}",
            extra={"props": log_props},
        )
        return {
            "status": "error",
            "error_message": f"DB Error setting status: {update_err}",
            "task_id": task_id,
        }

    try:
        logger.info(
            f"Preparing recommendation prompt: {recommendation_prompt_instr[:50]}...",
            extra={"props": log_props},
        )

        # Use await with aget_llm_client
        recommendation_llm = await aget_llm_client(
            db=db_session, user_id=user_id, model_type="creative"
        )

        # Format the prompt
        prompt = format_recommendation_generation_prompt(
            recommendation_prompt=recommendation_prompt_instr,
            analysis_results=analysis_results,
        )

        generation_chain = recommendation_llm | StrOutputParser()

        logger.info(
            f"Invoking recommendation generation LLM ({recommendation_llm.model_name}).",
            extra={"props": log_props},
        )
        # Use await for async chain invocation
        recommendation_result = await generation_chain.ainvoke(prompt)

        # --- Parse LLM output for proposed actions and create records ---
        proposed_action_count = 0
        for match in ACTION_BLOCK_REGEX.finditer(recommendation_result):
            block_content = match.group(1)
            action_type, description, parameters = _parse_action_details(block_content)

            if action_type and description and parameters is not None:
                proposal_log_props = {**log_props, "proposed_action_type": action_type}
                try:
                    # Ensure create_proposed_action is async and use await
                    await create_proposed_action(
                        db=db_session,
                        user_id=user_id,
                        analysis_request_id=analysis_request_id,
                        action_type=action_type,
                        description=description,
                        parameters=parameters,
                    )
                    proposed_action_count += 1
                except Exception:
                    logger.error(
                        "Failed to create proposed action",
                        exc_info=True,
                        extra={"props": proposal_log_props},
                    )
            else:
                logger.warning(
                    "Failed to parse/validate action block",
                    extra={
                        "props": {**log_props, "block_content": block_content[:100]}
                    },
                )

        if proposed_action_count > 0:
            logger.info(
                f"Created {proposed_action_count} proposed actions.",
                extra={"props": log_props},
            )
        # --- End Action Proposal Handling ---

        logger.info(
            "Recommendation generation completed successfully.",
            extra={"props": log_props},
        )
        # Use await for status update
        await update_agent_task_status(
            db_session,
            task_id,
            AgentTaskStatus.COMPLETED,
            result=recommendation_result,
        )
        return {
            "status": "success",
            "result": recommendation_result,
            "task_id": task_id,
        }

    except Exception as e:
        logger.exception(
            "Error during recommendation generation",
            exc_info=True,
            extra={"props": log_props},
        )
        error_message = str(e)
        # Use await for status update
        try:
            await update_agent_task_status(
                db_session,
                task_id,
                AgentTaskStatus.FAILED,
                error_message=error_message,
            )
        except Exception as final_update_err:
            logger.error(
                f"Failed to update status to FAILED after error: {final_update_err}",
                extra={"props": log_props},
            )
        return {
            "status": "error",
            "error_message": error_message,
            "task_id": task_id,
        }


# Instantiate the runnable for this department
recommendation_generation_runnable = RunnableLambda(
    _generate_recommendations
).with_types(input_type=RecommendationGenerationInput)
