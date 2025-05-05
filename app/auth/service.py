import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode  # Added for building URLs

import jwt  # PyJWT
import requests  # Added for Shopify API calls
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import TEXT, cast, func, select  # Added func, cast, TEXT, select
from sqlalchemy.orm import Session

# Assuming SessionLocal is available for direct use if needed outside requests
# Import CRUD module instead of individual functions
from app import crud
from app.schemas.user import UserCreate
from app.crud.user import get_user_by_shopify_id # Import the new CRUD function

# Updated imports to use core modules
from app.core.config import settings
from app.core.security import (
    get_password_hash as security_get_password_hash,
)
from app.core.security import (
    verify_password as security_verify_password,
)
from app.database import get_db
# REMOVED: LinkedAccount model import no longer needed here

# encrypt_data, # No longer needed here for this purpose
# decrypt_data,
from app.models.user import User
from app.models.linked_account import LinkedAccount # Added import

# Removed old SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, pwd_context
# Removed old verify_password, get_password_hash (using security versions now)

import logging

logger = logging.getLogger(__name__)
# --- JWT Token Handling (using core config/security) ---
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    # Use settings from config
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> str | None:  # Return user_id (subject) or None
    try:
        # Use settings from config
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str | None = payload.get("sub")  # Assuming user ID is stored in 'sub'
        # Consider adding expiration check explicitly if needed, though decode handles it
        if user_id is None:
            # Optionally log this specific error
            return None
        # You might want to add checks here (e.g., token type, audience) depending on your needs
        return user_id
    except jwt.ExpiredSignatureError:
        # Log this?
        return None  # Token expired
    except jwt.InvalidTokenError:
        # Log e?
        return None  # Invalid token for other reasons


# --- Authentication Service Logic (using CRUD) ---


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = crud.user.get_user_by_email(db, email=email) # Use CRUD function from module
    if not user:
        return None
    # Add check for password existence before verifying
    if not user.hashed_password:
        return None # Cannot authenticate with password if none is set
    if not security_verify_password(password, user.hashed_password):
        return None
    return user


# Modify create_user call if needed, or rely on CRUD version directly
# We primarily use the CRUD version now from the router
async def create_user_with_password(db: Session, user_data: UserCreate) -> User:
    """Specific function to create a user with a password (standard registration)."""
    # Check if email exists
    existing_user = await crud.user.get_user_by_email(db, email=user_data.email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Use the updated CRUD function
    return await crud.user.create_user(db=db, obj_in=user_data)


# --- FastAPI Dependency for getting current user (using CRUD) ---
# Define the scheme once, maybe move to router or main app setup?
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token"
)  # Updated prefix


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id_str = decode_access_token(token)
    if user_id_str is None:
        raise credentials_exception
    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception  # Subject is not a valid UUID

    user = crud.user.get_user(db, user_id=user_uuid)  # Use CRUD function from module
    if user is None:
        # This means the user ID in a valid token doesn't exist in the DB anymore
        raise credentials_exception
    return user


# --- Shopify OAuth Logic (using CRUD) ---


def generate_shopify_auth_url(shop_domain: str) -> tuple[str, str]:
    """Generates the Shopify authorization URL and a state parameter for CSRF protection.

    Args:
    ----
        shop_domain: The myshopify.com domain of the shop.

    Returns:
    -------
        A tuple containing (authorization_url, state_parameter).
        The caller is responsible for storing the state parameter (e.g., in session)
        and verifying it during the callback.

    """
    if not settings.SHOPIFY_API_KEY or not settings.SHOPIFY_APP_URL:
        raise ValueError("Shopify API Key and App URL must be configured.")

    state = uuid.uuid4().hex  # Simple CSRF token, enhance if needed (e.g., JWT state)
    scopes = ",".join(settings.SHOPIFY_SCOPES)
    redirect_uri = f"{settings.SHOPIFY_APP_URL.strip('/')}/auth/shopify/callback"  # Ensure consistent URL structure

    query_params = {
        "client_id": settings.SHOPIFY_API_KEY,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "grant_options[]": "per-user",  # Request online access token (per-user)
    }
    auth_url = f"https://{shop_domain}/admin/oauth/authorize?{urlencode(query_params)}"
    return auth_url, state


def exchange_shopify_code_for_token(shop_domain: str, code: str) -> dict:
    """Exchanges the authorization code for a Shopify access token 
       and associated user information.
    
    Returns:
    -------
        A dictionary containing the access token details and associated user info.
        Example: {
            'access_token': '...', 
            'scope': '...', 
            'associated_user': {'id': 123, 'email': '...'}
        }
    """
    if not settings.SHOPIFY_API_KEY or not settings.SHOPIFY_API_SECRET:
        raise ValueError("Shopify API Key and Secret must be configured.")

    token_url = f"https://{shop_domain}/admin/oauth/access_token"
    payload = {
        "client_id": settings.SHOPIFY_API_KEY,
        "client_secret": settings.SHOPIFY_API_SECRET,
        "code": code,
    }

    try:
        response = requests.post(token_url, json=payload)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        token_data = response.json()
        # Check for essential data
        if "access_token" not in token_data or "associated_user" not in token_data:
            error_detail = token_data.get('error', 'Unknown error')
            logger.error(f"Failed to retrieve access token or associated_user from Shopify: {error_detail} - Response: {token_data}")
            raise ValueError(
                f"Failed to retrieve required details from Shopify: {error_detail}"
            )
        # Log extracted user info for debugging
        shopify_user_info = token_data.get("associated_user", {})
        logger.info(f"Received Shopify user info: ID={shopify_user_info.get('id')}, Email={shopify_user_info.get('email')}")
        return token_data  # Contains access_token, scope, associated_user, etc.
    except requests.exceptions.RequestException as e:
        # Log the error details
        logger.error(f"Error exchanging Shopify code: {e}")
        raise  # Re-raise the exception for the caller to handle
    except Exception as e:
        logger.error(f"Unexpected error during Shopify token exchange: {e}")
        raise


async def store_shopify_credentials(
    db: Session, user_id: uuid.UUID, shop_domain: str, access_token: str, scopes: str
) -> LinkedAccount:
    """Encrypts and stores Shopify credentials using pgcrypto via the CRUD layer.

    Handles creating or updating the account and manages the transaction.
    (This function remains largely unchanged as it focuses on the LinkedAccount)
    """
    # Encrypt using pgcrypto function within the query
    # NOTE: This still sends the *key* to the DB with the query, but not the plaintext token.
    # The encryption happens database-side.
    encrypted_token_result = db.execute(
        select(func.pgp_sym_encrypt(access_token, settings.PGCRYPTO_SYM_KEY))
    ).scalar_one()

    # Call the thin CRUD function to save the encrypted data
    db_account = await crud.linked_account.save_shopify_account(
        db=db,
        user_id=user_id,
        shop_domain=shop_domain,
        encrypted_token=encrypted_token_result,
        scopes=scopes,
    )

    try:
        await db.commit()
        await db.refresh(db_account)
        return db_account
    except Exception as e:
        await db.rollback()
        logger.error(f"Error storing Shopify credentials: {e}") 
        raise 


# REMOVED: Redundant get_decrypted_shopify_credentials function.
# The CRUD version (crud.linked_account.get_decrypted_token_for_shopify_account)
# should be used directly where needed.
# def get_decrypted_shopify_credentials(...):
#    ...
