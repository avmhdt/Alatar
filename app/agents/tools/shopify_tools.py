import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cached_shopify_data import CachedShopifyData
from app.models.linked_account import LinkedAccount
from app.services.shopify_client import (
    ShopifyAdminAPIClient,
    ShopifyAdminAPIClientError,
)

logger = logging.getLogger(__name__)

# Default cache TTL (Time To Live) - e.g., 1 hour
# DEFAULT_CACHE_TTL_SECONDS = 3600 # Remove this, use settings


def _generate_cache_key(prefix: str, args: dict[str, Any]) -> str:
    """Generates a consistent cache key based on a prefix and arguments."""
    # Remove db and potentially other non-cacheable args if they were passed
    args_to_hash = {
        k: v
        for k, v in args.items()
        if k not in ["db", "user_id", "shop_domain", "linked_account_id"]
    }
    # Sort args for consistency
    serialized_args = json.dumps(args_to_hash, sort_keys=True)
    # Use sha256 for a robust hash
    hash_object = hashlib.sha256(serialized_args.encode())
    return f"{prefix}:{hash_object.hexdigest()}"


# Convert to async and expect AsyncSession
async def _afetch_with_cache(
    db: AsyncSession,
    user_id: uuid.UUID,
    shop_domain: str,
    cache_key_prefix: str,
    api_method_name: str,
    api_method_args: dict[str, Any],
) -> Any:
    """Fetches data using the Shopify client asynchronously, utilizing a cache with AsyncSession.

    Args:
    ----
        db: The AsyncDatabase session.
        user_id: The ID of the user requesting the data.
        shop_domain: The Shopify shop domain.
        cache_key_prefix: A prefix for the cache key (e.g., 'shopify:products').
        api_method_name: The name of the ShopifyAdminAPIClient method to call (e.g., 'aget_products').
        api_method_args: A dictionary of arguments for the API method.

    Returns:
    -------
        The data returned by the Shopify API client method.

    Raises:
    ------
        ShopifyAdminAPIClientError: If the API client encounters an error.
        ValueError: If the linked account is not found.

    """
    # Use await and select for async query
    from sqlalchemy.future import select

    stmt = select(LinkedAccount).filter(
        LinkedAccount.user_id == user_id,
        LinkedAccount.account_type == "shopify",
        LinkedAccount.account_name == shop_domain,
    )
    result = await db.execute(stmt)
    linked_account = result.scalars().first()

    if not linked_account:
        logger.error(
            f"Cache check failed: No Shopify account linked for user {user_id}, shop {shop_domain}"
        )
        raise ValueError(f"Shopify account '{shop_domain}' not found for this user.")

    linked_account_id = linked_account.id
    # Pass the actual api_method_args to generate the key
    cache_key = _generate_cache_key(cache_key_prefix, api_method_args)
    now = datetime.now(UTC)

    # 1. Check cache (Async)
    cache_stmt = (
        select(CachedShopifyData)
        .filter(
            CachedShopifyData.linked_account_id == linked_account_id,
            CachedShopifyData.cache_key == cache_key,
            CachedShopifyData.expires_at > now,
        )
        .order_by(CachedShopifyData.cached_at.desc())  # Keep order_by
    )
    cache_result = await db.execute(cache_stmt)
    cached_entry = cache_result.scalars().first()

    if cached_entry:
        logger.info(
            f"Cache hit for key '{cache_key}' (User: {user_id}, Shop: {shop_domain})"
        )
        return cached_entry.data

    logger.info(
        f"Cache miss for key '{cache_key}' (User: {user_id}, Shop: {shop_domain}). Fetching from API."
    )

    # 2. Initialize client and fetch from API
    client = None  # Initialize client to None
    try:
        # Client init needs careful thought - if it does sync DB access, it blocks.
        # Assuming ShopifyAdminAPIClient is adapted or client init is infrequent.
        # Ideally, pass AsyncSession to client if it needs it for init.
        # For now, pass sync session (SessionLocal()) if client requires it for init,
        # but this is suboptimal in an async function.
        # Let's assume client init doesn't need DB session for simplicity here.
        # client = ShopifyAdminAPIClient(db=..., user_id=user_id, shop_domain=shop_domain)

        # Temporary: Initialize client without DB session, assuming token loading is handled elsewhere or lazy
        # This requires refactoring ShopifyAdminAPIClient
        client = ShopifyAdminAPIClient(
            db=None, user_id=user_id, shop_domain=shop_domain
        )  # HACK: Pass None for DB
        # Manually load token if necessary (should be async)
        # await client._aload_credentials(db) # Example if client needs async loading
        # Ensure token is loaded before proceeding
        if not client._access_token:
            # Need to load credentials asynchronously if not done in init
            # This requires _load_credentials to be async and use AsyncSession
            # await client._aload_credentials(db) # Hypothetical async load
            # For now, let's assume sync load happened somehow or raise error
            raise ShopifyAdminAPIClientError(
                "Client access token not loaded for cache fetch."
            )

        api_method = getattr(client, api_method_name)
        # Ensure the method being called is async
        if not asyncio.iscoroutinefunction(api_method):
            raise TypeError(f"API method {api_method_name} is not async")
        # Call the async method
        result = await api_method(**api_method_args)

    except ShopifyAdminAPIClientError as e:
        logger.error(f"Shopify API error during cache fetch for key '{cache_key}': {e}")
        raise
    except Exception as e:
        logger.exception(
            f"Unexpected error during Shopify API fetch for cache key '{cache_key}': {e}"
        )
        raise ShopifyAdminAPIClientError(f"Unexpected error fetching data: {e}") from e
    finally:
        if client:
            await client.aclose()  # Ensure client is closed

    # 3. Store in cache (Async)
    expires_at = now + timedelta(seconds=settings.SHOPIFY_CACHE_TTL_SECONDS)
    new_cache_entry = CachedShopifyData(
        user_id=user_id,
        linked_account_id=linked_account_id,
        cache_key=cache_key,
        data=result,  # Store the actual result
        expires_at=expires_at,
        # cached_at is handled by server_default
    )
    try:
        db.add(new_cache_entry)
        await db.commit()  # Commit async
        logger.info(
            f"Successfully cached data for key '{cache_key}' (User: {user_id}, Shop: {shop_domain})"
        )
    except Exception as e:
        await db.rollback()  # Rollback async
        logger.exception(f"Failed to cache data for key '{cache_key}': {e}")

    return result


