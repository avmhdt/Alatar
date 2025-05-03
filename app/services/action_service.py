"""Service layer for Proposed Action related operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.graphql.types import decode_cursor
from app.models.proposed_action import ProposedAction, ProposedActionStatus

# Import other necessary models if needed
# Import the executor function directly
from app.services.action_executor import _execute_action_logic

logger = logging.getLogger(__name__)

# Placeholder for GQL/Pydantic types if service needs to return specific errors
# from app.graphql.types import InputValidationError, NotFoundError, BasePayload ...


async def create_proposed_action(
    db: Session,
    user_id: uuid.UUID,
    analysis_request_id: uuid.UUID,
    action_type: str,
    description: str,
    parameters: dict[str, Any],
) -> ProposedAction:
    """Creates a new ProposedAction record in the database with status PROPOSED.

    Args:
    ----
        db: The SQLAlchemy Session object.
        user_id: The ID of the user this action belongs to.
        analysis_request_id: The ID of the analysis request that generated this action.
        action_type: A string identifying the type of action (e.g., 'update_product_metafield').
        description: A human-readable description of the proposed action.
        parameters: A dictionary containing parameters needed to execute the action.

    Returns:
    -------
        The created ProposedAction object.

    Raises:
    ------
        ValueError: If the associated AnalysisRequest is not found.
        Exception: For database errors during creation.

    """
    # Optional: Verify analysis_request_id exists and belongs to the user
    # analysis_request = db.query(AnalysisRequest).filter_by(id=analysis_request_id, user_id=user_id).first()
    # if not analysis_request:
    #     raise ValueError(f"AnalysisRequest {analysis_request_id} not found for user {user_id}")

    new_action = ProposedAction(
        user_id=user_id,
        analysis_request_id=analysis_request_id,
        action_type=action_type,
        description=description,
        parameters=parameters,
        status=ProposedActionStatus.PROPOSED,
    )
    db.add(new_action)
    db.commit()
    db.refresh(new_action)
    # Audit Log
    logger.info(
        "Proposed action created",
        extra={
            "audit": True,
            "audit_event": "ACTION_PROPOSED",
            "user_id": str(user_id),
            "action_id": str(new_action.id),
            "analysis_request_id": str(analysis_request_id),
            "action_type": action_type,
            "parameters": parameters,  # Consider summarizing/masking sensitive params
        },
    )
    # print(f"[Service] Created ProposedAction {new_action.id} for request {analysis_request_id}")
    return new_action


async def list_pending_actions(
    db: Session,
    user_id: uuid.UUID,
    limit: int = 10,
    cursor: str | None = None,  # Expects base64 encoded cursor
) -> tuple[list[ProposedAction], bool]:  # Returns (items, has_next_page)
    """List pending proposed actions for a user with cursor-based pagination."""
    # logger.debug(
    #     f"Listing pending ProposedActions for user {user_id} (limit={limit}, cursor={cursor})"
    # )
    order_by_column = ProposedAction.created_at
    order_direction_func = desc
    query = db.query(ProposedAction).filter(
        ProposedAction.user_id == user_id,
        ProposedAction.status == ProposedActionStatus.PROPOSED,
    )
    if cursor:
        try:
            cursor_value_str = decode_cursor(cursor)
            cursor_value_dt = datetime.fromisoformat(cursor_value_str).replace(
                tzinfo=UTC
            )
            query = query.filter(order_by_column < cursor_value_dt)
        except Exception as e:
            logger.warning(f"Failed to decode or apply cursor '{cursor}': {e}")
            return [], False
    query = query.order_by(order_direction_func(order_by_column)).limit(limit + 1)
    results = query.all()
    has_next_page = len(results) > limit
    items = results[:limit]
    # logger.debug(f"Found {len(results)} items. Has next: {has_next_page}. Returning {len(items)}.")
    return items, has_next_page
    # print(
    #     "[Service Placeholder] list_pending_actions service partially implemented (structure only). Returning empty list."
    # )
    # raise NotImplementedError(
    #     "list_pending_actions service pagination logic not fully implemented"
    # )
    # # return [], False


# Define required scopes for specific action types (example)
ACTION_SCOPES = {
    "CREATE_PRICE_RULE": ["write_price_rules"],
    "CREATE_DRAFT_ORDER": ["write_draft_orders"],
    # Add mappings for other action types
}


async def approve_action(
    db: Session, user_id: uuid.UUID, action_id: uuid.UUID
) -> ProposedAction | str:
    """Approve a proposed action, mark as approved, and trigger execution logic."""
    logger.info(f"Attempting to approve action {action_id} for user {user_id}")
    action = (
        db.query(ProposedAction)
        .filter(ProposedAction.id == action_id, ProposedAction.user_id == user_id)
        .with_for_update()
        .first()
    )

    if not action:
        # Audit Log Attempt Failed
        logger.warning(
            "Action approval failed: Not found or not owned",
            extra={
                "audit": True,
                "audit_event": "ACTION_APPROVAL_FAILED",
                "reason": "Not found or not owned",
                "user_id": str(user_id),
                "action_id": str(action_id),
            },
        )
        return f"Action {action_id} not found or not owned by user."

    if action.status != ProposedActionStatus.PROPOSED:
        # Audit Log Attempt Failed
        logger.warning(
            f"Action approval failed: Invalid state ({action.status.value})",
            extra={
                "audit": True,
                "audit_event": "ACTION_APPROVAL_FAILED",
                "reason": f"Invalid state: {action.status.value}",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "action_type": action.action_type,
            },
        )
        return f"Action {action_id} is not in a proposed state (current: {action.status.value})."

    # --- Scope Check Removed - Handled by Executor --- #

    # --- Mark as Approved and Trigger Execution --- #
    execution_error_message = None
    try:
        # Mark as approved
        action.status = ProposedActionStatus.APPROVED
        action.approved_at = datetime.now(UTC)
        action.execution_logs = "Action approved by user."
        db.commit()  # Commit the APPROVED status
        db.refresh(action)
        # Audit Log Approved
        logger.info(
            "Proposed action approved",
            extra={
                "audit": True,
                "audit_event": "ACTION_APPROVED",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "action_type": action.action_type,
            },
        )

        # Call the executor logic (which contains scope checks, client init, execution, status updates)
        # Pass the existing DB session
        logger.info(f"Calling action executor for action {action_id}.")
        _execute_action_logic(db, action_id)
        logger.info(f"Action executor finished for action {action_id}.")

        # Refresh the action object to get the final status set by the executor
        db.refresh(action)

        # Check the final status set by the executor
        if action.status == ProposedActionStatus.FAILED:
            execution_error_message = (
                action.execution_logs or "Execution failed with unknown reason."
            )
            logger.warning(
                f"Action {action_id} failed during execution: {execution_error_message}"
            )
            # Return the error message from the execution logs
            return f"Action approved but failed during execution: {execution_error_message}"
        elif action.status == ProposedActionStatus.EXECUTED:
            logger.info(f"Action {action_id} executed successfully by executor.")
            return action  # Return the successful action
        else:
            # Should not happen if executor logic is correct
            logger.error(
                f"Action {action_id} ended in unexpected state {action.status.value} after execution."
            )
            return (
                f"Action {action_id} ended in unexpected state: {action.status.value}"
            )

    except Exception as e:
        # Catch errors during the approval process or potentially from the executor call if it raises unexpectedly
        db.rollback()  # Rollback any changes from this function level
        logger.exception(f"Unexpected error during approve_action for {action_id}: {e}")
        # Audit Log - Unexpected Error during Approval/Trigger
        logger.error(
            "Unexpected error during action approval/trigger",
            extra={
                "audit": True,
                "audit_event": "ACTION_APPROVAL_ERROR",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "error": str(e),
            },
        )
        # Attempt to mark as failed if possible
        try:
            action = (
                db.query(ProposedAction).filter(ProposedAction.id == action_id).first()
            )  # Re-fetch if needed
            if action and action.status not in [
                ProposedActionStatus.EXECUTED,
                ProposedActionStatus.FAILED,
                ProposedActionStatus.REJECTED,
            ]:
                action.status = ProposedActionStatus.FAILED
                action.execution_logs = f"Failed during approval/trigger phase: {e}"
                db.commit()
        except Exception as db_err:
            logger.error(
                f"Failed to mark action {action_id} as FAILED after top-level error: {db_err}"
            )
        return f"An unexpected error occurred while approving action {action_id}: {e}"


async def reject_action(
    db: Session, user_id: uuid.UUID, action_id: uuid.UUID
) -> ProposedAction | str:  # Return model on success, error message string on failure
    """Reject a proposed action."""
    logger.info(f"Attempting to reject action {action_id} for user {user_id}")
    action = (
        db.query(ProposedAction)
        .filter(ProposedAction.id == action_id, ProposedAction.user_id == user_id)
        .with_for_update()
        .first()
    )  # Lock row

    if not action:
        # Audit Log Attempt Failed
        logger.warning(
            "Action rejection failed: Not found or not owned",
            extra={
                "audit": True,
                "audit_event": "ACTION_REJECTION_FAILED",
                "reason": "Not found or not owned",
                "user_id": str(user_id),
                "action_id": str(action_id),
            },
        )
        return f"Action {action_id} not found or not owned by user."

    if action.status != ProposedActionStatus.PROPOSED:
        # Audit Log Attempt Failed
        logger.warning(
            f"Action rejection failed: Invalid state ({action.status.value})",
            extra={
                "audit": True,
                "audit_event": "ACTION_REJECTION_FAILED",
                "reason": f"Invalid state: {action.status.value}",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "action_type": action.action_type,
            },
        )
        return f"Action {action_id} is not in a proposed state (current: {action.status.value})."

    try:
        action.status = ProposedActionStatus.REJECTED
        action.execution_logs = "Action rejected by user."
        db.commit()
        db.refresh(action)
        # Audit Log Rejected
        logger.info(
            "Proposed action rejected",
            extra={
                "audit": True,
                "audit_event": "ACTION_REJECTED",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "action_type": action.action_type,
            },
        )
        return action
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to reject action {action_id}: {e}")
        # Audit Log - Unexpected Error during Rejection
        logger.error(
            "Unexpected error during action rejection",
            extra={
                "audit": True,
                "audit_event": "ACTION_REJECTION_ERROR",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "error": str(e),
            },
        )
        return f"Failed to reject action {action_id}: {e}"
    # raise NotImplementedError("reject_action service not implemented")
