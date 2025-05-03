import json
import logging
from typing import TYPE_CHECKING

from redis import asyncio as aioredis

from app.core.config import settings

# Import the Pydantic model for type hinting
if TYPE_CHECKING:
    from app.schemas.pubsub import AnalysisRequestUpdateData

logger = logging.getLogger(__name__)

redis_pool = None


async def create_redis_pool() -> aioredis.Redis:
    """Creates an aioredis connection pool."""
    global redis_pool
    if redis_pool is None:
        try:
            redis_pool = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await redis_pool.ping()
            logger.info(
                f"Successfully connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
            )
        except aioredis.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            redis_pool = None  # Ensure pool is None if connection fails
            # Depending on application requirements, you might want to raise the exception
            # or handle it differently (e.g., retry logic, disable features).
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during Redis connection: {e}")
            redis_pool = None
            raise
    return redis_pool


async def close_redis_pool() -> None:
    """Closes the aioredis connection pool."""
    global redis_pool
    if redis_pool:
        await redis_pool.close()
        # await redis_pool.wait_closed() # wait_closed is deprecated/removed in aioredis > 2
        redis_pool = None
        logger.info("Redis connection pool closed.")


async def get_redis_connection() -> aioredis.Redis:
    """Provides a Redis connection from the pool. Should be called within startup/lifespan."""
    pool = await create_redis_pool()
    if pool is None:
        raise ConnectionError("Redis pool is not initialized or connection failed.")
    return pool


# --- Pub/Sub Helper Functions ---


def get_analysis_update_channel(request_id: str) -> str:
    """Returns the specific Redis channel name for a given analysis request ID."""
    return f"analysis_request_updates:{request_id}"


async def publish_analysis_update_to_redis(request_id: str, update_data: 'AnalysisRequestUpdateData') -> None:
    """Publishes analysis update data (as Pydantic model) to the relevant Redis channel."""
    redis = await get_redis_connection()
    channel = get_analysis_update_channel(request_id)
    try:
        # Serialize the Pydantic model to JSON using its method
        message = update_data.model_dump_json()
        await redis.publish(channel, message)
        logger.debug(f"Published update to Redis channel {channel}: {message}")
    except aioredis.RedisError as e:
        logger.error(f"Redis error publishing to {channel}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error publishing to {channel}: {e}")
