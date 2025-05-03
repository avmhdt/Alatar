import logging
import uuid

from sqlalchemy.orm import Session
from strawberry.types import Info

# Assuming User model and Pydantic schemas exist
from app import schemas
from app.auth.dependencies import (
    get_current_user_from_info,
    get_current_user_id,
)

# Helper to get user ID from context/token
from app.core.exceptions import NotFoundError
from app.graphql.relay import to_global_id

# Import GraphQL types
from app.graphql.types import (
    UserError,
    UserPreferences,
    UserPreferencesPayload,
    UserPreferencesUpdateInput,
)
from app.graphql.types.common import ShopifyStore
from app.graphql.types.user import User as UserGQL
from app.models import User as UserModel

# Assume a Shopify service exists
from app.services.shopify_service import fetch_store_details  # Hypothetical service

logger = logging.getLogger(__name__)


def get_user_service():  # Placeholder for dependency injection or direct service instantiation
    from app.services.user_service import UserService  # Avoid top-level import cycle

    return UserService()


def get_linked_account_service():  # Placeholder
    from app.services.linked_account_service import LinkedAccountService

    return LinkedAccountService()


async def get_current_user_info(info: Info) -> UserGQL | None:
    """Resolver for the 'me' query."""
    current_user: UserModel | None = await get_current_user_from_info(info)
    if not current_user:
        return None

    # Prepare basic GQL data
    user_gql_data = {
        "db_id": current_user.id,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "is_active": current_user.is_active,
        "linked_accounts": current_user.linked_accounts,
        "preferences": current_user.preferences,
        "shopify_store": None,  # Default to None
    }

    # Attempt to fetch Shopify Store information if a Shopify account is linked
    shopify_account = next(
        (
            acc
            for acc in current_user.linked_accounts
            if acc.provider == "shopify" and acc.is_active
        ),
        None,
    )
    if shopify_account:
        try:
            logger.debug(
                f"Found active Shopify account for user {current_user.id}. Fetching store details for {shopify_account.account_id}"
            )
            # --- Call Shopify API --- #
            # Ensure shopify_account has necessary fields (access_token, account_id which is shop_domain)
            if shopify_account.access_token and shopify_account.account_id:
                shop_info_from_api = await fetch_store_details(
                    access_token=shopify_account.access_token,
                    shop_domain=shopify_account.account_id,
                )
            else:
                logger.warning(
                    f"Shopify linked account {shopify_account.id} is missing access token or shop domain."
                )
                shop_info_from_api = None
            # ----------------------- #

            if shop_info_from_api:
                # Map API result to ShopifyStore GQL type
                # Assuming fetch_store_details returns a dict with keys like:
                # 'name', 'shopDomain', 'currencyCode', 'planDisplayName'
                # The store's actual Shopify GID might be useful if making ShopifyStore a Node later.

                # Use the linked account's global ID as the GQL ShopifyStore ID for consistency?
                # Or define a new node type ShopifyStore? Let's use linked account ID for now.
                store_gql_id = to_global_id("LinkedAccount", shopify_account.id)

                user_gql_data["shopify_store"] = ShopifyStore(
                    id=store_gql_id,  # Use LinkedAccount's global ID
                    domain=shop_info_from_api.get(
                        "shopDomain", shopify_account.account_id
                    ),
                    name=shop_info_from_api.get("name"),
                    currency_code=shop_info_from_api.get("currencyCode"),
                    plan_display_name=shop_info_from_api.get("planDisplayName"),
                )
                logger.info(
                    f"Successfully fetched Shopify store info ({shop_info_from_api.get('name')}) for user {current_user.id}"
                )
            else:
                logger.warning(
                    f"Did not receive store details from Shopify API for user {current_user.id}, shop {shopify_account.account_id}"
                )

        except Exception as e:
            logger.error(
                f"Failed to fetch/map Shopify store info for user {current_user.id}: {e}",
                exc_info=True,
            )
            # Keep shopify_store as None if API call fails

    # Create the GQL User object
    # Strawberry handles ID resolution via @strawberry.field
    return UserGQL(**user_gql_data)


async def update_user_preferences(
    info: Info, input: UserPreferencesUpdateInput
) -> UserPreferencesPayload:
    """Resolver for the 'updatePreferences' mutation."""
    db: Session = info.context["db"]
    user_id: uuid.UUID | None = get_current_user_id(info.context.get("request"))

    if not user_id:
        return UserPreferencesPayload(
            userErrors=[UserError(message="Authentication required.")]
        )

    user_service = get_user_service()
    try:
        updated_prefs_model = await user_service.update_preferences(
            db,
            user_id,
            schemas.PreferencesUpdate(
                preferred_llm=input.preferred_llm,
                notifications_enabled=input.notifications_enabled,
            ),
        )
        # Map result back to GQL type
        updated_prefs_gql = UserPreferences(
            preferred_llm=updated_prefs_model.preferred_llm,
            notifications_enabled=updated_prefs_model.notifications_enabled,
        )
        return UserPreferencesPayload(preferences=updated_prefs_gql)

    except NotFoundError as e:
        return UserPreferencesPayload(userErrors=[UserError(message=str(e))])
    except Exception as e:
        # Log the exception
        logger.error(
            f"Error updating preferences for user {user_id}: {e}", exc_info=True
        )
        return UserPreferencesPayload(
            userErrors=[UserError(message="An unexpected error occurred.")]
        )
