"""Service layer for Proposed Action related operations."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.graphql.types import decode_cursor
from app.models.proposed_action import ProposedAction, ProposedActionStatus

# Import other necessary models if needed
# Import the executor function directly
# from app.services.action_executor import _execute_action_logic

# Assume QueueClient is available (e.g., via dependency injection or global instance)
# Placeholder import - replace with actual access method
from app.services.queue_client import QueueClient, RABBITMQ_URL
from app.agents.constants import QUEUE_ACTION_EXECUTION # Import new queue name

logger = logging.getLogger(__name__)

# Placeholder for GQL/Pydantic types if service needs to return specific errors
# from app.graphql.types import InputValidationError, NotFoundError, BasePayload ...

# --- Queue Client Initialization (Placeholder) ---
# In a real app, manage this through app lifecycle or dependency injection
# This is a simplified example assuming direct instantiation here
# Global instance for simplicity in this example, NOT recommended for production
_queue_client_instance = QueueClient(RABBITMQ_URL)
async def get_queue_client():
    await _queue_client_instance.connect()
    return _queue_client_instance
# Remember to handle closing the client connection on app shutdown


async def create_proposed_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    analysis_request_id: uuid.UUID,
    linked_account_id: uuid.UUID,
    action_type: str,
    description: str,
    parameters: dict[str, Any],
) -> ProposedAction:
    """Creates a new ProposedAction record in the database with status PROPOSED.

    Args:
    ----
        db: The SQLAlchemy AsyncSession object.
        user_id: The ID of the user this action belongs to.
        analysis_request_id: The ID of the analysis request that generated this action.
        linked_account_id: The ID of the linked account this action targets.
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
        linked_account_id=linked_account_id,
        action_type=action_type,
        description=description,
        parameters=parameters,
        status=ProposedActionStatus.PROPOSED,
    )
    db.add(new_action)
    await db.commit()
    await db.refresh(new_action)
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
    db: AsyncSession,
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
    stmt = select(ProposedAction).filter(
        ProposedAction.user_id == user_id,
        ProposedAction.status == ProposedActionStatus.PROPOSED,
    )
    if cursor:
        try:
            cursor_value_str = decode_cursor(cursor)
            cursor_value_dt = datetime.fromisoformat(cursor_value_str).replace(
                tzinfo=UTC
            )
            stmt = stmt.filter(order_by_column < cursor_value_dt)
        except Exception as e:
            logger.warning(f"Failed to decode or apply cursor '{cursor}': {e}")
            return [], False
    stmt = stmt.order_by(order_direction_func(order_by_column)).limit(limit + 1)
    result = await db.execute(stmt)
    results = list(result.scalars().all())
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
    db: AsyncSession,
    user_id: uuid.UUID,
    action_id: uuid.UUID
) -> ProposedAction | str:
    """Approve a proposed action, mark as approved, and enqueue for background execution."""
    logger.info(f"Attempting to approve action {action_id} for user {user_id}")
    stmt = select(ProposedAction).filter(
        ProposedAction.id == action_id,
        ProposedAction.user_id == user_id
    ).with_for_update()
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
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

    try:
        action.status = ProposedActionStatus.APPROVED
        action.approved_at = datetime.now(UTC)
        action.execution_logs = "Action approved by user. Queued for execution."
        db.add(action)
        await db.commit()
        await db.refresh(action)
        logger.info(
            "Proposed action approved and status committed.",
            extra={
                "audit": True,
                "audit_event": "ACTION_APPROVED",
                "user_id": str(user_id),
                "action_id": str(action_id),
                "action_type": action.action_type,
            },
        )

        try:
            queue_client = await get_queue_client()
            message_body = {
                "action_id": str(action.id),
                "user_id": str(action.user_id),
            }
            await queue_client.publish_message(QUEUE_ACTION_EXECUTION, message_body)
            logger.info(
                f"Action {action.id} enqueued for execution.",
                extra={
                    "audit": True,
                    "audit_event": "ACTION_ENQUEUED",
                    "user_id": str(user_id),
                    "action_id": str(action_id),
                    "queue": QUEUE_ACTION_EXECUTION,
                },
            )
        except Exception as queue_err:
            logger.exception(
                f"Failed to enqueue action {action.id} after approval: {queue_err}",
                extra={
                    "audit": True,
                    "audit_event": "ACTION_ENQUEUE_FAILED",
                    "user_id": str(user_id),
                    "action_id": str(action_id),
                }
            )
            await db.rollback()
            action.execution_logs += f"\nCRITICAL: Failed to enqueue for execution: {queue_err}"
            return f"Action {action.id} approved but FAILED TO ENQUEUE. Please retry or contact support."

        return action

    except Exception as e:
        await db.rollback()
        logger.exception(f"Unexpected error during approve_action for {action_id}: {e}")
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
        try:
            refetch_stmt = select(ProposedAction).filter(ProposedAction.id == action_id)
            result = await db.execute(refetch_stmt)
            fail_action = result.scalar_one_or_none()
            if fail_action and fail_action.status == ProposedActionStatus.PROPOSED:
                fail_action.status = ProposedActionStatus.FAILED
                fail_action.execution_logs = f"Failed during approval phase: {e}"
                db.add(fail_action)
                await db.commit()
        except Exception as db_err:
            logger.error(
                f"Failed to mark action {action_id} as FAILED after approval error: {db_err}"
            )

        return f"An unexpected error occurred while approving action {action_id}: {e}"


async def reject_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    action_id: uuid.UUID
) -> ProposedAction | str:
    logger.info(f"Attempting to reject action {action_id} for user {user_id}")
    stmt = select(ProposedAction).filter(
        ProposedAction.id == action_id,
        ProposedAction.user_id == user_id
    ).with_for_update()
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()

    if not action:
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
        db.add(action)
        await db.commit()
        await db.refresh(action)
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
        await db.rollback()
        logger.exception(f"Failed to reject action {action_id}: {e}")
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
