import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


# --- Base Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None
    # Add other fields stored in token payload if needed
    # user_id: uuid.UUID | None = None


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


# --- User Preferences Schemas ---


class UserPreferencesBase(BaseModel):
    preferred_planner_model: str | None = None
    preferred_aggregator_model: str | None = None
    preferred_tool_model: str | None = None
    preferred_creative_model: str | None = None


class UserPreferencesUpdate(UserPreferencesBase):
    # All fields are optional for update
    pass


class UserPreferences(UserPreferencesBase):
    user_id: uuid.UUID
    # Add effective models for convenience if needed in API response
    # effective_planner_model: str
    # ...

    class Config:
        from_attributes = True


# Add other schemas for other models as they are created
# e.g., LinkedAccount, AnalysisRequest etc.
