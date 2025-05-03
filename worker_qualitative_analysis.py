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
    C2_QUALITATIVE_ANALYSIS_QUEUE,
    AgentTaskStatus,
)

# Updated department imports
from app.agents.departments.qualitative_analysis import (
    QualitativeAnalysisInput,
    qualitative_analysis_runnable,
)

# Updated Queue
from app.agents.utils import update_agent_task_status
from app.database import AsyncSessionLocal, current_user_id_cv, get_async_db_session_with_rls
from app.services.queue_client import RABBITMQ_URL, QueueClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_qualitative_analysis")  # Updated Logger Name


async def process_qualitative_analysis_message(
    message: AbstractIncomingMessage,
) -> bool:
    # Initialize context vars for logging
    log_props = {
        "message_id": str(message.message_id),
        "department": "Qualitative Analysis",
    }
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    analysis_request_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        logger.info("Received QL message", extra={"props": log_props})
        logger.debug(f"QL Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        task_id_str = data.get("task_id")
        user_id_str = data.get("user_id")
        analysis_request_id_str = data.get("analysis_request_id")
        shop_domain = data.get("shop_domain")
        task_details = data.get("task_details")  # Contains analysis_prompt
        retrieved_data = task_details.get("retrieved_data")  # Match input schema
        if not retrieved_data:
            retrieved_data = data.get("retrieved_data")  # Fallback

        # Add IDs to log_props
        log_props["task_id"] = task_id_str
        log_props["user_id"] = user_id_str
        log_props["analysis_request_id"] = analysis_request_id_str

        # Adjusted check based on input schema
        if not all(
            [
                task_id_str,
                user_id_str,
                analysis_request_id_str,
                shop_domain,
                task_details,
                retrieved_data,
            ]
        ):
            logger.error(
                "Invalid QL message format",
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
                "Invalid UUID format in QL message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False

        logger.info("Processing QL Task", extra={"props": log_props})

        runnable_success = False
        runnable_error_message = "Task processing failed unexpectedly."

        async with get_async_db_session_with_rls(user_id) as db:
            try:
                # Let runnable handle status updates
                # analysis_prompt = task_details.get("analysis_prompt", "Perform qualitative analysis.")

                input_data = QualitativeAnalysisInput(
                    db=db,  # Pass AsyncSession
                    user_id=user_id,
                    shop_domain=shop_domain,
                    task_id=task_id,
                    # analysis_request_id=analysis_request_id, # No longer in schema
                    # task_details=task_details, # Pass individual fields instead
                    analysis_prompt=task_details.get(
                        "analysis_prompt", "Perform qualitative analysis."
                    ),
                    retrieved_data=retrieved_data,
                )

                # Use await for async runnable
                result_dict = await qualitative_analysis_runnable.ainvoke(input_data)

                if result_dict.get("status") == "success":
                    runnable_success = True
                    logger.info(
                        "QL Task completed successfully (status updated by runnable).",
                        extra={"props": log_props},
                    )
                    # Status update now happens within the runnable
                    # await update_agent_task_status(db, task_id, AgentTaskStatus.COMPLETED, result=result_dict.get("result"))
                else:
                    runnable_error_message = result_dict.get(
                        "error_message", "Task failed without specific error message."
                    )
                    logger.error(
                        f"QL Task failed (status updated by runnable): {runnable_error_message}",
                        extra={"props": log_props},
                    )
                    # Status update now happens within the runnable
                    # await update_agent_task_status(db, task_id, AgentTaskStatus.FAILED, error_message=runnable_error_message)
                    runnable_success = False  # Explicitly set failure

            except Exception as invoke_err:
                runnable_error_message = f"Error during task invocation: {invoke_err}"
                logger.exception(
                    "Critical error invoking QL runnable",
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
            "Invalid UUID format in QL message",
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
                "department": "Qualitative Analysis",
            }
        )
        logger.error(
            "Critical error in QL process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        # Attempting DB update is difficult here
        return False


stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"QL Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info(
        "Starting Qualitative Analysis Worker Service (C2)..."
    )  # Updated Log Message

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()
        # Updated Queue Name
        await queue_client.consume_messages(
            queue_name=C2_QUALITATIVE_ANALYSIS_QUEUE,
            callback=process_qualitative_analysis_message,  # Updated Callback
        )
        logger.info(
            f"QL Worker: Consuming messages from queue: {C2_QUALITATIVE_ANALYSIS_QUEUE}"  # Updated Log Message
        )
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("QL Worker: Main task cancelled.")  # Updated Log Prefix
    except Exception as e:
        logger.critical(
            f"QL Worker: Critical error: {e}", exc_info=True
        )  # Updated Log Prefix
    finally:
        logger.info("QL Worker: Shutting down...")  # Updated Log Prefix
        await queue_client.close()
        logger.info("QL Worker: Shutdown complete.")  # Updated Log Prefix


if __name__ == "__main__":
    asyncio.run(main())
