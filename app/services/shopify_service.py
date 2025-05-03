import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# TODO: Implement proper Shopify API session management and client initialization.
# This might involve using the shop domain and access token to create an authenticated session.
# Example using shopify library:
# shopify.Session.setup(api_key=settings.SHOPIFY_API_KEY, secret=settings.SHOPIFY_API_SECRET)
# session = shopify.Session(shop_url, api_version, access_token)
# shopify.ShopifyResource.activate_session(session)


async def fetch_store_details(
    access_token: str, shop_domain: str
) -> dict[str, Any] | None:
    """Fetches basic store details from the Shopify Admin API.

    Args:
    ----
        access_token: The offline access token for the shop.
        shop_domain: The shop's myshopify domain (e.g., your-store.myshopify.com).

    Returns:
    -------
        A dictionary containing store details (e.g., name, currencyCode) or None if fetch fails.

    """
    logger.info(f"Attempting to fetch Shopify store details for {shop_domain}")

    # --- Placeholder Implementation --- #
    # Replace this with actual Shopify Admin API call (GraphQL preferred)
    # You need to handle session activation using the access token and domain.
    # Example GraphQL query:
    # query = """
    # { shop { name myshopifyDomain currencyCode plan { displayName } } }
    # """
    # try:
    #    # Activate session using token and domain
    #    # ... (Session activation logic based on shopify library) ...
    #    # result = shopify.GraphQL().execute(query)
    #    # data = json.loads(result) # Assuming JSON response
    #    # shop_data = data.get('data', {}).get('shop')
    #    # shopify.ShopifyResource.clear_session()
    #    # if shop_data:
    #    #     return {
    #    #         "name": shop_data.get("name"),
    #    #         "shopDomain": shop_data.get("myshopifyDomain"),
    #    #         "currencyCode": shop_data.get("currencyCode"),
    #    #         "planDisplayName": shop_data.get("plan", {}).get("displayName")
    #    #     }
    #    # else:
    #    #     logger.warning(f"Received empty shop data from Shopify API for {shop_domain}")
    #    #     return None
    # except Exception as e:
    #    logger.error(f"Error fetching Shopify store details for {shop_domain}: {e}", exc_info=True)
    #    # shopify.ShopifyResource.clear_session()
    #    return None

    # --- Mock Data --- #
    logger.warning(
        f"Using MOCK Shopify store data for {shop_domain}. Implement actual API call."
    )
    await asyncio.sleep(0.1)  # Simulate async call
    return {
        "name": f"{shop_domain.split('.')[0].replace('-', ' ').title()} Store (Mock)",
        "shopDomain": shop_domain,
        "currencyCode": "USD",
        "planDisplayName": "Mock Plan",
    }
    # ----------------- #


# Add helper for activating Shopify session (adjust based on library usage)
# def activate_shopify_session(shop_domain: str, access_token: str):
#     try:
#         api_version = "unstable" # Or your preferred stable version
#         session = shopify.Session(shop_domain, api_version, access_token)
#         shopify.ShopifyResource.activate_session(session)
#         logger.debug(f"Activated Shopify session for {shop_domain}")
#         return True
#     except Exception as e:
#         logger.error(f"Failed to activate Shopify session for {shop_domain}: {e}")
#         return False
