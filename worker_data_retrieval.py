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

# Agent Task Status and Queue constants
from app.agents.constants import C2_DATA_RETRIEVAL_QUEUE, AgentTaskStatus

# Department-specific runnable and input schema
from app.agents.departments.data_retrieval import (
    DataRetrievalInput,
    data_retrieval_runnable,
)

# Agent utility for status updates
from app.agents.utils import update_agent_task_status

# Database session factory
from app.database import AsyncSessionLocal, current_user_id_cv

# Queue Client
from app.services.queue_client import RABBITMQ_URL, QueueClient

# Basic Logging Setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_data_retrieval")


# --- RLS Context Setting Function (copied/adapted from worker.py) ---
# Removed - Now handled by get_db_session_with_context
# async def set_db_session_context(session: Session, user_id: uuid.UUID):
#    ...


# --- Database Context Management (Async with RLS) ---
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
                f"Failed to set RLS context for user {user_id} in DR worker: {e}",
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
        except SQLAlchemyError as e:  # Catch specific DB errors
            logger.error(
                f"Database error during session for user {user_id} in DR worker: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await db.rollback()  # Rollback asynchronously
            raise
        except Exception as e:  # Catch other errors
            logger.error(
                f"Unexpected error during session for user {user_id} in DR worker: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await db.rollback()  # Rollback asynchronously
            raise
        finally:
            if rls_set_success:
                try:
                    await db.execute(text("RESET app.current_user_id;"))
                except Exception as e:
                    logger.warning(
                        f"Failed to reset RLS context for user {user_id} in DR worker: {e}",
                        extra={"props": {"user_id": str(user_id)}},
                    )
            await db.close()  # Close asynchronously
            current_user_id_cv.set(None)


# --- Message Processing Logic ---
async def process_data_retrieval_message(message: AbstractIncomingMessage) -> bool:
    """Callback function to process a single message from the data retrieval queue.
    Returns True if processing was successful (message should be ACKed),
    False otherwise (message should be NACKed/rejected).
    """
    # Initialize context vars for logging
    log_props = {"message_id": str(message.message_id), "department": "Data Retrieval"}
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    analysis_request_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        logger.info("Received DR message", extra={"props": log_props})
        logger.debug(f"DR Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        task_id_str = data.get("task_id")
        user_id_str = data.get("user_id")
        analysis_request_id_str = data.get("analysis_request_id")
        shop_domain = data.get("shop_domain")
        task_details = data.get("task_details")

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
                "Invalid DR message format",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False

        try:
            task_id = uuid.UUID(task_id_str)
            user_id = uuid.UUID(user_id_str)
            analysis_request_id = uuid.UUID(analysis_request_id_str)
            current_user_id_cv.set(user_id)  # Set context var
            log_props["task_id"] = str(task_id)
            log_props["user_id"] = str(user_id)
            log_props["analysis_request_id"] = str(analysis_request_id)
        except ValueError:
            logger.error(
                "Invalid UUID format in DR message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            current_user_id_cv.set(None)
            return False

        logger.info("Processing DR Task", extra={"props": log_props})

        runnable_success = False
        runnable_error_message = "Task processing failed unexpectedly."

        # Use the async context manager with user_id
        async with get_db_session_with_context(user_id) as db:
            try:
                # Update task status to RUNNING (use await)
                try:
                    # Pass AsyncSession to update function
                    await update_agent_task_status(db, task_id, AgentTaskStatus.RUNNING)
                    logger.info(
                        "Updated DR Task status to RUNNING.", extra={"props": log_props}
                    )
                except Exception as status_update_err:
                    logger.error(
                        f"Failed to update DR task status to RUNNING: {status_update_err}",
                        extra={"props": log_props},
                    )
                    # Continue processing, but log the error

                input_data = DataRetrievalInput(
                    db=db,  # Pass the AsyncSession
                    user_id=user_id,
                    shop_domain=shop_domain,
                    task_id=task_id,
                    analysis_request_id=analysis_request_id,
                    task_details=task_details,
                )

                logger.info(
                    "Invoking data_retrieval_runnable asynchronously.",
                    extra={"props": log_props},
                )
                result_dict = await data_retrieval_runnable.ainvoke(input_data)
                logger.info(
                    "data_retrieval_runnable finished.", extra={"props": log_props}
                )

                if result_dict.get("status") == "success":
                    runnable_success = True
                    # Status update (COMPLETED) now happens inside the runnable/utils using AsyncSession
                    logger.info(
                        "DR Task completed successfully (status updated by runnable).",
                        extra={"props": log_props},
                    )
                else:
                    runnable_success = False
                    # Status update (FAILED) now happens inside the runnable/utils using AsyncSession
                    runnable_error_message = result_dict.get(
                        "error_message", "Task failed without specific error message."
                    )
                    logger.error(
                        f"DR Task failed (status updated by runnable): {runnable_error_message}",
                        extra={"props": log_props},
                    )

            except Exception as invoke_err:
                runnable_success = False
                runnable_error_message = (
                    f"Error during task invocation wrapper: {invoke_err}"
                )
                logger.exception(
                    "Critical error invoking DR runnable (in worker callback)",
                    exc_info=True,
                    extra={"props": log_props},
                )
                try:
                    # Attempt to mark as FAILED if not already handled by inner logic (use await)
                    await update_agent_task_status(
                        db,
                        task_id,
                        AgentTaskStatus.FAILED,
                        error_message=runnable_error_message,
                    )
                except Exception:
                    logger.error(
                        "Failed to update task status to FAILED after worker callback error",
                        exc_info=True,
                        extra={"props": log_props},
                    )
            # Commit/Rollback handled by context manager

        return runnable_success

    except json.JSONDecodeError:
        logger.error(
            "Failed to decode JSON from message body", extra={"props": log_props}
        )
        return False
    except ValueError:
        logger.error(
            "Invalid UUID format in DR message",
            exc_info=True,
            extra={"props": log_props},
        )
        return False
    except Exception:
        final_log_props = (
            log_props
            if task_id
            else {"message_id": str(message.message_id), "department": "Data Retrieval"}
        )
        logger.error(
            "Critical error in DR process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        # Attempting DB update here is difficult without user_id/async context
        return False
    finally:
        # Ensure context var is reset
        if "current_user_id_cv" in locals() and current_user_id_cv.get() is not None:
            current_user_id_cv.set(None)


# --- Worker Lifecycle ---
stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"DR Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info("Starting Data Retrieval Worker Service (C2)...")

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()

        # Start consuming from the specific department queue
        await queue_client.consume_messages(
            queue_name=C2_DATA_RETRIEVAL_QUEUE,
            callback=process_data_retrieval_message,  # Use the async callback
        )
        logger.info(
            f"DR Worker: Consuming messages from queue: {C2_DATA_RETRIEVAL_QUEUE}"
        )

        # Keep running until stop event is set
        await stop_event.wait()

    except asyncio.CancelledError:
        logger.info("DR Worker: Main task cancelled.")
    except Exception as e:
        logger.critical(f"DR Worker: Critical error: {e}", exc_info=True)
    finally:
        logger.info("DR Worker: Shutting down...")
        await queue_client.close()
        logger.info("DR Worker: Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
