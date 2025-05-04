"""Main application package for Alatar."""

# Database components
from app.database import (
    Base,
    get_db,
    get_async_db,
    get_async_db_session_with_rls,
    current_user_id_cv,
    SyncSessionLocal,
    AsyncSessionLocal,
)

# Logging setup
from app.logging_config import (
    setup_logging,
    JsonFormatter,
    PIIMaskingFilter,
)

# For convenient access to common subpackages
from app import (
    models,
    schemas,
    services,
    crud,
    graphql,
    auth,
    core,
)

__all__ = [
    # Database components
    "Base",
    "get_db",
    "get_async_db",
    "get_async_db_session_with_rls",
    "current_user_id_cv",
    "SyncSessionLocal",
    "AsyncSessionLocal",
    
    # Logging setup
    "setup_logging",
    "JsonFormatter",
    "PIIMaskingFilter",
    
    # Subpackages
    "models",
    "schemas",
    "services",
    "crud",
    "graphql",
    "auth",
    "core",
]
