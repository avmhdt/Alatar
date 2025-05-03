import asyncio
import logging
import signal
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.orm import Session

from app.database import SessionLocal

# TODO: Import runnable and input schema from app.agents.departments.comparative_analysis
# from app.agents.departments.comparative_analysis import (
#     comparative_analysis_runnable,
#     ComparativeAnalysisInput,
# )
from app.services.queue_client import RABBITMQ_URL, QueueClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_comparative_analysis")


# TODO: Implement RLS context setting (copy from other workers)
async def set_db_session_context(session: Session, user_id: uuid.UUID):
    pass


# TODO: Implement async DB context manager (copy from other workers)
@asynccontextmanager
async def get_db_session_with_context(
    user_id: uuid.UUID,
) -> AsyncGenerator[Session, None]:
    db = SessionLocal()
    try:
        # await set_db_session_context(db, user_id)
        yield db
    finally:
        # await db.close()
        pass  # Replace with actual close


# TODO: Implement message processing logic
async def process_comparative_analysis_message(
    message: AbstractIncomingMessage,
) -> bool:
    logger.warning("Comparative Analysis worker not implemented yet.")
    # Basic NACK, message will go to DLQ if configured
    await message.reject(requeue=False)
    return False


stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"CompA Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info(
        "Starting Comparative Analysis Worker Service (C2) - NOT IMPLEMENTED..."
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()
        # TODO: Define C2_COMPARATIVE_ANALYSIS_QUEUE in constants.py
        # TODO: Declare the queue in queue_client.connect()
        # await queue_client.consume_messages(
        #     queue_name=C2_COMPARATIVE_ANALYSIS_QUEUE,
        #     callback=process_comparative_analysis_message,
        # )
        # logger.info(
        #     f"CompA Worker: Consuming messages from queue: {C2_COMPARATIVE_ANALYSIS_QUEUE}"
        # )
        logger.warning("Comparative Analysis queue consumption is disabled.")
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("CompA Worker: Main task cancelled.")
    except Exception as e:
        logger.critical(f"CompA Worker: Critical error: {e}", exc_info=True)
    finally:
        logger.info("CompA Worker: Shutting down...")
        await queue_client.close()
        logger.info("CompA Worker: Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
