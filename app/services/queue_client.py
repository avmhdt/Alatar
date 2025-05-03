import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
DLX_NAME = "dlx.default"  # Default Dead Letter Exchange
DLQ_SUFFIX = ".dlq"  # Suffix for Dead Letter Queues

# Define Queue Names (as per implementation plan Section 6 & Phase 5)
# Queues for Class 1 Orchestrator Input
QUEUE_C1_INPUT = "q.c1_input"

# Queues for Class 2 Departments (Example, might need more)
QUEUE_C2_DATA_RETRIEVAL = "q.c2.data_retrieval"
QUEUE_C2_QUANTITATIVE_ANALYSIS = "q.c2.quantitative_analysis"
# Add other department queues as needed

# Potential Response Queues (If using direct reply-to or specific response queues)
# QUEUE_RESPONSE_PREFIX = "q.response."


class QueueClient:
    """Handles connection and communication with RabbitMQ."""

    def __init__(self, rabbitmq_url: str = RABBITMQ_URL):
        self.rabbitmq_url = rabbitmq_url
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._consumers: dict[
            str, tuple[aio_pika.Queue, asyncio.Task]
        ] = {}  # Store queue_name -> (queue_obj, task)

    async def connect(self):
        """Establishes connection and channel."""
        if self._connection and not self._connection.is_closed:
            logger.info("Already connected to RabbitMQ.")
            return
        try:
            logger.info(f"Connecting to RabbitMQ at {self.rabbitmq_url}...")
            self._connection = await aio_pika.connect_robust(self.rabbitmq_url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=10)  # Example QoS
            # Declare DLX first if it doesn't exist
            if not self._channel:
                raise ConnectionError(
                    "Cannot declare exchange, channel is not available."
                )
            await self._channel.declare_exchange(DLX_NAME, type="direct", durable=True)
            logger.info(f"Declared Dead Letter Exchange: {DLX_NAME}")
            logger.info("Successfully connected to RabbitMQ.")
            # Declare core queues on connection
            await self.declare_queue(QUEUE_C1_INPUT, use_dlq=True)
            await self.declare_queue(QUEUE_C2_DATA_RETRIEVAL, use_dlq=True)
            await self.declare_queue(QUEUE_C2_QUANTITATIVE_ANALYSIS, use_dlq=True)
            # Add declarations for other essential queues if known upfront
            # Declare action execution queue
            from app.agents.constants import QUEUE_ACTION_EXECUTION # Import late to avoid circularity if constants imports QueueClient
            await self.declare_queue(QUEUE_ACTION_EXECUTION, use_dlq=True)
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}", exc_info=True)
            self._connection = None
            self._channel = None
            # Consider adding retry logic or raising the exception

    async def close(self):
        """Closes channel and connection."""
        logger.info("Closing RabbitMQ connection...")
        # Stop consumers first
        for queue_name, (_, task) in self._consumers.items():
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Consumer task for queue '{queue_name}' cancelled.")
        self._consumers.clear()

        if self._channel and not self._channel.is_closed:
            await self._channel.close()
            logger.info("RabbitMQ channel closed.")
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            logger.info("RabbitMQ connection closed.")
        self._channel = None
        self._connection = None

    async def _ensure_connected(self):
        """Ensures connection is active before operations."""
        if (
            not self._connection
            or self._connection.is_closed
            or not self._channel
            or self._channel.is_closed
        ):
            logger.warning(
                "Connection lost or not established. Attempting to reconnect..."
            )
            await self.connect()
            if not self._channel:  # Check if reconnection succeeded
                raise ConnectionError(
                    "Failed to establish RabbitMQ connection/channel."
                )

    async def declare_queue(
        self, queue_name: str, durable: bool = True, use_dlq: bool = False, **kwargs
    ) -> aio_pika.Queue:
        """Declares a queue idempotently, optionally configuring a Dead Letter Queue (DLQ).

        Args:
        ----
            queue_name (str): Name of the main queue.
            durable (bool): Whether the queue should survive broker restarts.
            use_dlq (bool): If True, configures and declares associated DLQ infrastructure.
            **kwargs: Additional arguments for queue declaration.

        Returns:
        -------
            aio_pika.Queue: The declared main queue object.

        """
        await self._ensure_connected()

        arguments = kwargs.pop("arguments", {})
        if use_dlq:
            dlq_name = queue_name + DLQ_SUFFIX
            logger.info(
                f"Configuring DLQ for queue '{queue_name}'. DLQ: '{dlq_name}', DLX: '{DLX_NAME}"
            )
            # Declare the DLQ
            if not self._channel:
                raise ConnectionError("Cannot declare DLQ, channel is not available.")
            dlq_queue = await self._channel.declare_queue(dlq_name, durable=True)
            # Bind DLQ to the DLX with routing key = original queue name
            await dlq_queue.bind(exchange=DLX_NAME, routing_key=queue_name)

            arguments["x-dead-letter-exchange"] = DLX_NAME
            arguments["x-dead-letter-routing-key"] = (
                queue_name  # Route to DLQ using original name
            )

        logger.info(
            f"Declaring queue: {queue_name} (durable={durable}, arguments={arguments})"
        )
        if not self._channel:
            raise ConnectionError("Cannot declare queue, channel is not available.")
        return await self._channel.declare_queue(
            queue_name, durable=durable, arguments=arguments, **kwargs
        )

    async def publish_message(
        self,
        queue_name: str,
        message_body: dict,
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        **properties,
    ):
        """Publishes a JSON message to the specified queue."""
        await self._ensure_connected()
        try:
            message = aio_pika.Message(
                body=json.dumps(message_body).encode(),
                delivery_mode=delivery_mode,
                content_type="application/json",
                **properties,  # Allows passing correlation_id, reply_to etc.
            )
            if not self._channel:
                raise ConnectionError(
                    "Cannot publish message, channel is not available."
                )
            await self._channel.default_exchange.publish(
                message, routing_key=queue_name
            )
            logger.debug(f"Published message to queue '{queue_name}': {message_body}")
        except Exception as e:
            logger.error(
                f"Failed to publish message to queue '{queue_name}': {e}", exc_info=True
            )
            # Re-raise the exception so the caller is aware
            raise

    async def consume_messages(
        self,
        queue_name: str,
        callback: Callable[
            [AbstractIncomingMessage], Awaitable[bool]
        ],  # Callback returns True if message processing is successful
        durable: bool = True,
        use_dlq: bool = True,  # Assume consumers should use DLQ if available
    ):
        """Starts consuming messages from a specified queue."""
        await self._ensure_connected()

        if queue_name in self._consumers:
            logger.warning(
                f"Already consuming from queue '{queue_name}'. Skipping new consumer setup."
            )
            return

        queue = await self.declare_queue(queue_name, durable=durable, use_dlq=use_dlq)
        logger.info(f"Starting consumer for queue: {queue_name}")

        async def consumer_task_wrapper():
            consumer_tag = None
            try:
                async with queue.iterator() as queue_iter:
                    # Store consumer tag only after iterator starts successfully
                    # Note: Getting the actual consumer_tag might require accessing internal attributes
                    # or might not be directly available in a simple way with iterator.
                    # For explicit cancellation, storing the task is more reliable.
                    logger.info(f"Consumer iterator started for queue '{queue_name}'")
                    async for message in queue_iter:
                        async with message.process(
                            requeue=False, ignore_processed=True
                        ):  # Auto-nack on context exit unless explicitly acked/rejected
                            logger.debug(
                                f"Received message from '{queue_name}': {message.message_id}"
                            )
                            try:
                                success = await callback(message)
                                if success:
                                    # Explicitly ack only if callback confirms success
                                    # message.ack() # No need if using message.process() context manager correctly
                                    logger.debug(
                                        f"Message {message.message_id} processed successfully and acked."
                                    )
                                else:
                                    # Callback indicated failure, requeue=False based on process()
                                    # If specific requeue logic is needed, avoid process() context or reject manually
                                    await message.reject(
                                        requeue=False
                                    )  # Explicitly reject/nack
                                    logger.warning(
                                        f"Message {message.message_id} processed with failure, rejected (not requeued)."
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error processing message {message.message_id} from '{queue_name}': {e}",
                                    exc_info=True,
                                )
                                # Message will be nacked due to process() context exit on exception
                                await message.reject(
                                    requeue=False
                                )  # Explicitly reject/nack
            except asyncio.CancelledError:
                logger.info(f"Consumer task for queue '{queue_name}' cancelled.")
                # If consumer_tag was obtained, could use self._channel.basic_cancel(consumer_tag) here
            except aio_pika.exceptions.ChannelClosed:
                logger.warning(
                    f"Channel closed while consuming from '{queue_name}'. Attempting reconnect via _ensure_connected in outer loop if applicable."
                )
                # Consider removing from _consumers if reconnect fails persistently
                if queue_name in self._consumers:
                    del self._consumers[queue_name]  # Clean up on channel closure
            except Exception as e:
                logger.error(
                    f"Consumer for queue '{queue_name}' encountered an unhandled error: {e}",
                    exc_info=True,
                )
                # Clean up consumer entry if it stops unexpectedly
                if queue_name in self._consumers:
                    del self._consumers[queue_name]
            finally:
                logger.info(f"Consumer task for queue '{queue_name}' stopped.")
                # Ensure cleanup if task stops for any reason other than explicit cancellation during close()
                if queue_name in self._consumers:
                    _, task = self._consumers[queue_name]
                    if task.done():  # Remove if task finished/cancelled/errored
                        del self._consumers[queue_name]

        # Start the consumer task
        task = asyncio.create_task(consumer_task_wrapper())
        self._consumers[queue_name] = (queue, task)


# Global instance (optional, consider dependency injection)
# queue_client = QueueClient()

# Example usage (usually called from app startup/shutdown)
# async def main():
#     await queue_client.connect()
#     # Start consumers or publish messages
#     await queue_client.publish_message(QUEUE_C1_INPUT, {"test": "data"})
#     # Keep running or await specific tasks
#     await asyncio.sleep(10) # Keep alive for a bit
#     await queue_client.close()

# if __name__ == "__main__":
#     asyncio.run(main())
