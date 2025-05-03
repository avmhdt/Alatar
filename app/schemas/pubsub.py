import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator

# Note: Enums would ideally be imported from a shared location
# For simplicity here, we'll use strings but validate them.

class AnalysisRequestStatusEnum:
    # Simplified enum values for Pydantic model
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AnalysisRequestUpdateData(BaseModel):
    """Pydantic model for data published to Redis for analysis request updates."""
    id: str # UUID as string
    prompt: str
    status: str # Use string representation of the enum status
    # result_summary: Optional[str] = None # Simplified result structure for pub/sub
    # result_data: Optional[Any] = None # Can be dict, list, etc.
    result: Optional[Any] = None # Combined result field for simplicity
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None # Pydantic handles datetime serialization
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    user_id: str # UUID as string
    proposed_actions: List[Any] = Field(default_factory=list) # Keep as Any for now

    @field_validator('status')
    @classmethod
    def check_status_value(cls, v: str):
        allowed_statuses = {
            AnalysisRequestStatusEnum.PENDING,
            AnalysisRequestStatusEnum.PROCESSING,
            AnalysisRequestStatusEnum.COMPLETED,
            AnalysisRequestStatusEnum.FAILED,
            AnalysisRequestStatusEnum.CANCELLED,
        }
        if v not in allowed_statuses:
            raise ValueError(f"Invalid status value: {v}. Must be one of {allowed_statuses}")
        return v

    class Config:
        from_attributes = True # Allow creating from ORM models (like AnalysisRequestModel)
        # orm_mode = True # Deprecated alias for from_attributes


# Example Usage (in worker):
# from app.models.analysis_request import AnalysisRequest as AnalysisRequestModel
# db_request: AnalysisRequestModel = ... # Fetched from DB
# update_payload = AnalysisRequestUpdateData.model_validate(db_request)
# # Redis publish update_payload.model_dump_json() 