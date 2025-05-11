import hashlib
import hmac
from datetime import timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas, crud
from app.schemas.user import User, UserCreate
from app.auth import service as auth_service, get_current_user_optional
from app.core.config import settings
from app.database import get_async_db

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

# --- Helper for Shopify HMAC Verification ---


def verify_shopify_hmac(query_params: dict, secret: str) -> bool:
    """Verifies the HMAC signature of a Shopify request."""
    hmac_signature = query_params.get("hmac")
    if not hmac_signature:
        return False

    # Create the message string from parameters, excluding 'hmac' and 'signature'
    # Parameters must be sorted alphabetically
    params = []
    for key, value in sorted(query_params.items()):
        if key not in ["hmac", "signature"]:
            # Replace special characters as per Shopify documentation
            key_edited = key.replace("%", "%25").replace("&", "%26").replace("=", "%3D")
            value_edited = str(value).replace("%", "%25").replace("&", "%26")
            params.append(f"{key_edited}={value_edited}")

    message = "&".join(params)

    # Calculate the digest
    digest = hmac.new(
        secret.encode("utf-8"), msg=message.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()

    # Use secure comparison
    return hmac.compare_digest(digest, hmac_signature)


# --- Standard OAuth2 Token Endpoint (Email/Password Login) ---
@router.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: AsyncSession = Depends(get_async_db)
):
    user = await auth_service.authenticate_user(
        db, email=form_data.username.lower(), password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth_service.create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- Shopify OAuth Endpoints ---


@router.get("/shopify/start")
async def start_shopify_oauth(
    request: Request,
    shop: str = Query(
        ...,
        description="The user's myshopify.com domain (e.g., your-store.myshopify.com)",
    ),
    client_redirect_uri: str | None = Query(
        None, 
        description="Optional URI to redirect the client back to after Alatar\'s auth flow."
    ),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Initiates the Shopify OAuth flow by redirecting the user to Shopify."""
    if not shop.endswith(".myshopify.com"):
        raise HTTPException(
            status_code=400, detail="Invalid shop domain. Must end with .myshopify.com"
        )

    try:
        auth_url, state = auth_service.generate_shopify_auth_url(shop_domain=shop)
        request.session["shopify_oauth_state"] = state
        if client_redirect_uri:
            request.session["client_redirect_uri"] = client_redirect_uri
            logger.info(f"Storing client_redirect_uri for this session: {client_redirect_uri}")

        if current_user:
            logger.info(
                f"Redirecting user {current_user.id} to Shopify for shop {shop}"
            )
        else:
            logger.info(
                f"Redirecting new/unidentified user to Shopify for shop {shop}"
            )
        return RedirectResponse(url=auth_url)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"Server configuration error: {e}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )


@router.get("/shopify/callback")
async def handle_shopify_callback(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    code: str = Query(...),
    hmac: str = Query(...),
    shop: str = Query(...),
    state: str = Query(...),
    timestamp: str = Query(...),
):
    """Handles the callback from Shopify after user authorization during app install.
       Finds or creates a user based on Shopify info, links the account,
       and redirects the user to the frontend with a session token.
       If client_redirect_uri was provided in the start phase, redirects there.
    """
    logger.info(f"Received Shopify callback for shop {shop}")
    query_param_dict = dict(request.query_params)
    if not settings.SHOPIFY_API_SECRET or not verify_shopify_hmac(
        query_param_dict, settings.SHOPIFY_API_SECRET
    ):
        logger.error(f"HMAC verification failed for shop {shop}")
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")
    logger.debug(f"HMAC verified for shop {shop}")

    # Retrieve the client_redirect_uri from session if it was set
    client_redirect_uri = request.session.pop("client_redirect_uri", None)
    if client_redirect_uri:
        logger.info(f"Retrieved client_redirect_uri from session: {client_redirect_uri}")
        # TODO: IMPORTANT SECURITY VALIDATION:
        # Validate client_redirect_uri against an allowlist from settings
        # e.g., if client_redirect_uri not in settings.ALLOWED_CLIENT_REDIRECT_URIS:
        # raise HTTPException(status_code=400, detail="Invalid client_redirect_uri")
        pass # Placeholder for validation

    logger.debug(f"State parameter received: {state} (Verification skipped for install flow)")

    user: User | None = None
    try:
        logger.debug(f"Exchanging Shopify code for shop {shop}")
        token_data = auth_service.exchange_shopify_code_for_token(
            shop_domain=shop, code=code
        )
        access_token = token_data.get("access_token")
        scopes = token_data.get("scope")
        associated_user_data = token_data.get("associated_user")

        if not access_token or not scopes or not associated_user_data:
            logger.error(f"Missing access_token, scopes, or associated_user in Shopify response for shop {shop}")
            raise HTTPException(status_code=502, detail="Failed to get required details from Shopify")

        shopify_user_id = str(associated_user_data.get("id"))
        shopify_email = associated_user_data.get("email")
        
        if not shopify_user_id or not shopify_email:
             logger.error(f"Missing user ID or email in associated_user data from Shopify for shop {shop}")
             raise HTTPException(status_code=502, detail="Missing user details from Shopify")

        logger.info(f"Successfully exchanged code. Shopify User ID: {shopify_user_id}, Email: {shopify_email}")

        user = await crud.user.get_user_by_shopify_id(db, shopify_user_id=shopify_user_id)

        if user:
            logger.info(f"Found existing user (ID: {user.id}) for Shopify user ID {shopify_user_id}")
        else:
            logger.info(f"No existing user found for Shopify user ID {shopify_user_id}. Creating new user.")
            existing_email_user = await crud.user.get_user_by_email(db, email=shopify_email)
            if existing_email_user:
                 logger.error(f"Shopify email {shopify_email} already exists for a different user (ID: {existing_email_user.id}). Cannot link automatically.")
                 raise HTTPException(status_code=409, detail=f"Email {shopify_email} associated with this Shopify account already exists in our system. Please log in with your existing account and link Shopify manually, or contact support.")
            
            user_in = UserCreate(email=shopify_email, password=None)
            user = await crud.user.create_user(
                db=db, obj_in=user_in, shopify_user_id=shopify_user_id
            )
            logger.info(f"Created new user (ID: {user.id}) for Shopify user ID {shopify_user_id}")

        logger.info(f"Storing Shopify credentials for user {user.id} and shop {shop}")
        await auth_service.store_shopify_credentials(
            db=db,
            user_id=user.id,
            shop_domain=shop,
            access_token=access_token,
            scopes=scopes,
        )

        logger.info(f"Creating JWT token for user {user.id}")
        app_token = auth_service.create_access_token(
            data={"sub": str(user.id)},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        final_redirect_url: str
        if client_redirect_uri:
            # Ensure client_redirect_uri does not have existing fragment
            base_client_redirect_uri = client_redirect_uri.split('#')[0]
            final_redirect_url = f"{base_client_redirect_uri}#token={app_token}"
            logger.info(f"Redirecting user {user.id} to client_redirect_uri: {final_redirect_url.split('#')[0]}...")
        else:
            final_redirect_url = f"{settings.FRONTEND_URL.strip('/')}/auth/callback#token={app_token}"
            logger.info(f"Redirecting user {user.id} to Alatar frontend: {final_redirect_url.split('#')[0]}...")
        
        return RedirectResponse(url=final_redirect_url)

    except HTTPException as e:
        logger.error(f"HTTPException during Shopify callback for shop {shop}: {e.detail} (Status: {e.status_code})")
        raise e 
    except ValueError as e:
        logger.error(f"ValueError during Shopify callback for shop {shop}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP Request error during Shopify callback for shop {shop}: {e}")
        raise HTTPException(status_code=502, detail="Failed to communicate with Shopify")
    except Exception as e:
        user_id_info = f"user {user.id}" if user else "unknown user"
        logger.exception(f"Unexpected error during Shopify callback for {user_id_info}, shop {shop}: {e}")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred during Shopify authentication.")


# Example route to test authentication (optional - now uses User model)
# @router.get("/users/me", response_model=User)
# async def read_users_me(current_user: User = Depends(auth_service.get_current_user)):
#     return current_user

