import uuid
from app.services.queue_client import QueueClient, RABBITMQ_URL
from app.agents.constants import INPUT_QUEUE as QUEUE_C1_INPUT
import logging

logger = logging.getLogger(__name__)

class AnalysisQueueService:
    def __init__(self):
        # Initialize QueueClient here or pass it in
        self.queue_client = QueueClient(RABBITMQ_URL)

    async def enqueue_request(
        self,
        analysis_request_id: uuid.UUID,
        user_id: uuid.UUID,
        prompt: str,
        shop_domain: str,
    ):
        """Enqueues an analysis request message to the C1 input queue."""
        message_body = {
            "analysis_request_id": str(analysis_request_id),
            "user_id": str(user_id),
            "prompt": prompt,
            "shop_domain": shop_domain,
        }
        try:
            await self.queue_client.connect()
            await self.queue_client.publish_message(QUEUE_C1_INPUT, message_body)
            logger.info(
                f"Successfully enqueued analysis request {analysis_request_id}",
                extra={
                    "props": {
                        "analysis_request_id": str(analysis_request_id),
                        "user_id": str(user_id),
                    }
                },
            )
        except Exception as e:
            logger.error(
                f"Failed to enqueue analysis request {analysis_request_id}: {e}",
                exc_info=True,
                extra={
                    "props": {
                        "analysis_request_id": str(analysis_request_id),
                        "user_id": str(user_id),
                    }
                },
            )
            # Re-raise or handle the error appropriately (e.g., mark request as failed)
            raise
        finally:
            await self.queue_client.close() 