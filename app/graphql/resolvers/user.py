import logging
import uuid
import strawberry
from strawberry.types import Info
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Assuming User model and Pydantic schemas exist
from app import schemas
from app.auth.dependencies import (
    get_current_user_from_info,
    get_current_user_id,
    get_current_user_id_from_info,
    get_required_user_id_from_info,
    get_current_user_id_context,
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
    InputValidationError,
)
from app.graphql.types.common import ShopifyStore
from app.graphql.types.user import User as UserGQL
from app.models import User as UserModel

# Assume a Shopify service exists
from app.services.shopify_service import fetch_store_details  # Hypothetical service

from app import crud # Use CRUD

# Import schema for update input type
from app.schemas.user_preferences import UserPreferencesUpdate

logger = logging.getLogger(__name__)


def get_user_service():  # Placeholder for dependency injection or direct service instantiation
    from app.services.user_service import UserService  # Avoid top-level import cycle

    return UserService()


def get_linked_account_service():  # Placeholder
    from app.services.linked_account_service import LinkedAccountService

    return LinkedAccountService()


# --- me Query --- #
async def get_current_user_info(info: Info) -> UserGQL | None:
    """Resolver to fetch the currently authenticated user's information."""
    user_id = get_current_user_id_context()
    if not user_id:
        return None

    db: AsyncSession = info.context.db
    # Use async CRUD function
    user_db = await crud.aget_user(db, user_id=user_id)
    if user_db:
        # Strawberry Pydantic type will handle conversion
        return UserGQL.from_orm(user_db)
    return None


async def update_user_preferences(
    info: Info,
    input: UserPreferencesUpdateInput
) -> UserPreferencesPayload:
    """Resolver to update user preferences."""
    user_id = get_current_user_id_context()
    if not user_id:
        return UserPreferencesPayload(userErrors=[UserError(message="Authentication required.")])

    db: AsyncSession = info.context.db

    try:
        # Use async CRUD function
        updated_prefs_db = await crud.create_or_update_user_preferences_async(
            db, user_id=user_id, obj_in=input.to_pydantic()
        )
        if updated_prefs_db:
            # Convert to GQL type
            updated_prefs_gql = UserPreferences.from_orm(updated_prefs_db)
            return UserPreferencesPayload(preferences=updated_prefs_gql)
        else:
            # Handle case where CRUD might fail (though it should raise exceptions)
            return UserPreferencesPayload(userErrors=[UserError(message="Failed to update preferences.")])

    except Exception as e:
        # Log the exception e
        return UserPreferencesPayload(userErrors=[UserError(message=f"An error occurred: {e}")])
