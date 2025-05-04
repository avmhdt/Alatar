import uuid
from datetime import datetime
from typing import List, Optional

import strawberry
from strawberry.schema_directive import Location

# Import Node interface and global ID helpers
from app.graphql.common import Node, to_global_id

# Import base types and UserError
from .common import LinkedAccount, UserPreferences, Skip
from .user_error import UserError
from .shopify import ShopifyStore


# --- Input Types ---
@strawberry.input
class UserPreferencesUpdateInput:
    preferred_llm: str | None = strawberry.field(
        default=strawberry.UNSET, description="Update preferred LLM provider (optional)"
    )
    notifications_enabled: bool | None = strawberry.field(
        default=strawberry.UNSET,
        description="Update notification preference (optional)",
    )
    # Add other updatable preferences here


# --- Object Types ---
@strawberry.type
class User(Node):
    """Represents a user in the system."""

    # Keep original db_id for internal use if needed, but expose global ID
    db_id: uuid.UUID = strawberry.field(
        description="Internal database ID",
        directives=[Skip(if_=True)],
    )  # Hide internal ID

    # Implement Node interface id field
    @strawberry.field
    def id(self) -> strawberry.ID:
        """The globally unique ID for the User."""
        return to_global_id("User", self.db_id)

    email: str
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    # Ensure these related types are correctly defined elsewhere
    linked_accounts: list[LinkedAccount] = strawberry.field(default_factory=list)
    preferences: UserPreferences | None = None

    # Add field for ShopifyStore (defined later)
    shopify_store: ShopifyStore | None = None  # Use the imported type


# --- Payloads ---
@strawberry.type
class UserPreferencesPayload:
    """Payload returned after updating user preferences."""

    user: User | None = None
    userErrors: list["UserError"] = strawberry.field(
        default_factory=list
    )  # Forward reference if UserError is in another file


# Payload for the 'me' query (optional, can return User directly)
# @strawberry.type
# class MePayload:
#     user: Optional[User] = None
#     userErrors: List[UserError] = strawberry.field(default_factory=list)