# --- Pydantic Input Schemas for Tools ---


class BaseShopifyToolInput(BaseModel):
    # db: Session = Field(..., exclude=True) # Revert to sync Session
    db: AsyncSession = Field(..., exclude=True)  # Expect AsyncSession
    user_id: uuid.UUID = Field(..., exclude=True)
    shop_domain: str = Field(
        ...,
        description="The user's Shopify shop domain (e.g., 'your-store.myshopify.com').",
    )

    # Allow arbitrary types for AsyncSession
    class Config:
        arbitrary_types_allowed = True


class GetProductsInput(BaseShopifyToolInput):
    first: int = Field(default=10, description="Number of products per page.")
    cursor: str | None = Field(
        default=None,
        description="Cursor for pagination (from previous page's pageInfo.endCursor).",
    )


class GetOrdersInput(BaseShopifyToolInput):
    first: int = Field(default=10, description="Number of orders per page.")
    cursor: str | None = Field(
        default=None,
        description="Cursor for pagination (from previous page's pageInfo.endCursor).",
    )
    query_filter: str | None = Field(
        default=None,
        description="Optional filter query string (e.g., 'processed_at:>=2023-01-01'). Refer to Shopify Order query syntax.",
    )


# --- LangChain Tool Definitions (Async Run) ---


