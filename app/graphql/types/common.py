from enum import Enum
import uuid
import datetime

import strawberry
from strawberry.schema_directive import Location
# from strawberry.types import Node # Removed old import
from app.graphql.common import Node, to_global_id # Use local Node interface definition

# Import base UserError if needed for payloads, or define payloads elsewhere
# from .user_error import UserError

# Define a schema directive to hide fields from the GraphQL schema
@strawberry.schema_directive(locations=[Location.FIELD_DEFINITION])
class Skip:
    if_: bool = True


# Corresponds to DB model LinkedAccount
@strawberry.type
class LinkedAccount(Node):
    """Represents an external account linked by the user (e.g., Shopify store)."""
    db_id: uuid.UUID = strawberry.field(directives=[Skip(if_=True)])

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
    data: strawberry.scalars.JSON  # Data formatted for the specific visualization type
    title: str | None = None


@strawberry.type
class AnalysisResult:
    summary: str | None = None
    visualizations: list[Visualization] | None = None
    # rawData: Optional[strawberry.JSON] = None # Include if raw data is needed


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

import base64  # Added for cursors
import binascii  # Added import
import datetime
import enum
import uuid
from typing import Any, Generic, TypeVar  # Added TypeVar, Generic

import strawberry

# Import schemas for Pydantic integration
from app import schemas
from app.schemas.user import User as UserSchema
from app.schemas.user import UserCreate as UserCreateSchema

# Import Enums from models
from app.models.analysis_request import AnalysisRequestStatus
from app.models.proposed_action import ProposedActionStatus

# Register Enums with Strawberry
AnalysisRequestStatusEnum = strawberry.enum(
    AnalysisRequestStatus, name="AnalysisRequestStatus"
)
ProposedActionStatusEnum = strawberry.enum(
    ProposedActionStatus, name="ProposedActionStatus"
)

# --- Pagination Types ---

NodeType = TypeVar("NodeType")


@strawberry.type
class Edge(Generic[NodeType]):
    node: NodeType
    cursor: str


@strawberry.type
class Connection(Generic[NodeType]):
    """Relay-style connection for pagination."""
    edges: list[Edge[NodeType]]
    pageInfo: "PageInfo" = strawberry.field(
        description="Information to aid in pagination."
    )


@strawberry.type
class PageInfo:
    """Information about pagination in a connection."""
    hasNextPage: bool = strawberry.field(
        description="When paginating forwards, indicates if more items exist."
    )
    hasPreviousPage: bool = strawberry.field(
        description="When paginating backwards, indicates if more items exist."
    )
    startCursor: str | None = strawberry.field(
        description="The cursor to continue when paginating backwards.",
        default=None,
    )
    endCursor: str | None = strawberry.field(
        description="The cursor to continue when paginating forwards.",
        default=None,
    )


# --- Base Error/Payload Types ---


@strawberry.interface
class UserError:
    message: str
    field: str | None = None  # Optional field indicating the source of the error


# Placeholder for future types (e.g., AnalysisRequest, ProposedAction, etc.)
# Will be added as we implement corresponding resolvers.


# Example of a type implementing UserError
@strawberry.type
class AuthenticationError(UserError):
    message: str = "Authentication failed."
    field: str | None = None


@strawberry.type
class AuthorizationError(UserError):
    message: str = "Authorization failed."
    field: str | None = None


@strawberry.type
class InputValidationError(UserError):
    message: str
    field: str  # Make field mandatory for input errors


@strawberry.type
class NotFoundError(UserError):
    message: str = "Resource not found."
    field: str | None = None


@strawberry.type
class InternalServerError(UserError):
    message: str = "An internal server error occurred."
    field: str | None = None


# --- Specific Application Errors ---


@strawberry.type
class ShopifyAuthError(UserError):
    message: str = "Failed to authenticate with Shopify. Please check your connection."
    field: str | None = None


@strawberry.type
class ShopifyAPIError(UserError):
    message: str = "An error occurred while communicating with Shopify."
    field: str | None = None


@strawberry.type
class RateLimitError(UserError):
    message: str = "Rate limit exceeded. Please try again later."
    field: str | None = None


@strawberry.type
class ActionExecutionError(UserError):
    message: str = "Failed to execute the requested action."
    field: str | None = None


