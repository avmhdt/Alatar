# Skeleton file for Comparative Analysis department

import logging
import uuid
from typing import Any
import json # Import json for placeholder

# --- Tenacity for Retries --- #
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
# --- End Tenacity --- #

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_core.pydantic_v1 import BaseModel, Field # Import Pydantic
from sqlalchemy.ext.asyncio import AsyncSession # Import AsyncSession

# Import constants and utils
from app.agents.constants import DEFAULT_RETRY_LIMIT, AgentTaskStatus
# from app.agents.prompts import format_comparison_prompt  # Assumes prompt exists - COMMENTED OUT
from app.agents.utils import aget_llm_client, update_agent_task_status # Use async utils

logger = logging.getLogger(__name__)


# --- Helper: Build Log Props --- #
def _get_ca_log_props(input_data: "ComparativeAnalysisInput") -> dict:
    return {
        "task_id": str(input_data.task_id),
        "user_id": str(input_data.user_id),
        "analysis_request_id": str(input_data.analysis_request_id),
    }


class ComparativeAnalysisInput(BaseModel):
    db: AsyncSession  # Expect AsyncSession
    user_id: uuid.UUID
    task_id: uuid.UUID
    analysis_request_id: uuid.UUID
    task_details: dict[str, Any] = Field(default={})
    aggregated_data: dict[str, Any] = Field(...) # Data from previous steps (DR, QA)

    class Config:
        arbitrary_types_allowed = True

# Define retry parameters
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
async def _run_comparative_analysis(input_data: ComparativeAnalysisInput) -> dict[str, Any]:
    log_props = _get_ca_log_props(input_data)
    logger.info(f"Running comparative analysis for task {input_data.task_id}", extra={"props": log_props})

    db_session = input_data.db
    task_id = input_data.task_id

    # --- Status Update: Set to RUNNING --- #
    try:
        await update_agent_task_status(db_session, task_id, AgentTaskStatus.RUNNING)
        logger.info("Comparative analysis attempt starting.", extra={"props": log_props})
    except Exception as update_err:
        logger.error(
            f"Failed to update status before processing: {update_err}",
            extra={"props": log_props},
        )
        raise RuntimeError(f"DB Error setting status: {update_err}") from update_err
    # --- End Status Update --- #

    try:
        # Get async LLM client
        llm = await aget_llm_client(
            db=db_session, user_id=input_data.user_id, model_type="tool" # Use 'tool' or 'aggregator'?
        )

        # TODO: Use a proper formatted prompt from app.agents.prompts
        # prompt = format_comparison_prompt(
        #     task_request=input_data.task_details.get(
        #         "request", "Compare provided data."
        #     ),
        #     data_to_compare=input_data.aggregated_data,
        # )
        # --- Placeholder for prompt --- #
        prompt_str = f"Compare data: {json.dumps(input_data.aggregated_data, indent=2, default=str)}" # TEMPORARY
        # --- End Placeholder --- #

        chain = llm | StrOutputParser()
        logger.info(f"Invoking comparative analysis LLM ({llm.model_name}).", extra={"props": log_props})
        # Use await for async invocation
        comparison_result = await chain.ainvoke(prompt_str)

        logger.info(f"Comparative analysis completed for task {task_id}", extra={"props": log_props})
        await update_agent_task_status(
            db_session,
            task_id,
            AgentTaskStatus.COMPLETED,
            result=comparison_result
        )
        return {
            "status": "success",
            "result": comparison_result, # Return raw string for now
            "task_id": task_id,
        }
    except Exception as e:
        logger.warning(
            f"Error during comparative analysis attempt: {e}",
            exc_info=True,
            extra={"props": log_props},
        )
        # Let tenacity handle retry/reraise - final FAILED status by worker callback
        raise e


comparative_analysis_runnable = RunnableLambda(_run_comparative_analysis).with_types(
    input_type=ComparativeAnalysisInput
)