class GetShopifyProductsTool(BaseTool):
    name: str = "get_shopify_products"
    description: str = (
        "Asynchronously fetches a paginated list of products from the user's Shopify store. "
        "Use this to get product details like title, status, inventory levels. "
        "Requires 'shop_domain'. Provides 'first' (page size) and 'cursor' (for next page) arguments."
    )
    args_schema: type[BaseModel] = GetProductsInput

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    # Implement async _arun, expect AsyncSession
    async def _arun(
        self,
        db: AsyncSession,  # Expect AsyncSession
        user_id: uuid.UUID,
        shop_domain: str,
        first: int = 10,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            # Use the async fetch_with_cache helper
            result = await _afetch_with_cache(
                db=db,
                user_id=user_id,
                shop_domain=shop_domain,
                cache_key_prefix="shopify:products",
                api_method_name="aget_products",  # Use the async client method name
                api_method_args={
                    "first": first,
                    "cursor": cursor,
                    "db": db,
                },  # Pass db to client method
            )
            return result
        except (ShopifyAdminAPIClientError, ValueError) as e:
            logger.error(
                f"Error using GetShopifyProductsTool for User {user_id}, Shop {shop_domain}: {e}"
            )
            return f"Error fetching products: {e!s}"
        except Exception as e:
            logger.exception(f"Unexpected error in GetShopifyProductsTool: {e}")
            return f"An unexpected error occurred: {e!s}"


class GetShopifyOrdersTool(BaseTool):
    name: str = "get_shopify_orders"
    description: str = (
        "Asynchronously fetches a paginated list of orders from the user's Shopify store. "
        "Use this to get order details like status, total price, customer info. "
        "Requires 'shop_domain'. Provides 'first' (page size), 'cursor' (for next page), "
        "and 'query_filter' (to filter orders, e.g., by date or status) arguments."
    )
    args_schema: type[BaseModel] = GetOrdersInput

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    # Implement async _arun, expect AsyncSession
    async def _arun(
        self,
        db: AsyncSession,  # Expect AsyncSession
        user_id: uuid.UUID,
        shop_domain: str,
        first: int = 10,
        cursor: str | None = None,
        query_filter: str | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            # Use the async fetch_with_cache helper
            result = await _afetch_with_cache(
                db=db,
                user_id=user_id,
                shop_domain=shop_domain,
                cache_key_prefix="shopify:orders",
                api_method_name="aget_orders",  # Use the async client method name
                api_method_args={
                    "first": first,
                    "cursor": cursor,
                    "query_filter": query_filter,
                    "db": db,
                },  # Pass db
            )
            return result
        except (ShopifyAdminAPIClientError, ValueError) as e:
            logger.error(
                f"Error using GetShopifyOrdersTool for User {user_id}, Shop {shop_domain}: {e}"
            )
            return f"Error fetching orders: {e!s}"
        except Exception as e:
            logger.exception(f"Unexpected error in GetShopifyOrdersTool: {e}")
            return f"An unexpected error occurred: {e!s}"


# Instantiate the tools for potential use elsewhere
get_shopify_products_tool = GetShopifyProductsTool()
get_shopify_orders_tool = GetShopifyOrdersTool()

# List of all available Shopify tools for easy import
shopify_tools = [get_shopify_products_tool, get_shopify_orders_tool]

# Add more tools here for other Shopify operations (customers, inventory, etc.)
# Remember to:
# 1. Add methods to ShopifyAdminAPIClient if needed.
# 2. Create Pydantic input schemas.
# 3. Create BaseTool subclasses, calling _fetch_with_cache.
# 4. Add the new tool instance to the `shopify_tools` list.

# --- TODO: Add Async Tools for Write Operations ---
# e.g., UpdateProductPriceTool, CreateDiscountTool, AdjustInventoryTool
# These would call the respective async methods (e.g., client.aupdate_product_price)
# and likely wouldn't need the `db` session passed directly to _arun if the
# client handles its own session lifecycle appropriately.

# --- TODO: Add Skeletons for Missing Tools (Gap 6) ---


class GetShopifyCustomersTool(BaseTool):
    name: str = "get_shopify_customers"
    description: str = "Asynchronously fetches customer data (name, email, order count, amount spent) from Shopify."
    args_schema: type[BaseModel] = GetProductsInput  # Reuse pagination schema

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    async def _arun(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        shop_domain: str,
        first: int = 10,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            result = await _afetch_with_cache(
                db=db,
                user_id=user_id,
                shop_domain=shop_domain,
                cache_key_prefix="shopify:customers",
                api_method_name="aget_customers",
                api_method_args={"first": first, "cursor": cursor, "db": db},  # Pass db
            )
            return result
        except (ShopifyAdminAPIClientError, ValueError) as e:
            logger.error(f"Error in GetShopifyCustomersTool: {e}")
            return f"Error fetching customers: {e!s}"
        except Exception as e:
            logger.exception(f"Unexpected error in GetShopifyCustomersTool: {e}")
            return f"An unexpected error occurred: {e!s}"


class GetShopifyAnalyticsTool(BaseTool):
    name: str = "get_shopify_analytics"
    description: str = "Asynchronously fetches basic shop analytics/info (name, currency, plan) from Shopify."
    args_schema: type[BaseModel] = (
        BaseShopifyToolInput  # Expects db, user_id, shop_domain
    )

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    async def _arun(
        self, db: AsyncSession, user_id: uuid.UUID, shop_domain: str, **kwargs: Any
    ) -> Any:
        try:
            # Note: Analytics might not be cacheable long-term, TTL is global for now
            result = await _afetch_with_cache(
                db=db,
                user_id=user_id,
                shop_domain=shop_domain,
                cache_key_prefix="shopify:analytics:shop_info",  # Specific prefix
                api_method_name="aget_analytics",
                api_method_args={"db": db},  # Pass db
            )
            return result
        except (ShopifyAdminAPIClientError, ValueError) as e:
            logger.error(f"Error in GetShopifyAnalyticsTool: {e}")
            return f"Error fetching analytics: {e!s}"
        except Exception as e:
            logger.exception(f"Unexpected error in GetShopifyAnalyticsTool: {e}")
            return f"An unexpected error occurred: {e!s}"


class WriteShopifyPriceRuleTool(BaseTool):
    name: str = "write_shopify_price_rule"
    description: str = "Asynchronously creates or updates a Shopify price rule. (TODO: Implement fully)"

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    # args_schema: Type[BaseModel] = ... # Define input schema
    # Expect AsyncSession if client needs it for init/operation
    async def _arun(
        self, db: AsyncSession, user_id: uuid.UUID, shop_domain: str, **kwargs: Any
    ) -> Any:
        client = None
        try:
            client = ShopifyAdminAPIClient(
                db=None, user_id=user_id, shop_domain=shop_domain
            )  # Init without db
            # result = await client.acreate_discount(discount_details=kwargs, db=db) # Pass db here
            # await client._ensure_initialized(db) # Ensure init before call
            await client.aclose()
            return (
                "Error: Write tool write_shopify_price_rule not fully implemented yet."
            )
        except Exception as e:
            if client:
                await client.aclose()
            logger.exception(f"Error in WriteShopifyPriceRuleTool: {e}")
            return f"Error executing write_shopify_price_rule: {e}"


class WriteShopifyDraftOrderTool(BaseTool):
    name: str = "write_shopify_draft_order"
    description: str = "Asynchronously creates or updates a Shopify draft order. (TODO: Implement fully)"

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return super()._run(*args, **kwargs)

    # args_schema: Type[BaseModel] = ... # Define input schema
    async def _arun(
        self, db: AsyncSession, user_id: uuid.UUID, shop_domain: str, **kwargs: Any
    ) -> Any:
        client = None
        try:
            client = ShopifyAdminAPIClient(
                db=None, user_id=user_id, shop_domain=shop_domain
            )  # Init without db
            # result = await client.acreate_draft_order(details=kwargs, db=db) # Pass db here
            # await client._ensure_initialized(db) # Ensure init before call
            await client.aclose()
            return (
                "Error: Write tool write_shopify_draft_order not fully implemented yet."
            )
        except Exception as e:
            if client:
                await client.aclose()
            logger.exception(f"Error in WriteShopifyDraftOrderTool: {e}")
            return f"Error executing write_shopify_draft_order: {e}"


# Add new tool instances here
get_shopify_customers_tool = GetShopifyCustomersTool()
get_shopify_analytics_tool = GetShopifyAnalyticsTool()
write_shopify_price_rule_tool = WriteShopifyPriceRuleTool()
write_shopify_draft_order_tool = WriteShopifyDraftOrderTool()

# Update the list of all tools
all_shopify_tools = [
    get_shopify_products_tool,
    get_shopify_orders_tool,
    get_shopify_customers_tool,
    get_shopify_analytics_tool,
    write_shopify_price_rule_tool,
    write_shopify_draft_order_tool,
]


# Helper function to get all tools
def get_all_shopify_tools():
    return all_shopify_tools
