import datetime
import uuid
from typing import NewType

import strawberry
from strawberry.relay import Connection, Node

# Use NewType for cursor clarity
ConnectionCursor = NewType("ConnectionCursor", str)

# Import related types
# Pydantic Schema (if used for input validation)
# from app import schemas
# Import Node interface and global ID helpers
from app.graphql.relay import to_global_id

from .common import AnalysisResult, AnalysisRequestStatus as AnalysisStatus
from .proposed_action import ProposedAction
from .user_error import UserError


@strawberry.type
class AnalysisRequest(Node):
    """Represents a request for data analysis made by a user."""

    # Keep original db_id for internal use if needed, but expose global ID
    db_id: uuid.UUID = strawberry.field(
        description="Internal database ID",
        directives=[strawberry.directive.Include(if_=False)],
    )  # Hide internal ID

    # Implement Node interface id field
    @strawberry.field
    def id(self) -> strawberry.ID:
        """The globally unique ID for the AnalysisRequest."""
        return to_global_id("AnalysisRequest", self.db_id)

    prompt: str
    status: AnalysisStatus
    result: AnalysisResult | None = strawberry.field(
        description="Structured result of the analysis"
    )
    error_message: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    user_id: strawberry.ID  # ID of the user who owns this request
    # linked_account_id: Optional[strawberry.ID] = None # If needed
    proposed_actions: list[ProposedAction] = strawberry.field(default_factory=list)


@strawberry.input
class SubmitAnalysisRequestInput:
    """Input for submitting a new analysis request."""

    prompt: str = strawberry.field(description="The user's prompt for analysis.")
    linked_account_id: strawberry.ID = strawberry.field(
        description="The Global ID of the LinkedAccount (e.g., Shopify store) to analyze."
    )


# Define UserError if it's not globally available
# Assuming UserError is defined elsewhere (e.g., types/user_error.py)


@strawberry.type
class SubmitAnalysisRequestPayload:
    """Payload returned after submitting an analysis request."""

    analysis_request: AnalysisRequest | None = None
    userErrors: list[UserError] = strawberry.field(default_factory=list)


# --- Pagination Types ---


@strawberry.type
class AnalysisRequestEdge:
    """Represents an edge in the AnalysisRequest connection."""

    node: AnalysisRequest
    cursor: ConnectionCursor


@strawberry.type
class PageInfo:
    hasNextPage: bool
    hasPreviousPage: bool
    startCursor: ConnectionCursor | None
    endCursor: ConnectionCursor | None


@strawberry.type
class AnalysisRequestConnection(Connection[AnalysisRequestEdge]):
    """Relay-style connection for paginating AnalysisRequests."""

    # pageInfo and edges are inherited
