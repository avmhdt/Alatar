import contextvars
import logging
import os
import uuid
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Get the context variable from auth dependencies
# Need to ensure this module is loaded after auth.dependencies or handle potential circular import
# Alternatively, define the CV here and import it in dependencies.
# Let's define it here for simplicity.
current_user_id_cv: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_user_id", default=None
)

logger = logging.getLogger(__name__)
load_dotenv()

# Prefer DATABASE_URL from environment, fallback for local development if needed
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost:5432/alatar_db"
)

# --- Sync Engine and Session (for FastAPI/GraphQL layer) ---
sync_engine = create_engine(SQLALCHEMY_DATABASE_URL)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

# --- Async Engine and Session (for Workers/Agents) ---
# Ensure database URL is compatible with asyncpg (e.g., postgresql+asyncpg://...)
ASYNC_SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
)
async_engine = create_async_engine(
    ASYNC_SQLALCHEMY_DATABASE_URL
)  # Add pool_pre_ping=True?
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


Base = declarative_base()

# --- REMOVED RLS Session Variable Event Listeners ---
# Sync listeners are not reliable with AsyncSession.
# RLS context will be set explicitly in get_async_db.


# --- Sync Dependency to get DB session (for FastAPI/GraphQL) ---
def get_db():
    db = SyncSessionLocal()
    user_id = current_user_id_cv.get()
    # logger.debug(f"Getting SYNC DB session. User ID from context: {user_id}")
    # Set RLS for sync session if user_id is present (important for GraphQL/API RLS)
    if user_id:
        try:
            db.execute(
                text("SET LOCAL app.current_user_id = :user_id"),
                {"user_id": str(user_id)},
            )
        except Exception as e:
            logger.error(f"Failed to set RLS for sync session (User: {user_id}): {e}")
            # Decide how to handle - rollback? raise?
            db.rollback()
            raise
    try:
        yield db
        db.commit()  # Commit if yield succeeds
    except Exception:
        db.rollback()  # Rollback on any exception during yield
        raise
    finally:
        # Reset RLS for sync session
        if user_id:
            try:
                db.execute(text("RESET app.current_user_id;"))
            except Exception as e:
                logger.warning(
                    f"Failed to reset RLS for sync session (User: {user_id}): {e}"
                )
        # logger.debug("Closing SYNC DB session.")
        db.close()
        current_user_id_cv.set(None)  # Explicitly clear context var


# --- Async Dependency to get DB session (for Workers/Agents) ---
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = AsyncSessionLocal()
    user_id = current_user_id_cv.get()  # Get user_id from context var (set upstream)
    # logger.debug(f"Getting ASYNC DB session. User ID from context: {user_id}")

    rls_set_success = False
    if user_id:
        try:
            # Explicitly set RLS context variable for the transaction
            await session.execute(
                text("SET LOCAL app.current_user_id = :user_id"),
                {"user_id": str(user_id)},
            )
            # logger.debug(f"Set RLS user ID: {user_id} for async session")
            rls_set_success = True
        except Exception as e:
            logger.error(
                f"Failed to set RLS user ID for async session (User: {user_id}): {e}"
            )
            # Important: Rollback and close if RLS setting fails
            await session.rollback()
            await session.close()
            current_user_id_cv.set(None)  # Clear context var
            raise  # Propagate error

    # Only yield if RLS was set successfully (or if no user_id was present)
    if rls_set_success or not user_id:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            logger.error(
                f"Database error in async session (User: {user_id}): {e}", exc_info=True
            )
            await session.rollback()
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in async session (User: {user_id}): {e}",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            # logger.debug(f"Closing ASYNC DB session for user {user_id}.")
            # Explicitly reset RLS context variable before closing
            if rls_set_success:  # Only reset if it was successfully set
                try:
                    await session.execute(text("RESET app.current_user_id;"))
                    # logger.debug(f"Reset RLS user ID: {user_id} for async session")
                except Exception as e:
                    # Log error, but proceed with closing
                    logger.warning(
                        f"Failed to reset RLS user ID for async session (User: {user_id}): {e}"
                    )
            await session.close()
            current_user_id_cv.set(None)  # Explicitly clear context var
