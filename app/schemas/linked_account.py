import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

# Pydantic schema for reading a LinkedAccount
class LinkedAccount(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    account_type: str
    account_name: str | None = None
    scopes: str | None = None
    status: str # Add status field
    created_at: datetime
    updated_at: datetime

# Add Create/Update schemas if needed later 