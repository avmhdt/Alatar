import logging
import uuid
from typing import Any

# from langchain_openai import ChatOpenAI # Removed direct import
from langchain_core.output_parsers import StrOutputParser  # Or JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession

# from app.models.agent_task import AgentTask
# from app.services.database import SessionLocal
from app.agents.constants import AgentTaskStatus
from app.agents.prompts import (
    format_qualitative_analysis_prompt,
)

# Import correct prompt
from app.agents.utils import aget_llm_client, update_agent_task_status  # Import helpers

# from app.agents.tools.some_tool import some_tool_functionality # Import tools if needed

logger = logging.getLogger(__name__)


# --- Helper: Build Log Props --- #
def _get_ql_log_props(input_data: "QualitativeAnalysisInput") -> dict:
    return {
        "task_id": str(input_data.task_id),
        "user_id": str(input_data.user_id),
        "analysis_request_id": str(input_data.analysis_request_id),
    }


class QualitativeAnalysisInput(BaseModel):
    """Input schema for the Qualitative Analysis Department runnable."""

    db: AsyncSession
    user_id: uuid.UUID
    task_id: uuid.UUID
    analysis_request_id: uuid.UUID
    shop_domain: str | None = None
    analysis_prompt: str = Field(default="Perform qualitative analysis.")
    retrieved_data: dict[str, Any] = Field(...)

    class Config:
        arbitrary_types_allowed = True


async def _perform_qualitative_analysis(
    input_data: QualitativeAnalysisInput,
) -> dict[str, Any]:
    """Performs qualitative analysis using an LLM based on the provided instructions and data.
    Updates task status via the placeholder _update_task_status function.
    """
    log_props = _get_ql_log_props(input_data)
    db_session = input_data.db
    user_id = input_data.user_id
    task_id = input_data.task_id
    analysis_prompt = input_data.analysis_prompt
    retrieved_data = input_data.retrieved_data

    try:
        await update_agent_task_status(db_session, task_id, AgentTaskStatus.RUNNING)
        logger.info("Starting qualitative analysis.", extra={"props": log_props})
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
            f"Preparing qualitative analysis prompt: {analysis_prompt[:50]}...",
            extra={"props": log_props},
        )

        # Get LLM Client using helper
        ql_llm = aget_llm_client(db=db_session, user_id=user_id, model_type="tool")

        # Format the prompt
        prompt = format_qualitative_analysis_prompt(
            analysis_prompt=analysis_prompt, retrieved_data=retrieved_data
        )

        # Define the analysis chain
        analysis_chain = ql_llm | StrOutputParser()

        logger.info(
            f"Invoking qualitative analysis LLM ({ql_llm.model_name}).",
            extra={"props": log_props},
        )
        analysis_result = await analysis_chain.ainvoke(prompt)

        logger.info(
            "Qualitative analysis completed successfully.", extra={"props": log_props}
        )
        await update_agent_task_status(
            db_session,
            task_id,
            AgentTaskStatus.COMPLETED,
            result=analysis_result,
        )
        return {
            "status": "success",
            "result": analysis_result,
            "task_id": task_id,
        }

    except Exception as e:
        logger.exception(
            "Error during qualitative analysis",
            exc_info=True,
            extra={"props": log_props},
        )
        error_message = str(e)
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
qualitative_analysis_runnable = RunnableLambda(
    _perform_qualitative_analysis
).with_types(input_type=QualitativeAnalysisInput)
