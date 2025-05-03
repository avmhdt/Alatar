from enum import Enum
import uuid
import datetime
from django.utils.translation import gettext_lazy as _

import strawberry
from strawberry.types import Node
from strawberry.types.node import to_global_id

# Import base UserError if needed for payloads, or define payloads elsewhere
# from .user_error import UserError


# Corresponds to DB model LinkedAccount
@strawberry.type
class LinkedAccount(Node):
    """Represents an external account linked by the user (e.g., Shopify store)."""
    db_id: uuid.UUID = strawberry.field(directives=[strawberry.directive.Include(if_=False)])

    @strawberry.field
    def id(self) -> strawberry.ID:
        return to_global_id("LinkedAccount", self.db_id)

    account_type: str
    account_name: str | None = None
    scopes: list[str] = strawberry.field(default_factory=list) # Often better as list
    status: str # Add status field
    created_at: datetime.datetime
    updated_at: datetime.datetime

    # Add resolver for scopes to parse from string if needed
    # @strawberry.field
    # def scopes(self) -> list[str]:
    #     return self.scopes.split(',') if self.scopes else []


# Corresponds to user settings
@strawberry.type
class UserPreferences:
    # Assuming these fields exist on a User or related model/service
    preferred_llm: str | None = strawberry.field(
        description="User's preferred LLM provider via OpenRouter"
    )
    notifications_enabled: bool = strawberry.field(
        description="Whether push/email notifications are enabled"
    )
    # Add other preferences as needed


@strawberry.enum
class VisualizationType(Enum):
    TABLE = "TABLE"
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"
    SCATTER_PLOT = "SCATTER_PLOT"
    PIE_CHART = "PIE_CHART"
    TEXT = "TEXT"


@strawberry.type
class Visualization:
    type: VisualizationType
    data: strawberry.JSON  # Data formatted for the specific visualization type
    title: str | None = None


@strawberry.type
class AnalysisResult:
    summary: str | None = None
    visualizations: list[Visualization] | None = None
    # rawData: Optional[strawberry.JSON] = None # Include if raw data is needed


@strawberry.type
class ShopifyStore:  # New Type
    """Represents information about a connected Shopify store."""

    # This will likely require fetching data via Shopify API
    # based on the user's LinkedAccount
    id: strawberry.ID  # Use global ID if store is a node itself?
    domain: str
    name: str | None = None  # e.g., shop.name
    currency_code: str | None = None  # e.g., shop.currency
    plan_display_name: str | None = None  # e.g., shop.plan_display_name
    # Add other relevant fields from Shopify Shop object
    # https://shopify.dev/docs/api/admin-graphql/latest/objects/Shop


# --- Payloads for Queries/Mutations using these types ---

# @strawberry.type
# class MyPreferencesPayload:
#     preferences: Optional[UserPreferences] = None
#     userErrors: List[UserError] = strawberry.field(default_factory=list)

# @strawberry.type
# class UpdatePreferencesPayload:
#     preferences: Optional[UserPreferences] = None
#     userErrors: List[UserError] = strawberry.field(default_factory=list)

# @strawberry.type
# class MePayload:
#     user: Optional["User"] = None # Forward reference if User defined elsewhere
#     linked_accounts: Optional[List[LinkedAccount]] = None
#     userErrors: List[UserError] = strawberry.field(default_factory=list)

# @strawberry.type
# class CompleteShopifyOAuthPayload:
#     linked_account: Optional[LinkedAccount] = None
#     userErrors: List[UserError] = strawberry.field(default_factory=list)

# Note: Payloads often live with their respective mutations/queries in resolvers or specific type files.
# Defining User type: Assuming it's defined elsewhere or needs definition here
# @strawberry.type
# class User:
#    id: strawberry.ID
#    email: str
#    preferences: Optional[UserPreferences] = None # Link to preferences
#    linkedAccounts: Optional[List[LinkedAccount]] = None # Link to accounts
