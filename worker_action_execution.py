import asyncio
import json
import logging
import signal
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Worker specific imports
from app.agents.constants import QUEUE_ACTION_EXECUTION # Consumes from this queue
from app.database import AsyncSessionLocal, current_user_id_cv, get_async_db_session_with_rls # Import shared utility
from app.services.queue_client import RABBITMQ_URL, QueueClient
from app.services.action_executor import execute_action_async # Import the execution logic

# Basic Logging Setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_action_execution")

# --- RLS Context Management (Async with RLS) ---
# REMOVED Local get_db_session_with_context - Use shared utility from app.database now
# @asynccontextmanager
# async def get_db_session_with_context(...):
#     ...

# --- Message Processing Logic ---
async def process_action_execution_message(message: AbstractIncomingMessage) -> bool:
    """Callback function to process a single message from the action execution queue.
    Returns True if message processing is successful (ACK), False otherwise (NACK/Reject).
    """
    log_props = {"message_id": str(message.message_id), "worker": "ActionExecution"}
    action_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        logger.info("Received Action Execution message", extra={"props": log_props})
        logger.debug(f"AE Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        action_id_str = data.get("action_id")
        user_id_str = data.get("user_id")

        if not all([action_id_str, user_id_str]):
            logger.error(
                "Invalid AE message format",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False # Reject message

        try:
            action_id = uuid.UUID(action_id_str)
            user_id = uuid.UUID(user_id_str)
            # Set context var for the duration of this task processing
            # Note: execute_action_async will re-set it for its own DB session management
            # We still need to set it here for potential calls *before* execute_action_async
            # if any were added, and reset it in the finally block.
            cv_token = current_user_id_cv.set(user_id)
            log_props["action_id"] = str(action_id)
            log_props["user_id"] = str(user_id)
        except ValueError:
            logger.error(
                "Invalid UUID format in AE message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            current_user_id_cv.set(None)
            return False # Reject message

        logger.info("Processing Action Execution Task", extra={"props": log_props})

        task_processed_successfully = False
        try:
            # Call the core execution logic
            await execute_action_async(action_id=action_id, user_id=user_id)
            # If execute_action_async completes without raising an exception,
            # consider the message processing successful, regardless of whether
            # the action itself failed logically (e.g., permissions, API error).
            # The action status in the DB reflects the logical outcome.
            task_processed_successfully = True
            logger.info("Action execution logic completed.", extra={"props": log_props})

        except Exception as exec_err:
            # This catches unexpected errors *within* execute_action_async or its call
            # execute_action_async should handle its internal errors and update DB status.
            # This block is for truly unexpected infrastructure/programming errors.
            logger.exception(
                "Critical unexpected error during execute_action_async call",
                exc_info=True,
                extra={"props": log_props},
            )
            task_processed_successfully = False # Message processing failed, reject/NACK
        finally:
            # Reset context var set at the start of this function
            if 'cv_token' in locals():
                 current_user_id_cv.reset(cv_token)

        # Return True to ACK the message if processing completed without infrastructure error
        return task_processed_successfully

    except json.JSONDecodeError:
        logger.error(
            "Failed to decode JSON from message body", extra={"props": log_props}
        )
        return False # Reject message
    except Exception as outer_err:
        # Catch errors during message parsing or initial setup
        final_log_props = log_props if action_id else {"message_id": str(message.message_id)}
        logger.error(
            "Critical error in AE process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        return False # Reject message
    finally:
        # Ensure context var is reset even on outer errors
        # This outer finally block ensures reset even if parsing/UUID conversion fails
        if "cv_token" in locals(): # Check if token was obtained before resetting
             current_user_id_cv.reset(cv_token)
        elif "current_user_id_cv" in locals() and current_user_id_cv.get() is not None:
             # Fallback clear if token wasn't assigned but var might be set
             current_user_id_cv.set(None)

# --- Worker Lifecycle ---
stop_event = asyncio.Event()

def handle_signal(sig, frame):
    logger.warning(
        f"AE Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()

async def main():
    logger.info("Starting Action Execution Worker Service...")

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()

        # Start consuming from the specific queue
        await queue_client.consume_messages(
            queue_name=QUEUE_ACTION_EXECUTION,
            callback=process_action_execution_message,
        )
        logger.info(
            f"AE Worker: Consuming messages from queue: {QUEUE_ACTION_EXECUTION}"
        )

        await stop_event.wait()

    except asyncio.CancelledError:
        logger.info("AE Worker: Main task cancelled.")
    except Exception as e:
        logger.critical(f"AE Worker: Critical error: {e}", exc_info=True)
    finally:
        logger.info("AE Worker: Shutting down...")
        await queue_client.close()
        logger.info("AE Worker: Shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main()) 