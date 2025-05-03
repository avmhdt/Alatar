import uuid

from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    """Gets a user by their ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    """Gets a user by their email address (case-insensitive)."""
    return db.query(User).filter(User.email == email.lower()).first()


async def aget_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Gets a user by their ID asynchronously."""
    stmt = select(User).filter(User.id == user_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def aget_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Gets a user by their email address (case-insensitive) asynchronously."""
    stmt = select(User).filter(User.email == email.lower())
    result = await db.execute(stmt)
    return result.scalars().first()


def add_user(db: Session, *, user_obj: User) -> User:
    """Adds a pre-constructed User object to the session without committing.

    Refreshes the object to populate any server-side defaults.
    """
    db.add(user_obj)
    db.flush() # Use flush + refresh instead of commit
    db.refresh(user_obj)
    return user_obj


# Add update/delete functions later if needed 