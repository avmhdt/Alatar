import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator

import aioredis
import strawberry
from sqlalchemy.orm import Session
from strawberry.channels import PubSub
from strawberry.types import Info

from app.core.redis_client import get_analysis_update_channel, get_redis_connection

# Import GQL types
from ..types.analysis_request import AnalysisRequest as AnalysisRequestGQL

# Import DB model (optional, if needed for initial fetch)
# from app.models.analysis_request import AnalysisRequest as AnalysisRequestModel

logger = logging.getLogger(__name__)

# --- PubSub Initialization ---
# Use strawberry.channels.PubSub for in-memory pub/sub
# For production, replace with RedisPubSub or similar
pubsub = PubSub()

# --- In-memory Pub/Sub (Replace with Redis/Broker for production) ---
# Simple dictionary to hold subscribers for different request IDs
subscribers = defaultdict(list)

# Simple Queue for broadcasting updates asynchronously
# Using asyncio.Queue for demonstration; use a proper broker (Redis PubSub, RabbitMQ) in production.
update_queue = asyncio.Queue()

# --- Event Publishing (called from C1 worker/orchestrator) ---
# Removed duplicate publisher function - publishing should happen elsewhere (e.g., worker via redis_client)
# async def publish_analysis_update(analysis_request_id: uuid.UUID, update_data: Dict[str, Any]):
#     """Publishes an update for a specific analysis request (IN-MEMORY VERSION)."""
#     logger.debug(
#         f"[In-Memory PubSub] Publishing update for request {analysis_request_id}"
#     )
#     await update_queue.put((str(analysis_request_id), update_data))

# --- Subscription Resolver ---

# Helper to map DB model to GQL type (if needed for initial state)
# def map_db_to_gql_analysis_request(db_obj: AnalysisRequestModel) -> AnalysisRequestGQL:
#    # ... mapping logic ...
#    pass

# Avoid circular import if possible - moved from within function
from .analysis_request import (
    get_analysis_request_by_uuid,
)


@strawberry.subscription
async def analysis_request_updates(
    root,
    info: Info,
    request_id: strawberry.ID,  # Changed to strawberry.ID for GQL consistency
) -> AsyncGenerator[AnalysisRequestGQL, None]:
    """Subscribe to real-time status and result updates for an AnalysisRequest using Redis Pub/Sub."""
    # Verify request_id format if needed (e.g., is it a UUID?)
    try:
        request_uuid = uuid.UUID(str(request_id))
    except ValueError:
        logger.warning(f"Invalid request_id format for subscription: {request_id}")
        # Optionally raise a GraphQL error or simply return
        return

    # Use global ID utilities if implemented later
    # type_name, pk = from_global_id(request_id)
    # if type_name != 'AnalysisRequest':
    #     raise ValueError("Invalid ID type for this subscription.")
    # request_uuid = uuid.UUID(pk)

    # Check user permission to subscribe to this request (using RLS/context)
    # Requires db session in context, assuming Context setup provides it
    db: Session = info.context.db
    # Use the function from the query resolver to check access
    # This ensures consistent permission checks

    # Fetch the request to ensure it exists and the user has access
    # Note: This fetch might happen *before* the subscription starts listening,
    # so it confirms initial access rights.
    initial_request = get_analysis_request_by_uuid(db, request_uuid)
    if not initial_request:
        logger.warning(
            f"Subscription attempt denied or request not found for ID: {request_uuid}"
        )
        # Don't yield anything if access denied / not found
        return

    logger.info(f"User subscribed to updates for AnalysisRequest ID: {request_uuid}")

    # --- Redis Subscription Logic ---
    redis = await get_redis_connection()
    channel_name = get_analysis_update_channel(str(request_uuid))
    pubsub = redis.pubsub()

    try:
        await pubsub.subscribe(channel_name)
        logger.debug(f"Subscribed to Redis channel: {channel_name}")

        # Yield the initial state first? (Optional)
        # yield AnalysisRequestGQL.from_orm(initial_request) # Convert DB model to GQL type

        # Listen for messages
        while True:
            # Use timeout to periodically check if client disconnected
            # Or rely on Strawberry/FastAPI to handle client disconnection cleanup
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                logger.debug(f"Received message from {channel_name}: {message['data']}")
                try:
                    update_data = json.loads(message["data"])
                    # TODO: Validate update_data schema
                    # Here, we assume the published data IS the full AnalysisRequest GQL structure
                    # or can be converted/validated into it.
                    # For simplicity, assuming it's the dictionary representation:
                    # Re-fetch from DB based on update? Or trust published data?
                    # Trusting published data is faster but less secure/consistent.
                    # Let's assume published data is sufficient for the GQL object:
                    # Need to ensure published data matches AnalysisRequestGQL fields.
                    # This might require adjustments in the publisher (worker.py)
                    # to send data in the correct GQL format.

                    # Attempt to yield the data directly (ASSUMES published data matches GQL type)
                    # This is brittle - ideally validate/convert update_data -> AnalysisRequestGQL
                    # For now, passing dict - Strawberry might handle it if types match
                    yield AnalysisRequestGQL(**update_data)  # Pass fields as kwargs

                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to decode JSON message from {channel_name}: {message['data']}"
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing message from {channel_name}: {e} - Data: {message.get('data')}"
                    )
            # Add a small sleep if no message to prevent tight loop if timeout is low/None
            await asyncio.sleep(0.01)

            # How to detect client disconnection?
            # Strawberry/FastAPI should handle closing the generator when the client disconnects.
            # If manual checks are needed, info.context.request.is_disconnected might work,
            # but accessing request directly might be tricky depending on context setup.

    except aioredis.ConnectionError as e:
        logger.error(
            f"Redis connection error during subscription for {channel_name}: {e}"
        )
        # Handle error appropriately, maybe raise to client?
    except Exception as e:
        logger.error(
            f"Unexpected error during subscription loop for {channel_name}: {e}"
        )
        # Handle error appropriately
    finally:
        logger.info(f"Unsubscribing from Redis channel: {channel_name}")
        if pubsub:
            await pubsub.unsubscribe(channel_name)
            # Ensure the pubsub connection is closed if necessary.
            # Closing the connection pool on shutdown should handle this.
            # await pubsub.close() # Might not be needed if using pool connection