@strawberry.type
class AnalysisTaskError(UserError):
    message: str = "The analysis task encountered an error."
    field: str | None = None


# Common Payloads incorporating UserError
@strawberry.type
class BasePayload:
    userErrors: list[UserError] = strawberry.field(default_factory=list)


# We will create specific payloads for mutations later, e.g.:
# @strawberry.type
# class RegisterPayload(BasePayload):
#     user: Optional[User] = None # Assuming User type exists
#
# @strawberry.type
# class SubmitAnalysisRequestPayload(BasePayload):
#     analysis_request: Optional[AnalysisRequest] = None # Assuming AnalysisRequest type exists

# --- Object Types ---


# User type based on Pydantic schema
@strawberry.experimental.pydantic.type(model=UserSchema, all_fields=True)
class User:
    pass


# AnalysisRequest Type
@strawberry.type
class AnalysisRequest:
    id: uuid.UUID
    # user_id: uuid.UUID # Excluded as it's implicit via auth
    prompt: str
    status: AnalysisRequestStatus
    result_summary: str | None = None
    result_data: Any | None = (
        None  # Using Any for JSONB, consider more specific type if possible
    )
    # agent_state: Optional[Any] = None # Exclude internal state from GQL?
    error_message: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    # Add relationships if needed, e.g., proposed_actions: List["ProposedAction"]


# ProposedAction Type
@strawberry.type
class ProposedAction:
    id: uuid.UUID
    analysis_request_id: uuid.UUID
    # user_id: uuid.UUID # Excluded as it's implicit via auth
    linked_account_id: uuid.UUID
    action_type: str
    description: str
    parameters: Any | None = None  # Using Any for JSONB
    status: ProposedActionStatus
    execution_logs: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    approved_at: datetime.datetime | None = None
    executed_at: datetime.datetime | None = None


# Define Connection types for lists
@strawberry.type
class AnalysisRequestConnection(Connection[AnalysisRequest]):
    pass


@strawberry.type
class ProposedActionConnection(Connection[ProposedAction]):
    pass


# Auth related payloads inheriting BasePayload
@strawberry.type
class AuthPayload(BasePayload):
    token: str | None = None  # Token might not be present on error
    user: User | None = None  # User might not be present on error


@strawberry.type
class RegisterPayload(BasePayload):
    user: User | None = None


@strawberry.type
class ShopifyOAuthStartPayload(BasePayload):
    authorization_url: str | None = None
    state: str | None = None


# Analysis/Action Mutation Payloads
@strawberry.type
class SubmitAnalysisRequestPayload(BasePayload):
    analysis_request: AnalysisRequest | None = None


@strawberry.type
class ApproveActionPayload(BasePayload):
    proposed_action: ProposedAction | None = None


@strawberry.type
class RejectActionPayload(BasePayload):
    proposed_action: ProposedAction | None = None


# Add other object types (AnalysisRequest, ProposedAction etc.) here later
# @strawberry.type
# class AnalysisRequest(BasePayload): # Example if it had userErrors
#     id: strawberry.ID
#     status: str
#     ...

# --- Input Types ---


# Auth inputs
@strawberry.experimental.pydantic.input(model=UserCreateSchema, all_fields=True)
class UserRegisterInput:
    pass


@strawberry.input
class UserLoginInput:
    email: str
    password: str


@strawberry.input
class StartShopifyOAuthInput:
    shop_domain: str = strawberry.field(
        description="The user's myshopify.com domain (e.g., your-store.myshopify.com)"
    )


# Analysis/Action Inputs (Simple ones defined inline in resolvers for now)
# Example: Define dedicated input types if they become complex

# @strawberry.input
# class SubmitAnalysisRequestInput:
#     prompt: str

# @strawberry.input
# class ApproveActionInput:
#     action_id: strawberry.ID

# @strawberry.input
# class RejectActionInput:
#     action_id: strawberry.ID

# --- Utility Functions ---


def encode_cursor(value: Any) -> str:
    """Encodes a value into a base64 cursor."""
    return base64.b64encode(str(value).encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> str:
    """Decodes a base64 cursor."""
    try:
        return base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):  # Use binascii.Error
        # Correct the instantiation based on user_error.py definition
        raise InputValidationError(message="Invalid cursor format.", field="after")
