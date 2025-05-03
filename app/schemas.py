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


# --- User Schemas REMOVED (Moved to app/schemas/user.py) ---


# --- User Preferences Schemas REMOVED (Moved to app/schemas/user_preferences.py) ---


# Add other base/generic schemas here if needed
# Model-specific schemas should go into app/schemas/ subdirectory
