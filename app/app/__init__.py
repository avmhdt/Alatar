from contextlib import asynccontextmanager
import logging

from app.schemas import User as UserSchema, UserCreate, UserPreferencesUpdate as UserUpdate
from app.database import create_db_and_tables, close_db_connections, get_session, init_db
from app.core import settings

# ... existing code ... 