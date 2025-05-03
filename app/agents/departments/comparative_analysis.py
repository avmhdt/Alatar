# Skeleton file for Comparative Analysis department

import logging
import uuid
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel
from sqlalchemy.orm import Session  # Assuming sync session for now

# from app.agents.prompts import format_comparison_prompt  # Assumes prompt exists - COMMENTED OUT
from app.agents.utils import aget_llm_client  # Use async version

logger = logging.getLogger(__name__)


class ComparativeAnalysisInput(BaseModel):
    db: Session  # Assuming sync session based on get_llm_client
    user_id: uuid.UUID
    task_id: uuid.UUID
    analysis_request_id: uuid.UUID
    task_details: dict[str, Any]
    aggregated_data: dict[str, Any]  # Data from previous steps (DR, QA)

    class Config:
        arbitrary_types_allowed = True


def _run_comparative_analysis(input_data: ComparativeAnalysisInput) -> dict[str, Any]:
    logger.info(f"Running comparative analysis for task {input_data.task_id}")
    comparison_result = None  # Define outside try
    status = "error"  # Default status
    result_payload = {}
    error_message = "Unknown error"
    try:
        # llm = get_llm_client(
        llm = aget_llm_client(  # Use async version
            db=input_data.db, user_id=input_data.user_id, model_type="aggregator"
        )  # Use aggregator/complex model
        # prompt = format_comparison_prompt( # COMMENTED OUT - function not found
        #     task_request=input_data.task_details.get(
        #         "request", "Compare provided data."
        #     ),
        #     data_to_compare=input_data.aggregated_data,
        # )
        # --- Placeholder for prompt --- #
        prompt = "Compare data: " + str(input_data.aggregated_data)  # TEMPORARY
        # --- End Placeholder --- #

        chain = (
            prompt | llm | StrOutputParser()
        )  # Assuming simple string output for now
        comparison_result = chain.invoke({})
        # Removed logger info and return from here
        status = "success"  # Set status on success

    except Exception as e:
        # logger.exception( # TRY401 Remove exception from call
        #     f"Error during comparative analysis for task {input_data.task_id}: {e}" # G004
        # )
        logger.exception(  # TRY401/G004 Fix
            "Error during comparative analysis for task %s",
            input_data.task_id,  # G004 Fix
        )
        # error_message = f"Comparative analysis failed: {e}" # Already captured by logger.exception
        error_message = f"Comparative analysis failed: {e}"

    else:  # TRY300 Add else block
        # This block runs only if the try block succeeded without exception
        logger.info(  # G004 Fix
            "Comparative analysis completed for task %s", input_data.task_id
        )
        result_payload = {"comparison_summary": comparison_result}

    # Common return structure
    if status == "success":
        return {
            "status": status,
            "result": result_payload,
            "task_id": input_data.task_id,
        }
    else:
        return {
            "status": status,
            "error_message": error_message,
            "task_id": input_data.task_id,
        }


comparative_analysis_runnable = RunnableLambda(_run_comparative_analysis).with_types(
    input_type=ComparativeAnalysisInput
)
