import asyncio
import json
import logging
import signal
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.constants import (
    C2_RECOMMENDATION_GENERATION_QUEUE,
    AgentTaskStatus,
)

# Updated department imports
from app.agents.departments.recommendation_generation import (
    RecommendationGenerationInput,
    recommendation_generation_runnable,
)

# Updated Queue
from app.agents.utils import update_agent_task_status
from app.database import AsyncSessionLocal, current_user_id_cv, get_async_db_session_with_rls
from app.services.queue_client import RABBITMQ_URL, QueueClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_recommendation_generation")  # Updated Logger Name


async def process_recommendation_generation_message(
    message: AbstractIncomingMessage,
) -> bool:
    # Initialize context vars for logging
    log_props = {
        "message_id": str(message.message_id),
        "department": "Recommendation Generation",
    }
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    analysis_request_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        logger.info("Received RG message", extra={"props": log_props})
        logger.debug(f"RG Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        task_id_str = data.get("task_id")
        user_id_str = data.get("user_id")
        analysis_request_id_str = data.get("analysis_request_id")
        shop_domain = data.get("shop_domain")
        task_details = data.get(
            "task_details"
        )  # Contains recommendation_prompt and analysis_results
        # analysis_results = task_details.get("analysis_results") # Original - Handled by input schema now
        # if not analysis_results:
        #     analysis_results = data.get("analysis_results") # Fallback

        # Add IDs to log_props
        log_props["task_id"] = task_id_str
        log_props["user_id"] = user_id_str
        log_props["analysis_request_id"] = analysis_request_id_str

        # Check required fields
        if not all(
            [
                task_id_str,
                user_id_str,
                analysis_request_id_str,
                shop_domain,
                task_details,
            ]
        ):
            logger.error(
                "Invalid RG message format",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False

        try:
            task_id = uuid.UUID(task_id_str)
            user_id = uuid.UUID(user_id_str)
            analysis_request_id = uuid.UUID(analysis_request_id_str)
            # Update props with UUID strings
            log_props["task_id"] = str(task_id)
            log_props["user_id"] = str(user_id)
            log_props["analysis_request_id"] = str(analysis_request_id)
        except ValueError:
            logger.error(
                "Invalid UUID format in RG message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False

        logger.info("Processing RG Task", extra={"props": log_props})

        runnable_success = False
        runnable_error_message = "Task processing failed unexpectedly."

        async with get_async_db_session_with_rls(user_id) as db:  # db is AsyncSession
            try:
                # Let runnable handle status updates
                # recommendation_prompt = task_details.get("recommendation_prompt", "Generate recommendations...")
                analysis_results = task_details.get(
                    "analysis_results", {}
                )  # Get analysis results

                input_data = RecommendationGenerationInput(
                    db=db,  # Pass AsyncSession
                    user_id=user_id,
                    analysis_request_id=analysis_request_id,
                    shop_domain=shop_domain,
                    task_id=task_id,
                    # task_details=task_details, # Pass individual fields
                    recommendation_prompt=task_details.get(
                        "recommendation_prompt",
                        "Generate recommendations based on the provided analysis.",
                    ),
                    analysis_results=analysis_results,
                )

                # Use await for async runnable
                result_dict = await recommendation_generation_runnable.ainvoke(
                    input_data
                )

                if result_dict.get("status") == "success":
                    runnable_success = True
                    logger.info(
                        "RG Task completed successfully (status updated by runnable).",
                        extra={"props": log_props},
                    )
                    # Status update handled by runnable
                else:
                    runnable_error_message = result_dict.get(
                        "error_message", "Task failed without specific error message."
                    )
                    logger.error(
                        f"RG Task failed (status updated by runnable): {runnable_error_message}",
                        extra={"props": log_props},
                    )
                    runnable_success = False  # Explicitly set failure

            except Exception as invoke_err:
                runnable_error_message = f"Error during task invocation: {invoke_err}"
                logger.exception(
                    "Critical error invoking RG runnable",
                    exc_info=True,
                    extra={"props": log_props},
                )
                try:
                    # Use await for status update
                    await update_agent_task_status(
                        db,
                        task_id,
                        AgentTaskStatus.FAILED,
                        error_message=runnable_error_message,
                    )
                except Exception:
                    logger.error(
                        "Failed to update task status to FAILED after error",
                        exc_info=True,
                        extra={"props": log_props},
                    )
                runnable_success = False
            # Commit/Rollback handled by context manager

        return runnable_success

    except json.JSONDecodeError:
        logger.error(
            "Failed to decode JSON from message body", extra={"props": log_props}
        )
        return False
    except ValueError:
        logger.error(
            "Invalid UUID format in RG message",
            exc_info=True,
            extra={"props": log_props},
        )
        return False
    except Exception:
        final_log_props = (
            log_props
            if task_id
            else {
                "message_id": str(message.message_id),
                "department": "Recommendation Generation",
            }
        )
        logger.error(
            "Critical error in RG process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        # Attempting DB update is difficult here
        return False


stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"RG Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info(
        "Starting Recommendation Generation Worker Service (C2)..."
    )  # Updated Log Message

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()
        # Updated Queue Name
        await queue_client.consume_messages(
            queue_name=C2_RECOMMENDATION_GENERATION_QUEUE,
            callback=process_recommendation_generation_message,  # Updated Callback
        )
        logger.info(
            f"RG Worker: Consuming messages from queue: {C2_RECOMMENDATION_GENERATION_QUEUE}"  # Updated Log Message
        )
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("RG Worker: Main task cancelled.")  # Updated Log Prefix
    except Exception as e:
        logger.critical(
            f"RG Worker: Critical error: {e}", exc_info=True
        )  # Updated Log Prefix
    finally:
        logger.info("RG Worker: Shutting down...")  # Updated Log Prefix
        await queue_client.close()
        logger.info("RG Worker: Shutdown complete.")  # Updated Log Prefix


if __name__ == "__main__":
    asyncio.run(main())
