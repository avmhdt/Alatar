import logging
import uuid
from typing import Any

# --- Tenacity for Retries --- #
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
# --- End Tenacity --- #

# from langchain_openai import ChatOpenAI # Removed direct import
from langchain_core.output_parsers import StrOutputParser  # Or JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession

# from app.models.agent_task import AgentTask
# from app.services.database import SessionLocal
# Use the constant for retry limit
from app.agents.constants import DEFAULT_RETRY_LIMIT, AgentTaskStatus
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

# Define retry parameters (same as quantitative)
retry_exceptions = (Exception,)
stop_conditions = stop_after_attempt(DEFAULT_RETRY_LIMIT + 1)
wait_conditions = wait_exponential(multiplier=1, min=2, max=30)

@retry(
    stop=stop_conditions,
    wait=wait_conditions,
    retry=retry_if_exception_type(retry_exceptions),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
async def _perform_qualitative_analysis(
    input_data: QualitativeAnalysisInput,
) -> dict[str, Any]:
    """Performs qualitative analysis using an LLM based on the provided instructions and data.
    Updates task status. Includes tenacity retry logic.
    """
    log_props = _get_ql_log_props(input_data)
    db_session = input_data.db
    user_id = input_data.user_id
    task_id = input_data.task_id
    analysis_prompt = input_data.analysis_prompt
    retrieved_data = input_data.retrieved_data

    # --- Status Update: Set to RUNNING (or RETRYING by utils) --- #
    try:
        # Assuming util handles RETRYING status based on retry_count if passed
        current_status = AgentTaskStatus.RUNNING
        await update_agent_task_status(db_session, task_id, current_status)
        logger.info("Qualitative analysis attempt starting.", extra={"props": log_props})
    except Exception as update_err:
        logger.error(
            f"Failed to update status before processing: {update_err}",
            extra={"props": log_props},
        )
        raise RuntimeError(f"DB Error setting status: {update_err}") from update_err
    # --- End Status Update --- #

    try:
        logger.info(
            f"Preparing qualitative analysis prompt: {analysis_prompt[:50]}...",
            extra={"props": log_props},
        )

        # Get LLM Client using helper
        # Changed model_type to "creative" as qualitative might benefit
        ql_llm = await aget_llm_client(db=db_session, user_id=user_id, model_type="creative")

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
        # Log warning for the failed attempt
        logger.warning(
            f"Error during qualitative analysis attempt: {e}",
            exc_info=True,
            extra={"props": log_props},
        )
        # Let tenacity handle retry/reraise - final FAILED status by worker callback
        raise e


# Instantiate the runnable for this department
qualitative_analysis_runnable = RunnableLambda(
    _perform_qualitative_analysis
).with_types(input_type=QualitativeAnalysisInput)
