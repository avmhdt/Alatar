import base64  # Added for cursors
import binascii  # Added import
import datetime
import enum
import uuid
from typing import Any, Generic, TypeVar  # Added TypeVar, Generic

import strawberry

# Import schemas for Pydantic integration
from app import schemas

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
class PageInfo:
    has_next_page: bool
    has_previous_page: bool  # Cursors are opaque, so previous might be hard/unreliable
    start_cursor: str | None = None
    end_cursor: str | None = None


@strawberry.type
class Edge(Generic[NodeType]):
    node: NodeType
    cursor: str


@strawberry.type
class Connection(Generic[NodeType]):
    page_info: PageInfo
    edges: list[Edge[NodeType]]


# --- Base Error/Payload Types ---


@strawberry.interface
class UserError:
    message: str
    field: str | None = None  # Optional field indicating the source of the error


@strawberry.enum
class VisualizationType(enum.Enum):
    """Placeholder for visualization types."""

    TABLE = "TABLE"
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"


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
@strawberry.experimental.pydantic.type(model=schemas.User, all_fields=True)
class User:
    pass


# AnalysisRequest Type
@strawberry.type
class AnalysisRequest:
    id: uuid.UUID
    # user_id: uuid.UUID # Excluded as it's implicit via auth
    prompt: str
    status: AnalysisRequestStatusEnum
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
    status: ProposedActionStatusEnum
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
@strawberry.experimental.pydantic.input(model=schemas.UserCreate)
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
