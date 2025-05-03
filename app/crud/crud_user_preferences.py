import uuid

from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user_preferences import UserPreferences
from app.schemas.user_preferences import UserPreferencesUpdate


def get_user_preferences(db: Session, user_id: uuid.UUID) -> UserPreferences | None:
    """Gets user preferences by user ID."""
    return db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()


async def aget_user_preferences(db: AsyncSession, user_id: uuid.UUID) -> UserPreferences | None:
    """Gets user preferences by user ID asynchronously."""
    stmt = select(UserPreferences).filter(UserPreferences.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().first()


def create_or_update_user_preferences(
    db: Session, *, user_id: uuid.UUID, obj_in: UserPreferencesUpdate
) -> UserPreferences:
    """Creates or updates user preferences."""
    db_obj = get_user_preferences(db, user_id)

    if db_obj:
        # Update existing preferences
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
    else:
        # Create new preferences
        db_obj = UserPreferences(**obj_in.model_dump(), user_id=user_id)
        db.add(db_obj)

    # Commit happens in the calling function (e.g., resolver)
    db.commit()
    db.refresh(db_obj)
    return db_obj


async def acreate_or_update_user_preferences(
    db: AsyncSession, *, user_id: uuid.UUID, obj_in: UserPreferencesUpdate
) -> UserPreferences:
    """Creates or updates user preferences asynchronously."""
    db_obj = await aget_user_preferences(db, user_id)

    if db_obj:
        # Update existing preferences
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
    else:
        # Create new preferences
        # Ensure all fields from obj_in and user_id are passed
        create_data = obj_in.model_dump()
        create_data['user_id'] = user_id
        db_obj = UserPreferences(**create_data)
        db.add(db_obj)

    # Let the caller (resolver) handle commit
    # await db.commit()
    # await db.refresh(db_obj)
    # Need to flush to get potential defaults or ensure object is persisted before returning
    await db.flush()
    await db.refresh(db_obj)
    return db_obj


# Add delete if needed 