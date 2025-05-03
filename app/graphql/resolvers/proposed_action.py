import logging
import uuid
from datetime import datetime
from typing import cast

import strawberry
from fastapi import BackgroundTasks  # Import BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.graphql.types import (
    ProposedAction,
    ProposedActionConnection,
    ProposedActionEdge,
    UserApproveActionInput,
    UserApproveActionPayload,
    UserError,
    UserRejectActionInput,
    UserRejectActionPayload,
)

# Import the executor service
from app.graphql.utils import (
    decode_cursor,
    encode_cursor,
    get_validated_user_id,
)
from app.models.proposed_action import (
    ProposedAction as ProposedActionModel,
)
from app.models.proposed_action import (
    ProposedActionStatus,
)
from app.services.action_executor import (
    execute_approved_action,
)

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


# Resolver for listing pending actions
def list_proposed_actions(
    info: strawberry.Info,
    first: int = 10,
    after: strawberry.relay.ConnectionCursor | None = None,
) -> ProposedActionConnection:
    db: Session = next(get_db_session())
    user_id = get_validated_user_id(info)

    logger.info(
        f"Listing proposed actions for user {user_id} (first: {first}, after: {after})"
    )

    query = db.query(ProposedActionModel).filter(
        ProposedActionModel.user_id == user_id,
        ProposedActionModel.status == ProposedActionStatus.PROPOSED,
    )

    # Apply cursor logic (assuming cursor is based on created_at for simplicity)
    if after:
        try:
            # Decode cursor to get the timestamp of the last item in the previous page
            after_timestamp = decode_cursor(
                cast(str, after)
            )  # Assuming cursor is datetime string
            if isinstance(after_timestamp, datetime):
                query = query.filter(ProposedActionModel.created_at > after_timestamp)
            else:
                logger.warning(
                    f"Decoded cursor is not a datetime: {after_timestamp}. Ignoring cursor."
                )
        except Exception as e:
            logger.warning(
                f"Failed to decode or apply cursor '{after}': {e}. Ignoring cursor."
            )

    # Order by creation time (ascending for forward pagination)
    query = query.order_by(ProposedActionModel.created_at.asc())

    # Fetch one more item than requested to determine if there's a next page
    actions = query.limit(first + 1).all()

    has_next_page = len(actions) > first
    items_to_return = actions[:first]

    edges = [
        ProposedActionEdge(
            node=map_action_model_to_gql(action),
            cursor=encode_cursor(action.created_at),  # Encode the sort key (created_at)
        )
        for action in items_to_return
    ]

    return ProposedActionConnection(
        edges=edges,
        pageInfo=strawberry.relay.PageInfo(
            hasNextPage=has_next_page,
            hasPreviousPage=bool(
                after
            ),  # Basic check, might need more logic for accurate backward pagination
            startCursor=edges[0].cursor if edges else None,
            endCursor=edges[-1].cursor if edges else None,
        ),
    )


