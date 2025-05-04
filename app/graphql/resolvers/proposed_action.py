import logging
import uuid
from datetime import datetime
from typing import cast

import strawberry
from fastapi import BackgroundTasks  # Import BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from strawberry.types import Info

from app.graphql.types.user_error import *
from app.graphql.types.analysis_request import *
from app.graphql.types.proposed_action import *
from app.graphql.types.common import *
from app.graphql.types.auth import *
from app.graphql.types.shopify import *
from app.graphql.types.user import *
from app.graphql.types.proposed_action import ConnectionCursor  # Import the ConnectionCursor NewType

# Import the executor service
from app.graphql.utils import (
    decode_cursor,
    encode_cursor,
    get_validated_user_id,
)
from app.auth.dependencies import get_current_user_id_context
from app.models.proposed_action import (
    ProposedAction as ProposedActionModel,
)
from app.models.proposed_action import (
    ProposedActionStatus,
)
from app.services.action_executor import (
    execute_approved_action,
)

# Import pagination PageInfo
from app.graphql.types.analysis_request import PageInfo

# Import the async service function
from app.services.action_service import approve_action, reject_action, list_pending_actions

# Import the relay helpers
from app.graphql.common import from_global_id, to_global_id

logger = logging.getLogger(__name__)


def map_action_model_to_gql(action: ProposedActionModel) -> ProposedAction:
    """Maps the SQLAlchemy model to the Strawberry GQL type."""
    return ProposedAction(
        id=strawberry.ID(str(action.id)),
        analysis_request_id=strawberry.ID(str(action.analysis_request_id)),
        user_id=strawberry.ID(str(action.user_id)),
        linked_account_id=strawberry.ID(str(action.linked_account_id)),
        action_type=action.action_type,
        description=action.description,
        parameters=action.parameters,  # Assuming this is already dict/serializable
        status=ProposedActionStatus(action.status),
        execution_logs=action.execution_logs,
        created_at=action.created_at,
        updated_at=action.updated_at,
        approved_at=action.approved_at,
        executed_at=action.executed_at,
    )


async def list_proposed_actions(
    info: Info,
    first: int = 10,
    after: ConnectionCursor | None = None,
) -> ProposedActionConnection:
    """Resolver to list pending proposed actions for the current user."""
    user_id = get_current_user_id_context()
    if not user_id:
        return ProposedActionConnection(page_info=PageInfo(has_next_page=False, has_previous_page=False), edges=[])

    db: AsyncSession = info.context.db

    # Call the async service function (which handles pagination)
    try:
        # Assuming cursor is base64 encoded simple value (like created_at)
        # Service function handles decoding/logic
        items_db, has_next_page = await list_pending_actions(
            db=db,
            user_id=user_id,
            limit=first,
            cursor=after # Pass opaque cursor
        )
    except Exception as e:
        logger.error(f"Error listing proposed actions for user {user_id}: {e}")
        # Return empty connection on error
        return ProposedActionConnection(page_info=PageInfo(has_next_page=False, has_previous_page=False), edges=[])

    edges = []
    for action in items_db:
        # Create cursor based on item (e.g., using created_at)
        # Needs a consistent method, using global ID for now
        cursor_val = to_global_id("ProposedAction", action.id)
        edges.append(
            ProposedActionEdge(
                node=ProposedAction.from_orm(action),
                cursor=cursor_val # Simple cursor example
            )
        )

    return ProposedActionConnection(
        page_info=PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None,
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
        ),
        edges=edges,
    )


async def user_approves_action(
    info: Info, input: UserApproveActionInput
) -> UserApproveActionPayload:
    """Resolver to approve a proposed action."""
    user_id = get_current_user_id_context()
    if not user_id:
        return UserApproveActionPayload(userErrors=[UserError(message="Authentication required.")])

    db: AsyncSession = info.context.db
    try:
        type_name, db_id_str = from_global_id(input.action_id)
        if type_name != "ProposedAction":
             return UserApproveActionPayload(userErrors=[UserError(message="Invalid action ID type.", field="actionId")])
        action_uuid = uuid.UUID(db_id_str)
    except (ValueError, TypeError):
        return UserApproveActionPayload(userErrors=[UserError(message="Invalid action ID format.", field="actionId")])

    # Call the async service function
    result = await approve_action(db=db, user_id=user_id, action_id=action_uuid)

    if isinstance(result, ProposedAction):
        # Approved successfully (or approved but execution failed, status reflects this)
        return UserApproveActionPayload(
            proposed_action=ProposedAction.from_orm(result)
        )
    else:
        # Service returned an error message string
        return UserApproveActionPayload(userErrors=[UserError(message=result)])


async def user_rejects_action(
    info: Info, input: UserRejectActionInput
) -> UserRejectActionPayload:
    """Resolver to reject a proposed action."""
    user_id = get_current_user_id_context()
    if not user_id:
        return UserRejectActionPayload(userErrors=[UserError(message="Authentication required.")])

    db: AsyncSession = info.context.db
    try:
        type_name, db_id_str = from_global_id(input.action_id)
        if type_name != "ProposedAction":
             return UserRejectActionPayload(userErrors=[UserError(message="Invalid action ID type.", field="actionId")])
        action_uuid = uuid.UUID(db_id_str)
    except (ValueError, TypeError):
        return UserRejectActionPayload(userErrors=[UserError(message="Invalid action ID format.", field="actionId")])

    # Call the async service function
    result = await reject_action(db=db, user_id=user_id, action_id=action_uuid)

    if isinstance(result, ProposedAction):
        return UserRejectActionPayload(
            proposed_action=ProposedAction.from_orm(result)
        )
    else:
        # Service returned an error message string
        return UserRejectActionPayload(userErrors=[UserError(message=result)])
