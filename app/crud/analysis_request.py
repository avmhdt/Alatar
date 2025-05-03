from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc  # Import text for direct SQL
from sqlalchemy.orm import Session

from app.crud.base import CRUDBase
from app.models.analysis_request import AnalysisRequest
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


analysis_request = CRUDAnalysisRequest(AnalysisRequest)
