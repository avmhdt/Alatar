"""In-memory Pub/Sub service for handling real-time updates (e.g., subscriptions)."""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)

# In-memory storage for subscriptions
# Format: {topic: {queue1, queue2, ...}} where queue is an asyncio.Queue
_subscriptions: defaultdict[str, set[asyncio.Queue]] = defaultdict(set)
_lock = asyncio.Lock()  # Lock for managing subscriptions safely


async def publish(topic: str, message: Any):
    """Publish a message to a topic."""
    logger.debug(f"Publishing to topic '{topic}': {message}")
    async with _lock:
        subscribers = _subscriptions.get(topic, set())
        if not subscribers:
            logger.debug(f"No subscribers for topic '{topic}'")
            return

        # Put the message into each subscriber's queue
        # Use list(subscribers) to avoid issues if a subscriber unsubscribes during iteration
        for queue in list(subscribers):
            try:
                await queue.put(message)
            except Exception as e:
                logger.error(f"Error putting message in queue for topic '{topic}': {e}")
                # Optionally remove the queue if it seems broken?


async def subscribe(topic: str) -> AsyncGenerator[Any, None]:
    """Subscribe to a topic and yield messages as they arrive."""
    queue = asyncio.Queue()
    logger.info(f"New subscription to topic '{topic}'")
    async with _lock:
        _subscriptions[topic].add(queue)

    try:
        while True:
            # Wait for a message on the queue
            message = await queue.get()
            logger.debug(f"Received message for topic '{topic}': {message}")
            yield message
            queue.task_done()
    except asyncio.CancelledError:
        logger.info(f"Subscription cancelled for topic '{topic}'")
        # Re-raise to ensure cleanup or handling up the stack
        raise
    except Exception as e:
        logger.error(f"Error in subscription generator for topic '{topic}': {e}")
        # Depending on the error, might want to break or continue
    finally:
        logger.info(f"Cleaning up subscription for topic '{topic}'")
        async with _lock:
            _subscriptions[topic].discard(queue)
            # Optional: clean up the topic entry if no subscribers left
            if not _subscriptions[topic]:
                del _subscriptions[topic]


# --- Specific Application Functions (Example) ---


def _get_analysis_request_topic(request_id: uuid.UUID) -> str:
    """Generate a consistent topic name for an analysis request."""
    return f"analysis_request:{request_id}"


async def publish_analysis_update(request_id: uuid.UUID, update_data: dict[str, Any]):
    """Publish an update specifically for an analysis request."""
    topic = _get_analysis_request_topic(request_id)
    await publish(topic, update_data)


async def subscribe_to_analysis_request(
    request_id: uuid.UUID,
) -> AsyncGenerator[dict[str, Any], None]:
    """Subscribe to updates for a specific analysis request."""
    topic = _get_analysis_request_topic(request_id)
    async for message in subscribe(topic):
        # Assume message is already the dict we need
        if isinstance(message, dict):
            yield message
        else:
            logger.warning(f"Received non-dict message on topic {topic}: {message}")
            # Decide how to handle unexpected message types
            continue


# --- Example Usage (for testing/demonstration) ---
async def _example_publisher(topic: str):
    count = 0
    while True:
        await asyncio.sleep(5)
        count += 1
        message = {"count": count, "timestamp": asyncio.get_event_loop().time()}
        await publish(topic, message)
        if count > 3:  # Stop after a few messages for demo
            break


async def _example_subscriber(topic: str, id: int):
    async for message in subscribe(topic):
        logger.info(f"Subscriber {id} received: {message}")
        # Simulate processing
        await asyncio.sleep(0.1)


async def _main_example():
    topic = "test_topic"
    # Start subscribers
    sub1_task = asyncio.create_task(_example_subscriber(topic, 1))
    sub2_task = asyncio.create_task(_example_subscriber(topic, 2))
    await asyncio.sleep(1)  # Allow subscribers to start

    # Start publisher
    pub_task = asyncio.create_task(_example_publisher(topic))

    await pub_task  # Wait for publisher to finish
    await asyncio.sleep(1)  # Allow final messages to be processed

    # Cancel subscribers
    sub1_task.cancel()
    sub2_task.cancel()
    try:
        await sub1_task
    except asyncio.CancelledError:
        logger.info("Subscriber 1 cancelled cleanly.")
    try:
        await sub2_task
    except asyncio.CancelledError:
        logger.info("Subscriber 2 cancelled cleanly.")


if __name__ == "__main__":
    # Run the example if the script is executed directly
    asyncio.run(_main_example())
