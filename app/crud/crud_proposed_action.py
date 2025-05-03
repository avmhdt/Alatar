import uuid
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, UTC

from app.models.proposed_action import ProposedAction, ProposedActionStatus


def get_proposed_action(db: Session, action_id: uuid.UUID) -> ProposedAction | None:
    """Gets a proposed action by its ID."""
    return db.query(ProposedAction).filter(ProposedAction.id == action_id).first()


async def aget_proposed_action(db: AsyncSession, action_id: uuid.UUID) -> ProposedAction | None:
    """Gets a proposed action by its ID asynchronously."""
    stmt = select(ProposedAction).filter(ProposedAction.id == action_id)
    result = await db.execute(stmt)
    return result.scalars().first()


# Note: Proposed Actions are typically created by agents, so a direct 'create' CRUD
# might not be used by the API layer, but could be useful internally or for testing.

def create_proposed_action(
    db: Session,
    *,
    analysis_request_id: uuid.UUID,
    user_id: uuid.UUID,
    linked_account_id: uuid.UUID,
    action_type: str,
    description: str,
    parameters: dict[str, Any],
) -> ProposedAction:
    """Creates a new proposed action."""
    db_obj = ProposedAction(
        analysis_request_id=analysis_request_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        action_type=action_type,
        description=description,
        parameters=parameters,
        status=ProposedActionStatus.PROPOSED,
    )
    db.add(db_obj)
    # Commit should likely happen in the service/agent layer after creation
    # db.commit()
    # db.refresh(db_obj)
    return db_obj


async def acreate_proposed_action(
    db: AsyncSession,
    *,
    analysis_request_id: uuid.UUID,
    user_id: uuid.UUID,
    linked_account_id: uuid.UUID,
    action_type: str,
    description: str,
    parameters: dict[str, Any],
) -> ProposedAction:
    """Creates a new proposed action asynchronously."""
    db_obj = ProposedAction(
        analysis_request_id=analysis_request_id,
        user_id=user_id,
        linked_account_id=linked_account_id,
        action_type=action_type,
        description=description,
        parameters=parameters,
        status=ProposedActionStatus.PROPOSED,
    )
    db.add(db_obj)
    # Commit should happen in the calling agent/service
    # await db.commit()
    # await db.refresh(db_obj)
    return db_obj


def update_proposed_action_status(
    db: Session, action_id: uuid.UUID, status: ProposedActionStatus, execution_logs: str | None = None
) -> ProposedAction | None:
    """Updates the status of a proposed action."""
    db_obj = get_proposed_action(db, action_id)
    if db_obj:
        db_obj.status = status
        if execution_logs is not None:
            db_obj.execution_logs = execution_logs

        # Update timestamps based on status
        now = datetime.now(UTC)
        if status == ProposedActionStatus.APPROVED and db_obj.approved_at is None:
            db_obj.approved_at = now
        elif status == ProposedActionStatus.EXECUTED and db_obj.executed_at is None:
            db_obj.executed_at = now
        # Add other status timestamp logic if needed

        db.add(db_obj)
        # Commit should happen in the calling resolver/service
        # db.commit()
        # db.refresh(db_obj)
    return db_obj


async def aupdate_proposed_action_status(
    db: AsyncSession, action_id: uuid.UUID, status: ProposedActionStatus, execution_logs: str | None = None
) -> ProposedAction | None:
    """Updates the status of a proposed action asynchronously."""
    db_obj = await aget_proposed_action(db, action_id)
    if db_obj:
        db_obj.status = status
        if execution_logs is not None:
            db_obj.execution_logs = execution_logs

        # Update timestamps based on status
        now = datetime.now(UTC)
        if status == ProposedActionStatus.APPROVED and db_obj.approved_at is None:
            db_obj.approved_at = now
        elif status == ProposedActionStatus.EXECUTED and db_obj.executed_at is None:
            db_obj.executed_at = now

        db.add(db_obj)
        # Commit should happen in the calling agent/service/executor
        # await db.commit()
        # await db.refresh(db_obj)
    return db_obj


def get_multi_proposed_actions_by_user(
    db: Session,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    status: ProposedActionStatus | None = None,
) -> list[ProposedAction]:
    """Gets multiple proposed actions for a user, optionally filtering by status."""
    query = db.query(ProposedAction).filter(ProposedAction.user_id == user_id)
    if status is not None:
        query = query.filter(ProposedAction.status == status)
    return query.order_by(ProposedAction.created_at.desc()).offset(skip).limit(limit).all()


# Add get_multi_by_analysis_request etc. if needed 