import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode  # Added for building URLs

import jwt  # PyJWT
import requests  # Added for Shopify API calls
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import TEXT, cast, func  # Added func, cast, TEXT
from sqlalchemy.orm import Session

# Assuming SessionLocal is available for direct use if needed outside requests
from app import schemas

# Updated imports to use core modules
from app.core.config import settings
from app.core.security import (
    get_password_hash as security_get_password_hash,
)
from app.core.security import (
    verify_password as security_verify_password,
)
from app.database import (
    get_db,
)
from app.models.linked_account import LinkedAccount  # Added model

# encrypt_data, # No longer needed here for this purpose
# decrypt_data,
from app.models.user import User

# Removed old SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, pwd_context
# Removed old verify_password, get_password_hash (using security versions now)


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


# --- Authentication Service Logic (using core security) ---


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)  # Use helper
    if not user:
        return None
    # Use imported security function
    if not security_verify_password(password, user.hashed_password):
        return None
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, user_data: schemas.UserCreate) -> User:
    # Use imported security function
    hashed_password = security_get_password_hash(user_data.password)
    # Ensure email is stored lowercase for case-insensitive lookup
    db_user = User(email=user_data.email.lower(), hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# --- FastAPI Dependency for getting current user (using updated JWT decode) ---
# Define the scheme once, maybe move to router or main app setup?
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/token"
)  # Adjust tokenUrl if using GraphQL path e.g., "/graphql/token"


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_exception
    try:
        # Validate user_id is a UUID? If 'sub' is always UUID string
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise credentials_exception  # Subject is not a valid UUID

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        # This means the user ID in a valid token doesn't exist in the DB anymore
        raise credentials_exception
    return user


# --- Shopify OAuth Logic ---


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
    """Exchanges the authorization code for a Shopify access token.

    Args:
    ----
        shop_domain: The myshopify.com domain of the shop.
        code: The authorization code received from Shopify.

    Returns:
    -------
        A dictionary containing the access token details (e.g., {'access_token': '...', 'scope': '...'}).

    Raises:
    ------
        ValueError: If configuration is missing or Shopify API returns an error.
        requests.exceptions.RequestException: If the HTTP request fails.

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
        if "access_token" not in token_data:
            # Shopify might return errors differently, check response content
            raise ValueError(
                f"Failed to retrieve access token: {token_data.get('error', 'Unknown error')}"
            )
        return token_data  # Contains access_token, scope, possibly expires_in, associated_user_scope, associated_user
    except requests.exceptions.RequestException as e:
        # Log the error details
        print(f"Error exchanging Shopify code: {e}")
        raise  # Re-raise the exception for the caller to handle


def store_shopify_credentials(
    db: Session, user_id: uuid.UUID, shop_domain: str, access_token: str, scopes: str
) -> LinkedAccount:
    """Stores pgcrypto-encrypted Shopify credentials in the LinkedAccounts table.
    Updates if an account for this user/shop already exists.

    Args:
    ----
        db: SQLAlchemy Session.
        user_id: UUID of the user.
        shop_domain: The myshopify.com domain.
        access_token: The Shopify access token (plaintext).
        scopes: Comma-separated string of granted scopes.

    Returns:
    -------
        The created or updated LinkedAccount object.

    """
    # Encrypt using pgcrypto function within the query
    # encrypted_token = encrypt_data(access_token) # Removed Fernet encryption

    # Check if an account already exists for this user and shop
    existing_account = (
        db.query(LinkedAccount)
        .filter(
            LinkedAccount.user_id == user_id,
            LinkedAccount.account_type == "shopify",
            LinkedAccount.account_name == shop_domain,
        )
        .first()
    )

    if existing_account:
        # Update existing account using pgcrypto function
        existing_account.encrypted_credentials = func.pgp_sym_encrypt(
            access_token, settings.PGCRYPTO_SYM_KEY
        )
        existing_account.scopes = scopes
        db_account = existing_account
    else:
        # Create new account using pgcrypto function
        db_account = LinkedAccount(
            user_id=user_id,
            account_type="shopify",
            account_name=shop_domain,
            # Use func.pgp_sym_encrypt directly here
            encrypted_credentials=func.pgp_sym_encrypt(
                access_token, settings.PGCRYPTO_SYM_KEY
            ),
            scopes=scopes,
        )
        db.add(db_account)

    try:
        db.commit()
        db.refresh(db_account)
        return db_account
    except Exception as e:
        db.rollback()
        # Log the error
        print(f"Error storing Shopify credentials with pgcrypto: {e}")
        raise  # Re-raise or handle appropriately


def get_decrypted_shopify_credentials(
    db: Session, user_id: uuid.UUID, shop_domain: str
) -> str | None:
    """Retrieves and decrypts Shopify credentials using pgcrypto.

    Args:
    ----
        db: SQLAlchemy Session.
        user_id: UUID of the user.
        shop_domain: The myshopify.com domain.

    Returns:
    -------
        The decrypted access token as a string, or None if not found or decryption fails.

    """
    try:
        # Query for the encrypted credentials and decrypt using pgcrypto function
        decrypted_token = (
            db.query(
                # Cast the result of decrypt to TEXT
                cast(
                    func.pgp_sym_decrypt(
                        LinkedAccount.encrypted_credentials, settings.PGCRYPTO_SYM_KEY
                    ),
                    TEXT,
                )
            )
            .filter(
                LinkedAccount.user_id == user_id,
                LinkedAccount.account_type == "shopify",
                LinkedAccount.account_name == shop_domain,
            )
            .scalar()
        )

        return decrypted_token  # Returns None if scalar() finds no row or decrypted value is NULL

    except Exception as e:
        # Log potential errors during decryption (e.g., wrong key, invalid data)
        print(
            f"Error decrypting Shopify credentials for user {user_id}, shop {shop_domain}: {e}"
        )
        return None
