import uuid
from pydantic import BaseModel, ConfigDict

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

    model_config = ConfigDict(from_attributes=True) 