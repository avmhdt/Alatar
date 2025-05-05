from sqlalchemy.orm import Session
import uuid # Added

from app.models.user import User
from app.schemas.user import UserCreate
from app.core.security import get_password_hash, verify_password # Keep verify_password if needed elsewhere

# Added shopify_user_id parameter, made hashed_password optional
async def create_user(db: Session, *, obj_in: UserCreate, shopify_user_id: str | None = None) -> User:
    """Creates a user, hashing the password if provided."""
    create_data = obj_in.model_dump()
    hashed_password = None
    if create_data.get("password"): # Only hash if password is provided
        hashed_password = get_password_hash(create_data["password"])
        del create_data["password"] # Don't store plain password
    
    db_obj = User(
        **create_data, 
        hashed_password=hashed_password, 
        shopify_user_id=shopify_user_id # Add shopify_user_id
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

# Function to get user by shopify_user_id
async def get_user_by_shopify_id(db: Session, *, shopify_user_id: str) -> User | None:
    """Retrieves a user by their Shopify User ID."""    
    return await db.query(User).filter(User.shopify_user_id == shopify_user_id).first()


# ... rest of the CRUD functions (get, get_by_email, update, etc.) ...
# Note: get_user_by_email likely remains unchanged unless emails don't 
# need to be unique across all auth methods.
async def get_user_by_email(db: Session, *, email: str) -> User | None:
    return await db.query(User).filter(User.email == email.lower()).first()

async def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return await db.query(User).filter(User.id == user_id).first()

# ... (add_user, authenticate potentially adjusted or unused for Shopify flow) ...

# This basic add might be replaced by create_user
# async def add_user(db: Session, user_obj: User):
#     db.add(user_obj)
#     # Commit and refresh are typically handled in the service layer after calling this


# Authentication function might need adjustment or be bypassed for Shopify logins
async def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = await get_user_by_email(db=db, email=email)
    if not user:
        return None
    if not user.hashed_password: # User created via external provider (no password)
        return None 
    if not verify_password(password, user.hashed_password):
        return None
    return user 