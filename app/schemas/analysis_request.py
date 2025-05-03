import uuid

from pydantic import BaseModel

# Pydantic schema for creating an AnalysisRequest
class AnalysisRequestCreate(BaseModel):
    prompt: str
    user_id: uuid.UUID
    linked_account_id: uuid.UUID | None = None # Match model's nullability

# Pydantic schema for updating an AnalysisRequest (example, adjust as needed)
class AnalysisRequestUpdate(BaseModel):
    pass # Add pass for empty class body

    # Add any necessary fields for updating the analysis request 