import logging
import uuid
from typing import Any

# from langchain_openai import ChatOpenAI # Removed direct import
from langchain_core.output_parsers import StrOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.runnables import RunnableLambda
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.constants import AgentTaskStatus
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


async def _perform_quantitative_analysis(
    input_data: QuantitativeAnalysisInput,
) -> dict[str, Any]:
    """Performs quantitative analysis using an LLM based on the provided instructions and data.
    Updates task status via the placeholder _update_task_status function.
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

    # Use await for status update
    try:
        await update_agent_task_status(db_session, task_id, AgentTaskStatus.RUNNING)
        logger.info("Starting quantitative analysis.", extra={"props": log_props})
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
        logger.exception(
            "Error during quantitative analysis",
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
quantitative_analysis_runnable = RunnableLambda(
    _perform_quantitative_analysis
).with_types(input_type=QuantitativeAnalysisInput)
