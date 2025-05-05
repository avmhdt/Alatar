import contextvars
import logging
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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

# Async URL (for application runtime)
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/alatar_db" # Default includes asyncpg
)

# Sync URL (for Alembic migrations)
SYNC_DATABASE_URL = os.getenv(
    "SYNC_DATABASE_URL", SQLALCHEMY_DATABASE_URL.replace("+asyncpg", "") # Default: strip +asyncpg if present
)

# --- Sync Engine and Session (for Alembic) ---
sync_engine = create_engine(SYNC_DATABASE_URL)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

# --- Async Engine and Session (for Application) ---
# Ensure async URL has the right prefix
if "+asyncpg" not in SQLALCHEMY_DATABASE_URL:
    # Add warning or attempt to fix?
    logger.warning(f"DATABASE_URL {SQLALCHEMY_DATABASE_URL} might be missing +asyncpg prefix for async engine.")
    # Attempt to fix if it looks like a standard postgres URL
    if SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
        ASYNC_SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
    else:
        ASYNC_SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL # Use as-is if unsure
else:
    ASYNC_SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL

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
# Simplified: Just provides a session, RLS handled by specific context manager below
async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    session: AsyncSession = AsyncSessionLocal()
    # logger.debug("Getting plain ASYNC DB session.")
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database error in async session: {e}", exc_info=True)
        await session.rollback()
        raise
    except Exception as e:
        logger.error(f"Unexpected error in async session: {e}", exc_info=True)
        await session.rollback()
        raise
    finally:
        # logger.debug("Closing plain ASYNC DB session.")
        await session.close()

# --- New Async Context Manager with RLS --- #
@asynccontextmanager
async def get_async_db_session_with_rls(user_id: uuid.UUID) -> AsyncGenerator[AsyncSession, None]:
    """Provides an async DB session with RLS context set for the given user_id."""
    if not isinstance(user_id, uuid.UUID):
        raise TypeError("user_id must be a valid UUID")

    session: AsyncSession = AsyncSessionLocal()
    cv_token = None
    rls_set_success = False
    log_props = {"user_id": str(user_id)}

    try:
        # 1. Set ContextVar
        cv_token = current_user_id_cv.set(user_id)
        # logger.debug(f"RLS Context Manager: Set current_user_id_cv", extra={"props": log_props})

        # 2. Set RLS session variable
        await session.execute(
            text("SET LOCAL app.current_user_id = :user_id"),
            {"user_id": str(user_id)},
        )
        rls_set_success = True
        # logger.debug(f"RLS Context Manager: Set session variable", extra={"props": log_props})

        # 3. Yield session
        yield session

        # 4. Commit if context exits without error
        await session.commit()
        # logger.debug(f"RLS Context Manager: Committed session", extra={"props": log_props})

    except SQLAlchemyError as e:
        logger.error(
            f"RLS Context Manager: Database error", exc_info=True, extra={"props": log_props}
        )
        await session.rollback()
        raise
    except Exception as e:
        logger.error(
            f"RLS Context Manager: Unexpected error", exc_info=True, extra={"props": log_props}
        )
        await session.rollback()
        raise
    finally:
        # 5. Reset RLS Session Variable (if set successfully)
        if rls_set_success:
            try:
                await session.execute(text("RESET app.current_user_id;"))
                # logger.debug(f"RLS Context Manager: Reset session variable", extra={"props": log_props})
            except Exception as reset_err:
                logger.warning(
                    f"RLS Context Manager: Failed to reset RLS variable",
                    exc_info=reset_err,
                    extra={"props": log_props}
                )
        # 6. Close Session
        await session.close()
        # logger.debug(f"RLS Context Manager: Closed session", extra={"props": log_props})
        # 7. Reset ContextVar (if set)
        if cv_token:
            current_user_id_cv.reset(cv_token)
            # logger.debug(f"RLS Context Manager: Reset current_user_id_cv", extra={"props": log_props})
