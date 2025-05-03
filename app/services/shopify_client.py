import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.models.cached_shopify_data import CachedShopifyData
from app.models.linked_account import LinkedAccount

logger = logging.getLogger(__name__)

# Default cache TTL from settings
# DEFAULT_CACHE_TTL_SECONDS = 3600

# Should ideally match the version used during OAuth scope request or be configurable
# See: https://shopify.dev/docs/api/usage/versioning
SHOPIFY_API_VERSION = "2024-07"  # Or fetch dynamically/use config


class ShopifyAdminAPIClientError(Exception):
    """Custom exception for Shopify API client errors."""

    def __init__(self, message, status_code=None, shopify_errors=None):
        super().__init__(message)
        self.status_code = status_code
        self.shopify_errors = shopify_errors  # List of errors from Shopify response


class ShopifyAdminAPIClient:
    """Client for interacting with the Shopify Admin GraphQL API (Async)."""

    # Expect AsyncSession during initialization
    def __init__(self, db: AsyncSession | None, user_id: uuid.UUID, shop_domain: str):
        self.db = db  # Store the async session (can be None initially)
        self.user_id = user_id
        self.shop_domain = shop_domain
        self._access_token: str | None = None
        self._linked_account_id: uuid.UUID | None = None
        self._initialized = False  # Flag to track if credentials are loaded
        self._api_url = (
            f"https://{self.shop_domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        )
        self._client = httpx.AsyncClient(timeout=30.0)
        # Credentials are NOT loaded synchronously anymore
        # self._load_credentials() # Requires db session

    # Convert credential loading to async
    async def _aload_credentials(self, db: AsyncSession):
        """Loads and decrypts the access token from the database asynchronously."""
        if self._initialized:
            return  # Already loaded

        logger.debug(
            f"Loading Shopify credentials async for user {self.user_id} and shop {self.shop_domain}"
        )
        # Use async query
        stmt = select(LinkedAccount.id, LinkedAccount.encrypted_credentials).filter(
            LinkedAccount.user_id == self.user_id,
            LinkedAccount.account_type == "shopify",
            LinkedAccount.account_name == self.shop_domain,
        )
        result = await db.execute(stmt)
        account_data = result.first()  # Returns a Row or None

        if not account_data:
            logger.error(
                f"No Shopify account linked for user {self.user_id} and shop {self.shop_domain}"
            )
            raise ShopifyAdminAPIClientError(
                f"Shopify account for shop '{self.shop_domain}' not linked."
            )

        self._linked_account_id = account_data.id
        encrypted_credentials = account_data.encrypted_credentials

        try:
            # Decrypt using pgcrypto - needs an execution context
            # Assuming get_decrypted_shopify_credentials is sync, which is problematic here.
            # Let's attempt decryption directly using async execute
            from sqlalchemy import TEXT, cast

            decrypt_stmt = select(
                cast(
                    func.pgp_sym_decrypt(
                        encrypted_credentials, settings.PGCRYPTO_SYM_KEY
                    ),
                    TEXT,
                )
            )
            # Need to execute this within the session
            # Hack: Re-execute within the passed session
            decrypt_result = await db.execute(decrypt_stmt)
            decrypted_token = decrypt_result.scalar_one_or_none()

            # decrypted_token = get_decrypted_shopify_credentials(
            #     db=db, user_id=self.user_id, shop_domain=self.shop_domain
            # ) # This needs to be async or run in executor

            if decrypted_token is None:
                logger.error(
                    f"Failed to decrypt Shopify credentials for user {self.user_id}, shop {self.shop_domain}. Token is null or decryption failed."
                )
                raise ValueError("Decryption failed or token not found.")

            self._access_token = decrypted_token
            self._initialized = True  # Mark as initialized
            logger.info(
                f"Successfully loaded and decrypted Shopify credentials async for user {self.user_id}, shop {self.shop_domain}"
            )
        except Exception as e:
            logger.exception(
                f"Failed during async credential loading/decryption for user {self.user_id}, shop {self.shop_domain}: {e}"
            )
            self._initialized = False  # Ensure flag is false on error
            raise ShopifyAdminAPIClientError(
                f"Failed to load/decrypt credentials for shop '{self.shop_domain}'."
            ) from e

    # Ensure credentials are loaded before making a request
    async def _ensure_initialized(self, db: AsyncSession):
        if not self._initialized:
            if not db:
                raise ShopifyAdminAPIClientError(
                    "Async DB session required but not provided for lazy credential loading."
                )
            await self._aload_credentials(db)
        if not self._access_token:
            # If still no token after loading attempt, raise error
            raise ShopifyAdminAPIClientError(
                "Client initialization failed: access token missing."
            )

    # Make request async
    async def _amake_request(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Makes an async GraphQL request to the Shopify Admin API."""
        # Ensure initialized, passing the session if needed for lazy loading
        # Use self.db if provided during init, otherwise use the passed db
        session_for_init = db or self.db
        if not session_for_init:
            raise ShopifyAdminAPIClientError("DB session required for Shopify request.")
        await self._ensure_initialized(session_for_init)

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self._access_token,
        }
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        logger.debug(f"Making async Shopify GraphQL request to {self._api_url}")
        try:
            response = await self._client.post(
                self._api_url, headers=headers, json=payload
            )
            response.raise_for_status()
            response_data = response.json()

            if "errors" in response_data:
                logger.error(
                    f"Shopify GraphQL API returned errors: {response_data['errors']}"
                )
                raise ShopifyAdminAPIClientError(
                    "Shopify API returned errors.",
                    status_code=response.status_code,
                    shopify_errors=response_data["errors"],
                )

            if "data" not in response_data:
                logger.error(
                    f"Shopify API response missing 'data' field: {response_data}"
                )
                raise ShopifyAdminAPIClientError(
                    "Invalid response from Shopify API (missing data).",
                    status_code=response.status_code,
                )

            logger.debug("Async Shopify GraphQL request successful.")
            return response_data["data"]

        except httpx.HTTPStatusError as e:
            logger.exception(
                f"HTTP error occurred during Shopify request: {e.request.url!r} - {e.response.status_code} {e.response.reason_phrase}"
            )
            raise ShopifyAdminAPIClientError(
                f"Shopify API request failed: {e.response.status_code} {e.response.reason_phrase}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            logger.exception(f"HTTP request to Shopify failed: {e}")
            raise ShopifyAdminAPIClientError(
                f"Failed to communicate with Shopify: {e}"
            ) from e
        except Exception as e:
            logger.exception(
                f"An unexpected error occurred during async Shopify API request: {e}"
            )
            raise ShopifyAdminAPIClientError(f"An unexpected error occurred: {e}")

    # --- Caching Logic (Needs Async DB) ---

    def _generate_cache_key(self, prefix: str, args: dict[str, Any]) -> str:
        """Generates a consistent cache key based on a prefix and arguments."""
        # Arguments relevant for Shopify API call (query + variables)
        args_to_hash = {
            k: v
            for k, v in args.items()
            # Ensure only serializable and relevant args are included
            if isinstance(v, (str, int, float, bool, list, dict, tuple)) or v is None
        }
        # Sort args for consistency
        serialized_args = json.dumps(args_to_hash, sort_keys=True)
        # Use sha256 for a robust hash
        hash_object = hashlib.sha256(serialized_args.encode())
        # Include user_id and shop_domain implicitly via linked_account_id
        if not self._linked_account_id:
            # Defensive check, should be set by _load_credentials
            # Now initialization is lazy, so this might happen. Trigger init?
            logger.warning(
                "linked_account_id not set before cache key generation. Credentials might not be loaded."
            )
            # We cannot easily load credentials here without an async context and session.
            # Rely on the caller (_afetch_with_cache) to ensure init happens.
            # For now, use user_id as fallback part of key (less ideal)
            account_part = f"user:{self.user_id}"
        else:
            account_part = f"lacc:{self._linked_account_id}"
        return f"{prefix}:{account_part}:{hash_object.hexdigest()}"

    async def _afetch_with_cache(
        self,
        db: AsyncSession,  # Expect AsyncSession here
        cache_key_prefix: str,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> Any:
        """Fetches data async via _amake_request, utilizing a cache with AsyncSession."""
        # Ensure client is initialized (loads credentials if needed)
        await self._ensure_initialized(db)

        # Now linked_account_id should be set if initialization succeeded
        if not self._linked_account_id:
            logger.error(
                "Client error: linked_account_id not set after ensuring initialization."
            )
            raise ShopifyAdminAPIClientError(
                "Client failed to initialize properly for caching."
            )

        cache_args = {"query": query, "variables": variables or {}}
        cache_key = self._generate_cache_key(cache_key_prefix, cache_args)
        now = datetime.now(UTC)

        # 1. Check cache (Async)
        stmt = (
            select(CachedShopifyData)
            .filter(
                CachedShopifyData.linked_account_id == self._linked_account_id,
                CachedShopifyData.cache_key == cache_key,
                CachedShopifyData.expires_at > now,
            )
            .order_by(CachedShopifyData.cached_at.desc())
        )
        result = await db.execute(stmt)
        cached_entry = result.scalars().first()

        if cached_entry:
            logger.info(
                f"Cache hit for key '{cache_key_prefix}' (User: {self.user_id}, Shop: {self.shop_domain}, Args Hash: {cache_key.split(':')[-1]})"
            )
            return cached_entry.data

        logger.info(
            f"Cache miss for key '{cache_key_prefix}' (User: {self.user_id}, Shop: {self.shop_domain}, Args Hash: {cache_key.split(':')[-1]}). Fetching from API."
        )

        # 2. Fetch from API (Async, ensure db is passed if needed by _amake_request)
        try:
            # Pass db session to _amake_request for potential lazy init
            api_result = await self._amake_request(
                query=query, variables=variables, db=db
            )
        except ShopifyAdminAPIClientError as e:
            logger.error(
                f"Shopify API error during async cache fetch for key '{cache_key}': {e}"
            )
            raise
        except Exception as e:
            logger.exception(
                f"Unexpected error during async Shopify API fetch for cache key '{cache_key}': {e}"
            )
            raise ShopifyAdminAPIClientError(
                f"Unexpected error fetching data: {e}"
            ) from e

        # 3. Store in cache (Async)
        ttl_seconds = settings.SHOPIFY_CACHE_TTL_SECONDS
        expires_at = now + timedelta(seconds=ttl_seconds)
        new_cache_entry = CachedShopifyData(
            user_id=self.user_id,
            linked_account_id=self._linked_account_id,
            cache_key=cache_key,
            data=api_result,
            expires_at=expires_at,
            cached_at=now,
        )
        try:
            db.add(new_cache_entry)
            await db.commit()  # Commit async
            logger.info(
                f"Successfully cached data for key '{cache_key_prefix}' (User: {self.user_id}, Shop: {self.shop_domain}, Args Hash: {cache_key.split(':')[-1]})"
            )
        except Exception as e:
            await db.rollback()  # Rollback async
            logger.exception(f"Failed to cache Shopify data for key '{cache_key}': {e}")

        return api_result

    # --- Async Read Operations (Ensure they pass db to _afetch_with_cache) ---

    async def aget_products(
        self, db: AsyncSession, first: int = 10, cursor: str | None = None
    ) -> dict[str, Any]:
        """Fetches products asynchronously using cache."""
        logger.info(
            f"Fetching products async for shop {self.shop_domain} (first: {first}, cursor: {cursor})"
        )
        query = """
            query ($first: Int!, $cursor: String) {
                products(first: $first, after: $cursor, sortKey: TITLE) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        cursor
                        node {
                            id
                            title
                            handle
                            status
                            totalInventory
                            createdAt
                            updatedAt
                        }
                    }
                }
            }
        """
        variables = {"first": first, "cursor": cursor}
        return await self._afetch_with_cache(
            db=db, cache_key_prefix="shopify:products", query=query, variables=variables
        )

    async def aget_orders(
        self,
        db: AsyncSession,
        first: int = 10,
        cursor: str | None = None,
        query_filter: str | None = None,
    ) -> dict[str, Any]:
        """Fetches orders asynchronously using cache."""
        logger.info(
            f"Fetching orders async for shop {self.shop_domain} (first: {first}, cursor: {cursor}, filter: {query_filter})"
        )
        query = """
            query ($first: Int!, $cursor: String, $queryFilter: String) {
                orders(first: $first, after: $cursor, sortKey: PROCESSED_AT, reverse: true, query: $queryFilter) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        cursor
                        node {
                            id
                            name
                            processedAt
                            displayFinancialStatus
                            displayFulfillmentStatus
                            totalPriceSet {
                                shopMoney {
                                    amount
                                    currencyCode
                                }
                            }
                            customer {
                                id
                                displayName
                            }
                        }
                    }
                }
            }
        """
        variables = {"first": first, "cursor": cursor, "queryFilter": query_filter}
        return await self._afetch_with_cache(
            db=db, cache_key_prefix="shopify:orders", query=query, variables=variables
        )

    async def aget_customers(
        self, db: AsyncSession, first: int = 10, cursor: str | None = None
    ) -> dict[str, Any]:
        """Fetches customers asynchronously using cache."""
        logger.info(
            f"Fetching customers async for shop {self.shop_domain} (first: {first}, cursor: {cursor})"
        )
        query = """
            query ($first: Int!, $cursor: String) {
                customers(first: $first, after: $cursor, sortKey: UPDATED_AT, reverse: true) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        cursor
                        node {
                            id
                            displayName
                            email
                            phone
                            numberOfOrders
                            amountSpent { amount currencyCode }
                            createdAt
                            updatedAt
                        }
                    }
                }
            }
        """
        variables = {"first": first, "cursor": cursor}
        return await self._afetch_with_cache(
            db=db,
            cache_key_prefix="shopify:customers",
            query=query,
            variables=variables,
        )

    async def aget_analytics(self, db: AsyncSession) -> dict[str, Any]:
        """Fetches analytics data asynchronously (implementation TBD)."""
        logger.warning(
            f"aget_analytics not fully implemented for shop {self.shop_domain}"
        )
        query = """
            query {
                shop {
                    name
                    currencyCode
                    ianaTimezone
                    plan { displayName }
                }
            }
        """
        return await self._afetch_with_cache(
            db=db,
            cache_key_prefix="shopify:analytics:shop_info",
            query=query,
            variables={},
        )

    # --- Async Write Operations (use _amake_request, pass db if needed for init) ---

    async def aupdate_product_price(
        self, product_variant_gid: str, new_price: float, db: AsyncSession
    ) -> dict[str, Any]:
        """Updates product price asynchronously."""
        logger.info(
            f"Updating price async for product variant {product_variant_gid} to {new_price} in shop {self.shop_domain}"
        )
        mutation = """
            mutation ProductVariantUpdate($input: ProductVariantInput!) {
              productVariantUpdate(input: $input) {
                productVariant {
                  id
                  price
                  updatedAt
                }
                userErrors {
                  field
                  message
                }
              }
            }
        """
        variables = {"input": {"id": product_variant_gid, "price": str(new_price)}}
        try:
            # Pass db for potential lazy init
            response_data = await self._amake_request(
                query=mutation, variables=variables, db=db
            )
            user_errors = response_data.get("productVariantUpdate", {}).get(
                "userErrors"
            )
            if user_errors:
                logger.error(
                    f"Shopify user errors during async productVariantUpdate: {user_errors}"
                )
                error_message = ", ".join(
                    [f"{err['field']}: {err['message']}" for err in user_errors]
                )
                raise ShopifyAdminAPIClientError(
                    f"Failed to update product variant: {error_message}",
                    shopify_errors=user_errors,
                )

            logger.info(
                f"Successfully updated price async for variant {product_variant_gid}"
            )
            return response_data.get("productVariantUpdate", {}).get(
                "productVariant", {}
            )
        except ShopifyAdminAPIClientError as e:
            raise e
        except Exception as e:
            logger.exception(
                f"Unexpected error during async update_product_price for {product_variant_gid}: {e}"
            )
            raise ShopifyAdminAPIClientError(
                f"An unexpected error occurred while updating product price: {e}"
            )

    async def acreate_discount(
        self, discount_details: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        """Creates discount asynchronously."""
        logger.info(
            f"Creating discount async with details {discount_details} in shop {self.shop_domain}"
        )
        mutation = """
            mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
              discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                  id
                  codeDiscount {
                    ... on DiscountCodeBasic {
                      title
                      codeCount
                      startsAt
                      endsAt
                      usageLimit
                      appliesOncePerCustomer
                      customerGets {
                        value {
                           ... on DiscountPercentage { percentage }
                           ... on DiscountAmount { amount { amount currencyCode } }
                        }
                      }
                    }
                  }
                }
                userErrors {
                  field
                  message
                  code
                }
              }
            }
        """
        variables = {"basicCodeDiscount": discount_details}
        try:
            # Pass db for potential lazy init
            response_data = await self._amake_request(
                query=mutation, variables=variables, db=db
            )
            user_errors = response_data.get("discountCodeBasicCreate", {}).get(
                "userErrors"
            )
            if user_errors:
                logger.error(
                    f"Shopify user errors during async discountCodeBasicCreate: {user_errors}"
                )
                error_message = ", ".join(
                    [
                        f"{err.get('field', 'general')}: {err['message']}"
                        for err in user_errors
                    ]
                )
                raise ShopifyAdminAPIClientError(
                    f"Failed to create discount: {error_message}",
                    shopify_errors=user_errors,
                )

            logger.info(
                f"Successfully created discount code async {discount_details.get('code')}"
            )
            return response_data.get("discountCodeBasicCreate", {}).get(
                "codeDiscountNode", {}
            )
        except ShopifyAdminAPIClientError as e:
            raise e
        except Exception as e:
            logger.exception(f"Unexpected error during async create_discount: {e}")
            raise ShopifyAdminAPIClientError(
                f"An unexpected error occurred while creating discount: {e}"
            )

    async def aadjust_inventory(
        self, inventory_item_gid: str, location_gid: str, delta: int, db: AsyncSession
    ) -> dict[str, Any]:
        """Adjusts inventory asynchronously."""
        logger.info(
            f"Adjusting inventory async for item {inventory_item_gid} at location {location_gid} by {delta} in shop {self.shop_domain}"
        )
        mutation = """
            mutation inventoryAdjustQuantities($input: InventoryAdjustQuantitiesInput!) {
              inventoryAdjustQuantities(input: $input) {
                inventoryAdjustmentGroup {
                  id
                  reason
                  createdAt
                  changes {
                    name
                    delta
                    quantityAfterChange
                  }
                }
                userErrors {
                  field
                  message
                  code
                }
              }
            }
        """
        variables = {
            "input": {
                "reason": "correction",
                "name": "available",
                "changes": [
                    {
                        "delta": delta,
                        "inventoryItemId": inventory_item_gid,
                        "locationId": location_gid,
                    }
                ],
            }
        }
        try:
            # Pass db for potential lazy init
            response_data = await self._amake_request(
                query=mutation, variables=variables, db=db
            )
            user_errors = response_data.get("inventoryAdjustQuantities", {}).get(
                "userErrors"
            )
            if user_errors:
                logger.error(
                    f"Shopify user errors during async inventoryAdjustQuantities: {user_errors}"
                )
                error_message = ", ".join(
                    [
                        f"{err.get('field', 'general')}: {err['message']}"
                        for err in user_errors
                    ]
                )
                raise ShopifyAdminAPIClientError(
                    f"Failed to adjust inventory: {error_message}",
                    shopify_errors=user_errors,
                )

            logger.info(
                f"Successfully adjusted inventory async for item {inventory_item_gid} at {location_gid} by {delta}"
            )
            return response_data.get("inventoryAdjustQuantities", {}).get(
                "inventoryAdjustmentGroup", {}
            )
        except ShopifyAdminAPIClientError as e:
            raise e
        except Exception as e:
            logger.exception(
                f"Unexpected error during async adjust_inventory for {inventory_item_gid}: {e}"
            )
            raise ShopifyAdminAPIClientError(
                f"An unexpected error occurred while adjusting inventory: {e}"
            )

    # Need an explicit close method for the httpx client
    async def aclose(self):
        await self._client.aclose()

    # --- Add other async methods as needed ---