# --- Old In-Memory Worker (Example - Replace with Redis Logic) ---
# async def broadcast_updates():
#     """Worker task to broadcast updates from the queue to subscribers (IN-MEMORY)."""
#     logger.info("[In-Memory PubSub] Broadcast worker started.")
#     while True:
#         try:
#             request_id_str, update_data = await update_queue.get()
#             logger.debug(
#                 f"[In-Memory PubSub] Processing update for {request_id_str}, Data: {update_data}"
#             )

#             sub_list = subscribers.get(request_id_str, [])
#             logger.debug(
#                 f"[In-Memory PubSub] Broadcasting to {len(sub_list)} subscribers for {request_id_str}"
#             )
#             disconnected_subs = []
#             for sub_queue in sub_list:
#                 try:
#                     # Put the update_data (expected to be AnalysisRequestGQL or dict)
#                     await sub_queue.put(update_data)
#                 except Exception as e:
#                     # If putting fails (e.g., queue full, closed?), assume disconnected
#                     logger.warning(
#                         f"[In-Memory PubSub] Failed to put update in subscriber queue for {request_id_str}: {e}. Marking for removal."
#                     )
#                     disconnected_subs.append(sub_queue)

#             # Clean up disconnected subscribers
#             if disconnected_subs:
#                 current_subs = subscribers.get(request_id_str, [])
#                 subscribers[request_id_str] = [
#                     q for q in current_subs if q not in disconnected_subs
#                 ]
#                 logger.debug(
#                     f"[In-Memory PubSub] Cleaned up {len(disconnected_subs)} subscribers for {request_id_str}"
#                 )

#             update_queue.task_done()
#         except asyncio.CancelledError:
#             logger.info("[In-Memory PubSub] Broadcast worker cancelled.")
#             break
#         except Exception as e:
#             logger.error(f"[In-Memory PubSub] Error in broadcast worker: {e}")
#             # Avoid tight loop on persistent errors
#             await asyncio.sleep(1)

# --- Start broadcast worker in background (Only needed for In-Memory) ---
# broadcast_task = asyncio.create_task(broadcast_updates())

# Ensure task is cancelled on shutdown (needs integration with lifespan)
# async def shutdown_broadcast_worker():
#     if broadcast_task:
#         broadcast_task.cancel()
#         try:
#             await broadcast_task
#         except asyncio.CancelledError:
#             logger.info("[In-Memory PubSub] Broadcast worker successfully cancelled.")
