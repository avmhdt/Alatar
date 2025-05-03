import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from app.agents.constants import AgentTaskStatus # Import enum
from app.models.agent_task import AgentTask


def get_agent_task(db: Session | AsyncSession, task_id: uuid.UUID) -> AgentTask | None:
    """Gets an agent task by its ID (sync or async)."""
    if isinstance(db, AsyncSession):
        # Async version needs await
        raise NotImplementedError("Use aget_agent_task for async sessions")
    return db.query(AgentTask).filter(AgentTask.id == task_id).first()


async def aget_agent_task(db: AsyncSession, task_id: uuid.UUID) -> AgentTask | None:
    """Gets an agent task by its ID asynchronously."""
    stmt = select(AgentTask).filter(AgentTask.id == task_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def create_agent_task(
    db: AsyncSession,
    *,
    analysis_request_id: uuid.UUID,
    user_id: uuid.UUID,
    task_type: str,
    input_data: dict[str, Any] | None = None,
) -> AgentTask:
    """Creates a new agent task asynchronously."""
    db_obj = AgentTask(
        analysis_request_id=analysis_request_id,
        user_id=user_id,
        task_type=task_type,
        input_data=input_data,
        status=AgentTaskStatus.PENDING, # Use Enum member
    )
    db.add(db_obj)
    await db.commit() # Commit async
    await db.refresh(db_obj) # Refresh async
    return db_obj


async def update_agent_task_status(
    db: AsyncSession,
    task_id: uuid.UUID,
    status: AgentTaskStatus,
    output_data: dict[str, Any] | None = None,
    logs: str | None = None,
) -> AgentTask | None:
    """Updates the status and optionally output/logs of an agent task asynchronously."""
    db_obj = await aget_agent_task(db, task_id)
    if db_obj:
        db_obj.status = status # Use Enum member
        if output_data is not None:
            db_obj.output_data = output_data
        if logs is not None:
            # Append or replace logs? Replacing for now.
            db_obj.logs = logs

        if status == AgentTaskStatus.RUNNING and db_obj.started_at is None:
            from datetime import datetime, UTC
            db_obj.started_at = datetime.now(UTC)
        elif status in [AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED, AgentTaskStatus.CANCELLED] and db_obj.completed_at is None:
            from datetime import datetime, UTC
            db_obj.completed_at = datetime.now(UTC)

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
    return db_obj


async def get_agent_tasks_by_ids(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> list[AgentTask]:
    """Gets multiple agent tasks by their IDs asynchronously."""
    if not task_ids:
        return []
    stmt = select(AgentTask).filter(AgentTask.id.in_(task_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# Add get_multi_by_analysis_request etc. if needed 