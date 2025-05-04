import datetime
import uuid
from typing import Any, Generic, TypeVar, Optional, NewType

import strawberry
from strawberry.relay import Connection

from app.graphql.common import Node, to_global_id, ConnectionCursor
from app.graphql.types.common import Skip  # Import the Skip directive

# Import Enum
from app.graphql.types.user_error import UserError  # Assuming UserError exists
from app.models.proposed_action import (
    ProposedActionStatus as ProposedActionStatusEnum,
)

# Register the imported enum for Strawberry
ProposedActionStatusGQL = strawberry.enum(
    ProposedActionStatusEnum, name="ProposedActionStatusGQL"
)


@strawberry.type
class ProposedAction(Node):
    """Represents an action proposed by the system based on analysis."""

    db_id: uuid.UUID = strawberry.field(
        description="Internal database ID",
        directives=[Skip(if_=True)],
    )

    @strawberry.field
    def id(self) -> strawberry.ID:
        """The globally unique ID for the ProposedAction."""
        return to_global_id("ProposedAction", self.db_id)

    analysis_request_id: strawberry.ID
    user_id: strawberry.ID
    linked_account_id: strawberry.ID
    action_type: str
    description: str
    parameters: strawberry.scalars.JSON | None = None  # Use JSON scalar for dictionary
    status: ProposedActionStatusEnum  # Use original Enum type
    execution_logs: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    approved_at: datetime.datetime | None
    executed_at: datetime.datetime | None
    tool_name: str
    tool_input: strawberry.scalars.JSON
    result: strawberry.scalars.JSON | None = None
    error_message: str | None = None


# --- Input Types ---


@strawberry.input
class UserApproveActionInput:
    """Input for approving a proposed action."""

    action_id: strawberry.ID


@strawberry.input
class UserRejectActionInput:
    """Input for rejecting a proposed action."""

    action_id: strawberry.ID
    reason: str | None = None


# --- Payload Types ---

T = TypeVar("T")


@strawberry.type
class BasePayload(Generic[T]):
    userErrors: list[UserError] = strawberry.field(default_factory=list)
    result: T | None = None


@strawberry.type
class UserApproveActionPayload(BasePayload[ProposedAction]):
    result: ProposedAction | None = strawberry.field(
        description="The approved action.", default=None
    )


@strawberry.type
class UserRejectActionPayload(BasePayload[ProposedAction]):
    result: ProposedAction | None = strawberry.field(
        description="The rejected action.", default=None
    )


# --- Connection Type for Pagination (if needed for listProposedActions) ---
@strawberry.type
class ProposedActionEdge:
    """Represents an edge in the ProposedAction connection."""

    node: ProposedAction
    cursor: ConnectionCursor


@strawberry.type
class ProposedActionConnection(Connection[ProposedActionEdge]):
    """Relay-style connection for paginating ProposedActions."""
