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
from langchain_core.output_parsers import StrOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession

# Use the constant for retry limit
from app.agents.constants import DEFAULT_RETRY_LIMIT, AgentTaskStatus
from app.agents.prompts import (
    format_quantitative_analysis_prompt,
)

# Import correct prompt
from app.agents.utils import (
    aget_llm_client,
    update_agent_task_status,
)

# from app.core.config import settings # Assuming settings for API keys

logger = logging.getLogger(__name__)

# --- LLM Client Initialization (Example) ---
# This should be configured properly, potentially shared across modules
# llm_client = ChatOpenAI(model="gpt-4o", openai_api_key=settings.OPENAI_API_KEY, temperature=0.1)


# --- Helper: Build Log Props --- #
def _get_qa_log_props(input_data: "QuantitativeAnalysisInput") -> dict:
    return {
        "task_id": str(input_data.task_id),
        "user_id": str(input_data.user_id),
        # Add analysis_request_id if passed
    }


class QuantitativeAnalysisInput(BaseModel):
    db: AsyncSession
    user_id: uuid.UUID
    task_id: uuid.UUID
    shop_domain: str | None = None  # Added shop_domain
    analysis_prompt: str = Field(default="Perform quantitative analysis.")
    # Expecting results from Data Retrieval step
    retrieved_data: dict[str, Any] = Field(...)

    class Config:
        arbitrary_types_allowed = True

# Define retry parameters
# Retry on general exceptions for now, refine if specific transient errors are known
retry_exceptions = (Exception,)
stop_conditions = stop_after_attempt(DEFAULT_RETRY_LIMIT + 1)
wait_conditions = wait_exponential(multiplier=1, min=2, max=30)

@retry(
    stop=stop_conditions,
    wait=wait_conditions,
    retry=retry_if_exception_type(retry_exceptions),
    before_sleep=before_sleep_log(logger, logging.WARNING), # Log before sleep on retry
    reraise=True # Re-raise the last exception after retries are exhausted
)
async def _perform_quantitative_analysis(
    input_data: QuantitativeAnalysisInput,
) -> dict[str, Any]:
    """Performs quantitative analysis using an LLM based on the provided instructions and data.
    Updates task status via the placeholder _update_task_status function.
    This function includes tenacity retry logic.
    """
    log_props = _get_qa_log_props(input_data)
    db_session = input_data.db
    user_id = input_data.user_id
    task_id = input_data.task_id
    analysis_prompt = input_data.analysis_prompt
    retrieved_data = input_data.retrieved_data

    # Input validation is implicitly handled by Pydantic, but we check db separately
    # as it's type 'Any'
    if not db_session:
        error_msg = "Missing database session."
        logger.error(error_msg, extra={"props": log_props})
        # We might not be able to update status if db is missing
        return {"status": "error", "error_message": error_msg, "task_id": task_id}

    # --- Status Update: Set to RUNNING (or RETRYING by utils) --- #
    # This will run on the first attempt and subsequent retries
    is_first_attempt = True # Simplistic way, tenacity context is better if needed
    try:
        # Determine if this is a retry attempt to set RETRYING status
        # Tenacity context isn't easily accessible here without class structure
        # Relying on update_agent_task_status internal logic (if it checks retry_count)
        # or just setting RUNNING each time is acceptable for now.
        current_status = AgentTaskStatus.RUNNING # Assume RUNNING unless logic determines RETRYING

        # Check current status from DB before updating? Could add overhead.
        # Let's assume setting RUNNING/RETRYING via utils is sufficient.
        # The `update_agent_task_status` util likely needs `retry_count` passed.
        # For simplicity here, we won't fetch the attempt number from tenacity context.

        await update_agent_task_status(db_session, task_id, current_status) # Pass retry_count if util handles it
        logger.info("Quantitative analysis attempt starting.", extra={"props": log_props})

    except Exception as update_err:
        logger.error(
            f"Failed to update status before processing: {update_err}",
            extra={"props": log_props},
        )
        # If status update fails, we probably shouldn't proceed. Raise to trigger retry/failure.
        raise RuntimeError(f"DB Error setting status: {update_err}") from update_err
    # --- End Status Update --- #

    try:
        logger.info(
            f"Preparing quantitative analysis prompt: {analysis_prompt[:50]}...",
            extra={"props": log_props},
        )

        # Use await with aget_llm_client
        qa_llm = await aget_llm_client(
            db=db_session, user_id=user_id, model_type="tool"
        )

        # Format the prompt using the function from prompts.py
        prompt = format_quantitative_analysis_prompt(
            analysis_prompt=analysis_prompt, retrieved_data=retrieved_data
        )

        # Define the analysis chain (output is expected to be a string or structured data)
        # Using StrOutputParser here, might need JsonOutputParser if structured output is required
        analysis_chain = qa_llm | StrOutputParser()

        logger.info(
            f"Invoking quantitative analysis LLM ({qa_llm.model_name}).",
            extra={"props": log_props},
        )
        # Use await for async chain invocation
        analysis_result = await analysis_chain.ainvoke(prompt)
        # --- End LLM Integration ---

        logger.info(
            "Quantitative analysis completed successfully.", extra={"props": log_props}
        )
        # Use await for status update
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
        # This block is reached if the core logic fails on a given attempt
        logger.warning(
            f"Error during quantitative analysis attempt: {e}",
            exc_info=True, # Log traceback for the warning
            extra={"props": log_props},
        )
        error_message = str(e)
        # --- Update Status to FAILED on Final Attempt --- #
        # The retry decorator (`reraise=True`) will re-raise the exception after exhaustion.
        # The caller (worker callback) should catch this final exception and mark as FAILED.
        # However, setting FAILED here *before* raising ensures DB state is updated
        # even if the caller fails to handle the exception properly.
        # We only do this if we detect it's the last attempt (difficult without context)
        # Alternative: Let the caller handle the final FAILED status update.

        # For now, let's rely on the caller (worker callback) to handle the final FAILED status
        # based on the exception raised by tenacity after exhaustion.
        # We will just raise the exception here to trigger tenacity's retry/reraise.
        raise e
        # --- End Final Status Update Logic --- #


# Instantiate the runnable for this department
quantitative_analysis_runnable = RunnableLambda(
    _perform_quantitative_analysis
).with_types(input_type=QuantitativeAnalysisInput)
