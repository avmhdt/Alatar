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
    C2_QUANTITATIVE_ANALYSIS_QUEUE,
    AgentTaskStatus,
)

# Updated department imports
from app.agents.departments.quantitative_analysis import (
    QuantitativeAnalysisInput,
    quantitative_analysis_runnable,
)

# Updated Queue
from app.agents.utils import update_agent_task_status
from app.database import AsyncSessionLocal, current_user_id_cv
from app.services.queue_client import RABBITMQ_URL, QueueClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_quantitative_analysis")  # Updated Logger Name


@asynccontextmanager
async def get_db_session_with_context(
    user_id: uuid.UUID,
) -> AsyncGenerator[AsyncSession, None]:
    """Provides an async DB session context manager with RLS context set."""
    db: AsyncSession = AsyncSessionLocal()
    rls_set_success = False
    if user_id:
        try:
            await db.execute(
                text("SET LOCAL app.current_user_id = :user_id"),
                {"user_id": str(user_id)},
            )
            rls_set_success = True
        except Exception as e:
            logger.error(
                f"Failed to set RLS context for user {user_id} in QA worker: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await db.rollback()
            await db.close()
            current_user_id_cv.set(None)
            raise

    if rls_set_success or not user_id:
        try:
            yield db
            await db.commit()
        except SQLAlchemyError as e:
            logger.error(
                f"Database error during session for user {user_id} in QA worker: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await db.rollback()
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during session for user {user_id} in QA worker: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await db.rollback()
            raise
        finally:
            if rls_set_success:
                try:
                    await db.execute(text("RESET app.current_user_id;"))
                except Exception as e:
                    logger.warning(
                        f"Failed to reset RLS context for user {user_id} in QA worker: {e}",
                        extra={"props": {"user_id": str(user_id)}},
                    )
            await db.close()
            current_user_id_cv.set(None)


async def process_quantitative_analysis_message(
    message: AbstractIncomingMessage,
) -> bool:
    # Initialize context vars for logging
    log_props = {
        "message_id": str(message.message_id),
        "department": "Quantitative Analysis",
    }
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    analysis_request_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        logger.info("Received QA message", extra={"props": log_props})
        logger.debug(f"QA Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        task_id_str = data.get("task_id")
        user_id_str = data.get("user_id")
        analysis_request_id_str = data.get("analysis_request_id")
        shop_domain = data.get("shop_domain")
        task_details = data.get("task_details")
        retrieved_data = task_details.get("retrieved_data")
        if not retrieved_data:
            retrieved_data = data.get("retrieved_data")

        # Add IDs to log_props
        log_props["task_id"] = task_id_str
        log_props["user_id"] = user_id_str
        log_props["analysis_request_id"] = analysis_request_id_str

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
                "Invalid QA message format (missing fields)",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False

        try:
            task_id = uuid.UUID(task_id_str)
            user_id = uuid.UUID(user_id_str)
            analysis_request_id = uuid.UUID(analysis_request_id_str)
            current_user_id_cv.set(user_id)
            # Update props with UUID strings
            log_props["task_id"] = str(task_id)
            log_props["user_id"] = str(user_id)
            log_props["analysis_request_id"] = str(analysis_request_id)
        except ValueError:
            logger.error(
                "Invalid UUID format in QA message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            current_user_id_cv.set(None)
            return False

        logger.info("Processing QA Task", extra={"props": log_props})

        runnable_success = False
        runnable_error_message = "Task processing failed unexpectedly."

        async with get_db_session_with_context(user_id) as db:
            try:
                # Pass analysis_prompt from task_details
                analysis_prompt = task_details.get(
                    "analysis_prompt", "Perform quantitative analysis."
                )

                input_data = QuantitativeAnalysisInput(
                    db=db,
                    user_id=user_id,
                    task_id=task_id,
                    shop_domain=shop_domain,
                    analysis_prompt=analysis_prompt,
                    retrieved_data=retrieved_data,
                )
                result_dict = await quantitative_analysis_runnable.ainvoke(input_data)

                if result_dict.get("status") == "success":
                    runnable_success = True
                    logger.info(
                        "QA Task completed successfully (status updated by runnable).",
                        extra={"props": log_props},
                    )
                else:
                    runnable_error_message = result_dict.get(
                        "error_message", "Task failed without specific error message."
                    )
                    logger.error(
                        f"QA Task failed (status updated by runnable): {runnable_error_message}",
                        extra={"props": log_props},
                    )
                    runnable_success = False

            except Exception as invoke_err:
                runnable_error_message = f"Error during task invocation: {invoke_err}"
                logger.exception(
                    "Critical error invoking QA runnable",
                    exc_info=True,
                    extra={"props": log_props},
                )
                try:
                    await update_agent_task_status(
                        db,
                        task_id,
                        AgentTaskStatus.FAILED,
                        error_message=runnable_error_message,
                    )
                except Exception:
                    logger.error(
                        "Failed to update QA task status to FAILED after error",
                        exc_info=True,
                        extra={"props": log_props},
                    )
                runnable_success = False

        return runnable_success

    except json.JSONDecodeError:
        logger.error(
            "Failed to decode JSON from message body", extra={"props": log_props}
        )
        return False
    except ValueError:
        logger.error(
            "Invalid UUID format in QA message",
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
                "department": "Quantitative Analysis",
            }
        )
        logger.error(
            "Critical error in QA process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        return False
    finally:
        # Ensure context var is reset
        if "current_user_id_cv" in locals() and current_user_id_cv.get() is not None:
            current_user_id_cv.set(None)


stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"QA Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info(
        "Starting Quantitative Analysis Worker Service (C2)..."
    )  # Updated Log Message

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()
        # Updated Queue Name
        await queue_client.consume_messages(
            queue_name=C2_QUANTITATIVE_ANALYSIS_QUEUE,
            callback=process_quantitative_analysis_message,  # Updated Callback
        )
        logger.info(
            f"QA Worker: Consuming messages from queue: {C2_QUANTITATIVE_ANALYSIS_QUEUE}"  # Updated Log Message
        )
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("QA Worker: Main task cancelled.")  # Updated Log Prefix
    except Exception as e:
        logger.critical(
            f"QA Worker: Critical error: {e}", exc_info=True
        )  # Updated Log Prefix
    finally:
        logger.info("QA Worker: Shutting down...")  # Updated Log Prefix
        await queue_client.close()
        logger.info("QA Worker: Shutdown complete.")  # Updated Log Prefix


if __name__ == "__main__":
    asyncio.run(main())
