import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .service import decode_access_token
from app.database import current_user_id_cv, get_db
from app.models.user import User

# ContextVar to hold the user ID for the current request/task scope
# current_user_id_cv: contextvars.ContextVar[Optional[uuid.UUID]] = contextvars.ContextVar(
#     "current_user_id", default=None
# ) # Defined in database.py now


def get_optional_user_id_from_token(request: Request) -> uuid.UUID | None:
    """Extracts User ID from Authorization header if present, returns None otherwise."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None

    user_id_str = decode_access_token(token)  # Returns user_id string or None
    if user_id_str:
        try:
            return uuid.UUID(user_id_str)
        except ValueError:
            return None  # Invalid UUID format in token
    return None


def get_required_user_id(
    user_id: uuid.UUID | None = Depends(get_optional_user_id_from_token),
) -> uuid.UUID:
    """Dependency that requires a valid user ID to be extracted from the token."""
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Set the ContextVar - This is crucial for RLS or logic needing implicit user context
    current_user_id_cv.set(user_id)
    return user_id


# Optional: A dependency to get the full User object if needed, requires DB lookup
def get_current_user_optional(
    user_id: uuid.UUID | None = Depends(get_optional_user_id_from_token),
    db: Session = Depends(get_db),
) -> User | None:
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        current_user_id_cv.set(user.id)  # Also set context var here
    return user


def get_current_user_required(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # ContextVar should already be set by get_current_user_optional
    return user


# Function to get the user_id from ContextVar (useful within services/tasks)
def get_current_user_id_context() -> uuid.UUID | None:
    """Gets the current user ID from the context variable."""
    return current_user_id_cv.get()
