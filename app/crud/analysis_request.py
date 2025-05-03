from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc, text
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Custom Exception for Not Found
class NotFoundException(Exception):
    pass

from app.crud.base import CRUDBase
from app.models.analysis_request import AnalysisRequest, AnalysisRequestStatus
from app.schemas.analysis_request import AnalysisRequestCreate, AnalysisRequestUpdate


class CRUDAnalysisRequest(
    CRUDBase[AnalysisRequest, AnalysisRequestCreate, AnalysisRequestUpdate]
):
    def create_with_owner(
        self, db: Session, *, obj_in: AnalysisRequestCreate, owner_id: UUID
    ) -> AnalysisRequest:
        obj_in_data = obj_in.dict()
        db_obj = self.model(**obj_in_data, user_id=owner_id)
        db.add(db_obj)
        # No commit/refresh here, handled by caller or context manager
        return db_obj

    def get_multi_by_owner(
        self, db: Session, *, owner_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[AnalysisRequest]:
        return (
            db.query(self.model)
            .filter(AnalysisRequest.user_id == owner_id)
            .order_by(desc(AnalysisRequest.created_at))  # Example ordering
            .offset(skip)
            .limit(limit)
            .all()
        )

    # Placeholder for paginated fetching
    def get_multi_by_owner_paginated(
        self,
        db: Session,
        *,
        owner_id: UUID,
        limit: int = 10,
        cursor_data: tuple[Any, Any] | None = None,  # Expect tuple (primary, secondary)
        primary_sort_column: str = "created_at",
        secondary_sort_column: str = "id",  # Unique tie-breaker
        descending: bool = True,
    ) -> list[AnalysisRequest]:
        """Fetches multiple analysis requests for an owner with cursor-based pagination (with tie-breaking)."""
        query = db.query(self.model).filter(AnalysisRequest.user_id == owner_id)

        # Ensure sort columns are valid attributes
        if not hasattr(self.model, primary_sort_column) or not hasattr(
            self.model, secondary_sort_column
        ):
            raise ValueError(
                f"Invalid sort column(s): {primary_sort_column}, {secondary_sort_column}"
            )

        primary_col = getattr(self.model, primary_sort_column)
        secondary_col = getattr(self.model, secondary_sort_column)

        # Apply cursor filtering using compound condition
        if cursor_data is not None:
            primary_cursor_val, secondary_cursor_val = cursor_data
            # Convert secondary cursor value to UUID if the column is UUID type
            # This assumes the secondary column 'id' is UUID. Adjust if necessary.
            try:
                secondary_cursor_val_typed = UUID(str(secondary_cursor_val))
            except ValueError:
                # Keep as string or handle error if conversion expected but failed
                secondary_cursor_val_typed = secondary_cursor_val

            if descending:
                # (primary < cursor_primary) OR (primary = cursor_primary AND secondary < cursor_secondary)
                query = query.filter(
                    (primary_col < primary_cursor_val)
                    | (
                        (primary_col == primary_cursor_val)
                        & (secondary_col < secondary_cursor_val_typed)
                    )
                )
            else:  # Ascending
                # (primary > cursor_primary) OR (primary = cursor_primary AND secondary > cursor_secondary)
                query = query.filter(
                    (primary_col > primary_cursor_val)
                    | (
                        (primary_col == primary_cursor_val)
                        & (secondary_col > secondary_cursor_val_typed)
                    )
                )

        # Apply ordering (primary first, then secondary for tie-breaking)
        sort_dir_primary = desc if descending else asc
        sort_dir_secondary = (
            desc if descending else asc
        )  # Usually same direction for tie-breaker

        query = query.order_by(
            sort_dir_primary(primary_col), sort_dir_secondary(secondary_col)
        ).limit(limit)

        # Execute query
        results = query.all()
        return results


class CRUDAnalysisRequestAsync(
    CRUDBase[AnalysisRequest, AnalysisRequestCreate, AnalysisRequestUpdate]
):
    # For now, implement async methods directly here, assuming CRUDBase needs refactor

    async def aget(self, db: AsyncSession, id: UUID) -> AnalysisRequest | None:
        """Gets an AnalysisRequest by ID asynchronously, respects RLS."""
        stmt = select(self.model).filter(self.model.id == id)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def acreate_with_owner(
        self, db: AsyncSession, *, obj_in: AnalysisRequestCreate, owner_id: UUID, linked_account_id: UUID | None = None
    ) -> AnalysisRequest:
        """Creates an AnalysisRequest asynchronously, expects commit from caller."""
        # obj_in_data = obj_in.dict() # deprecated
        obj_in_data = obj_in.model_dump()
        db_obj = self.model(
            **obj_in_data,
            user_id=owner_id,
            linked_account_id=linked_account_id,
            status=AnalysisRequestStatus.PENDING # Set initial status
        )
        db.add(db_obj)
        # Let caller handle commit/flush/refresh
        return db_obj

    async def get_multi_by_owner_paginated_async(
        self,
        db: AsyncSession,
        *,
        owner_id: UUID,
        limit: int = 10,
        cursor_data: tuple[Any, Any] | None = None, # Expect tuple (primary, secondary)
        primary_sort_column: str = "created_at",
        secondary_sort_column: str = "id", # Unique tie-breaker
        descending: bool = True,
    ) -> list[AnalysisRequest]:
        """Fetches multiple analysis requests for an owner with cursor-based pagination (async)."""
        query = select(self.model).filter(AnalysisRequest.user_id == owner_id)

        # Ensure sort columns are valid attributes
        if not hasattr(self.model, primary_sort_column) or not hasattr(
            self.model, secondary_sort_column
        ):
            raise ValueError(
                f"Invalid sort column(s): {primary_sort_column}, {secondary_sort_column}"
            )

        primary_col = getattr(self.model, primary_sort_column)
        secondary_col = getattr(self.model, secondary_sort_column)

        if cursor_data is not None:
            primary_cursor_val, secondary_cursor_val = cursor_data
            try:
                secondary_cursor_val_typed = UUID(str(secondary_cursor_val))
            except ValueError:
                secondary_cursor_val_typed = secondary_cursor_val

            if descending:
                query = query.filter(
                    (primary_col < primary_cursor_val)
                    | (
                        (primary_col == primary_cursor_val)
                        & (secondary_col < secondary_cursor_val_typed)
                    )
                )
            else:
                query = query.filter(
                    (primary_col > primary_cursor_val)
                    | (
                        (primary_col == primary_cursor_val)
                        & (secondary_col > secondary_cursor_val_typed)
                    )
                )

        sort_dir_primary = desc if descending else asc
        sort_dir_secondary = desc if descending else asc

        query = query.order_by(
            sort_dir_primary(primary_col), sort_dir_secondary(secondary_col)
        ).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    # --- State Management Methods (Async) ---
    async def get_agent_state(self, db: AsyncSession, analysis_request_id: UUID) -> dict | None:
        request = await self.aget(db, analysis_request_id)
        if request:
            return request.agent_state # Assumes agent_state is JSONB returning dict
        return None

    async def update_agent_state(self, db: AsyncSession, analysis_request_id: UUID, agent_state: dict):
        request = await self.aget(db, analysis_request_id)
        if not request:
            raise NotFoundException(f"AnalysisRequest {analysis_request_id} not found.")
        request.agent_state = agent_state
        db.add(request)
        await db.commit()
        await db.refresh(request)

    async def update_status_and_error(
        self, db: AsyncSession, analysis_request_id: UUID, status: AnalysisRequestStatus, error_message: str | None = None, set_completed_at: bool = False
    ):
        request = await self.aget(db, analysis_request_id)
        if not request:
             raise NotFoundException(f"AnalysisRequest {analysis_request_id} not found.")
        request.status = status
        request.error_message = error_message
        if set_completed_at and not request.completed_at:
            from datetime import datetime, UTC
            request.completed_at = datetime.now(UTC)
        db.add(request)
        await db.commit()
        await db.refresh(request)

# Instantiate async version
analysis_request = CRUDAnalysisRequestAsync(AnalysisRequest)

# Keep sync version if still needed elsewhere (e.g., older parts of app)
# analysis_request_sync = CRUDAnalysisRequest(AnalysisRequest)
