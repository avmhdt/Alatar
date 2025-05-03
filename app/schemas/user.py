import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


# --- User Schemas ---
class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: str


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)  # Enable ORM mode

    id: uuid.UUID
    # is_active: bool # Add if implemented in model
    created_at: datetime
    updated_at: datetime

    # linked_accounts: list["LinkedAccount"] = [] # Add relationships later
    # analysis_requests: list["AnalysisRequest"] = [] 