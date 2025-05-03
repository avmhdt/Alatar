import logging
import uuid

import strawberry
from sqlalchemy.orm import Session
from strawberry.types import Info

from app.auth.dependencies import get_current_user_id  # For user context

# Assuming services are available for OAuth flow
from app.auth.service import (
    exchange_shopify_code_for_token,
    store_shopify_credentials,
)

from ..types.auth import CompleteShopifyOAuthInput, CompleteShopifyOAuthPayload

# Import relevant types
from ..types.common import LinkedAccount
from ..types.user_error import UserError

logger = logging.getLogger(__name__)


async def complete_shopify_oauth(
    info: Info, input: CompleteShopifyOAuthInput
) -> CompleteShopifyOAuthPayload:
    """Resolver to complete the Shopify OAuth flow."""
    request = info.context.get("request")
    db: Session = info.context["db"]
    user_id: uuid.UUID | None = get_current_user_id(request)

    if not user_id:
        return CompleteShopifyOAuthPayload(
            userErrors=[UserError(message="Authentication required.")]
        )

    # 1. Verify State (Essential for security)
    session_state = request.session.pop("shopify_oauth_state", None)
    if not input.state or not session_state or input.state != session_state:
        return CompleteShopifyOAuthPayload(
            userErrors=[UserError(message="Invalid OAuth state.")]
        )

    try:
        # 2. Exchange Code for Token
        token_data = exchange_shopify_code_for_token(
            shop_domain=input.shop, code=input.code
        )
        access_token = token_data.get("access_token")
        scopes = token_data.get("scope")
        if not access_token:
            raise ValueError("Failed to retrieve access token from Shopify.")

        # 3. Store Encrypted Credentials
        linked_account_db = store_shopify_credentials(
            db=db,
            user_id=user_id,
            shop_domain=input.shop,
            access_token=access_token,
            scopes=scopes,
        )

        # 4. Map to GraphQL Type
        linked_account_gql = LinkedAccount(
            id=strawberry.ID(str(linked_account_db.id)),
            provider=linked_account_db.account_type,
            account_identifier=linked_account_db.account_name,
            status="active",  # Assuming active after successful link
            scopes=linked_account_db.scopes.split(",")
            if linked_account_db.scopes
            else [],
        )

        return CompleteShopifyOAuthPayload(linked_account=linked_account_gql)

    except Exception as e:
        # Log the exception details
        logger.error(
            f"Shopify OAuth completion failed for user {user_id}, shop {input.shop}: {e}",
            exc_info=True,
        )
        return CompleteShopifyOAuthPayload(
            userErrors=[UserError(message=f"Shopify OAuth failed: {e}")]
        )
