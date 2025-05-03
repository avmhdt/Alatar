from pydantic import BaseModel


# --- Base Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None
    # Add other fields stored in token payload if needed
    # user_id: uuid.UUID | None = None
