import asyncio
import logging
import signal
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.orm import Session

from app.database import SessionLocal

# TODO: Import runnable and input schema from app.agents.departments.predictive_analysis
# from app.agents.departments.predictive_analysis import (
#     predictive_analysis_runnable,
#     PredictiveAnalysisInput,
# )
from app.services.queue_client import RABBITMQ_URL, QueueClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_predictive_analysis")


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
async def process_predictive_analysis_message(message: AbstractIncomingMessage) -> bool:
    logger.warning("Predictive Analysis worker not implemented yet.")
    # Basic NACK, message will go to DLQ if configured
    await message.reject(requeue=False)
    return False


stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"PredA Worker: Received signal {sig}, shutting down...",
        extra={"props": {"signal": sig}},
    )
    stop_event.set()


async def main():
    logger.info("Starting Predictive Analysis Worker Service (C2) - NOT IMPLEMENTED...")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)

    try:
        await queue_client.connect()
        # TODO: Define C2_PREDICTIVE_ANALYSIS_QUEUE in constants.py
        # TODO: Declare the queue in queue_client.connect()
        # await queue_client.consume_messages(
        #     queue_name=C2_PREDICTIVE_ANALYSIS_QUEUE,
        #     callback=process_predictive_analysis_message,
        # )
        # logger.info(
        #     f"PredA Worker: Consuming messages from queue: {C2_PREDICTIVE_ANALYSIS_QUEUE}"
        # )
        logger.warning("Predictive Analysis queue consumption is disabled.")
        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("PredA Worker: Main task cancelled.")
    except Exception as e:
        logger.critical(f"PredA Worker: Critical error: {e}", exc_info=True)
    finally:
        logger.info("PredA Worker: Shutting down...")
        await queue_client.close()
        logger.info("PredA Worker: Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