# Resolver for approving an action
def user_approves_action(
    info: strawberry.Info,
    input: UserApproveActionInput,
    background_tasks: BackgroundTasks,  # Inject BackgroundTasks
) -> UserApproveActionPayload:
    db: Session = next(get_db_session())
    user_id = get_validated_user_id(info)
    payload = UserApproveActionPayload(userErrors=[])

    try:
        action_uuid = uuid.UUID(input.action_id)
        logger.info(f"User {user_id} attempting to approve action {action_uuid}")

        # Use with_for_update() to lock the row during the check and update
        action = (
            db.query(ProposedActionModel)
            .filter(
                ProposedActionModel.id == action_uuid,
                ProposedActionModel.user_id == user_id,
            )
            .with_for_update()
            .first()
        )

        if not action:
            payload.userErrors.append(
                UserError(
                    message=f"Action {input.action_id} not found.", field="actionId"
                )
            )
            return payload

        if action.status != ProposedActionStatus.PROPOSED:
            payload.userErrors.append(
                UserError(
                    message=f"Action {input.action_id} is not in 'proposed' state (current: {action.status.value}).",
                    field="actionId",
                )
            )
            # No need to rollback if we just read
            return payload

        # Mark as approved (initially)
        action.status = ProposedActionStatus.APPROVED
        action.approved_at = datetime.utcnow()  # Use UTC
        db.commit()  # Commit the status change
        logger.info(f"Action {action_uuid} status set to APPROVED by user {user_id}")

        # Add the execution logic to background tasks
        # Pass necessary data (action_id) that is safe to serialize/pass
        # The background task will need its own DB session scope
        try:
            logger.info(f"Adding action {action_uuid} execution to background tasks.")
            # NOTE: Passing the db session directly to background task is problematic.
            # The background task should acquire its own session.
            # We will modify execute_approved_action to handle this.
            background_tasks.add_task(execute_approved_action, action_id=action_uuid)
            logger.info(f"Execution task added for action {action_uuid}")
        except Exception as task_err:
            # Handle errors adding the task itself (rare)
            logger.error(
                f"Error adding execution task for action {action_uuid} to background: {task_err}",
                exc_info=True,
            )
            # Optionally revert status or log critical failure
            # Revert status back to PROPOSED if triggering fails?
            # action.status = ProposedActionStatus.PROPOSED
            # action.approved_at = None
            # db.commit()
            payload.userErrors.append(
                UserError(message="Failed to schedule action execution.")
            )
            # Return immediately as the trigger failed
            # Refresh action state before returning?
            db.refresh(action)
            payload.result = map_action_model_to_gql(action)
            return payload

        # Refresh action state AFTER commit and BEFORE mapping to GQL
        db.refresh(action)
        # Return the action in its 'APPROVED' state (execution happens async)
        payload.result = map_action_model_to_gql(action)

    except ValueError:
        payload.userErrors.append(
            UserError(message="Invalid action ID format.", field="actionId")
        )
        db.rollback()  # Rollback on format error
    except Exception as e:
        db.rollback()
        logger.exception(
            f"Error approving action {input.action_id} for user {user_id}: {e}"
        )
        payload.userErrors.append(
            UserError(message="An unexpected server error occurred during approval.")
        )

    return payload


# Resolver for rejecting an action
def user_rejects_action(
    info: strawberry.Info, input: UserRejectActionInput
) -> UserRejectActionPayload:
    db: Session = next(get_db_session())
    user_id = get_validated_user_id(info)
    payload = UserRejectActionPayload(userErrors=[])

    try:
        action_uuid = uuid.UUID(input.action_id)
        logger.info(f"User {user_id} attempting to reject action {action_uuid}")

        action = (
            db.query(ProposedActionModel)
            .filter(
                ProposedActionModel.id == action_uuid,
                ProposedActionModel.user_id == user_id,
            )
            .first()
        )

        if not action:
            payload.userErrors.append(
                UserError(
                    message=f"Action {input.action_id} not found.", field="actionId"
                )
            )
            return payload

        if action.status != ProposedActionStatus.PROPOSED:
            payload.userErrors.append(
                UserError(
                    message=f"Action {input.action_id} is not in 'proposed' state (current: {action.status.value}).",
                    field="actionId",
                )
            )
            return payload

        action.status = ProposedActionStatus.REJECTED
        db.commit()
        db.refresh(action)
        logger.info(f"Action {action_uuid} status set to REJECTED by user {user_id}")

        payload.result = map_action_model_to_gql(action)

    except ValueError:
        payload.userErrors.append(
            UserError(message="Invalid action ID format.", field="actionId")
        )
    except Exception as e:
        db.rollback()
        logger.exception(
            f"Error rejecting action {input.action_id} for user {user_id}: {e}"
        )
        payload.userErrors.append(
            UserError(message="An unexpected server error occurred during rejection.")
        )

    return payload
