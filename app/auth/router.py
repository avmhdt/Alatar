import hashlib
import hmac
from datetime import timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app import schemas
from app.auth import service as auth_service
from app.auth.dependencies import get_current_user_required as get_current_user
from app.core.config import settings
from app.database import get_db
from app.models.user import User

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


# --- Standard OAuth2 Token Endpoint (Moved under /auth prefix) ---
@router.post("/token", response_model=schemas.Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    # Use email from form_data.username for authentication
    user = auth_service.authenticate_user(
        db, email=form_data.username.lower(), password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Store user ID (as string) in the token's 'sub' claim
    access_token = auth_service.create_access_token(
        # Use settings for expiry
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- Shopify OAuth Endpoints ---


@router.get("/shopify/start")
def start_shopify_oauth(
    request: Request,
    shop: str = Query(
        ...,
        description="The user's myshopify.com domain (e.g., your-store.myshopify.com)",
    ),
    # Require user to be logged in to start the flow
    current_user: User = Depends(get_current_user),
):
    """Initiates the Shopify OAuth flow by redirecting the user to Shopify."""
    if not shop.endswith(".myshopify.com"):
        raise HTTPException(
            status_code=400, detail="Invalid shop domain. Must end with .myshopify.com"
        )

    try:
        auth_url, state = auth_service.generate_shopify_auth_url(shop_domain=shop)
        # Store the state in the session for later verification
        request.session["shopify_oauth_state"] = state
        # Optionally store the shop domain if needed on callback and not provided by Shopify (it usually is)
        # request.session['shopify_shop_domain'] = shop
        print(
            f"Redirecting user {current_user.id} to Shopify for shop {shop}"
        )  # Add logging
        return RedirectResponse(url=auth_url)
    except ValueError as e:
        # Handle configuration errors (missing keys etc.)
        raise HTTPException(status_code=500, detail=f"Server configuration error: {e}")
    except Exception as e:
        # Generic error handler
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )


@router.get("/shopify/callback")
def handle_shopify_callback(
    request: Request,
    db: Session = Depends(get_db),
    # Parameters from Shopify
    code: str = Query(...),
    hmac: str = Query(...),
    shop: str = Query(...),
    state: str = Query(...),
    timestamp: str = Query(...),
    # Optionally require user to be logged in, although state verification ties it somewhat.
    # If state doesn't include user info, we NEED the user to be logged in here.
    current_user: User = Depends(get_current_user),
):
    """Handles the callback from Shopify after user authorization."""
    # 1. Verify HMAC first!
    # Convert Starlette QueryParams to a simple dict for verification func
    query_param_dict = dict(request.query_params)
    if not settings.SHOPIFY_API_SECRET or not verify_shopify_hmac(
        query_param_dict, settings.SHOPIFY_API_SECRET
    ):
        print(f"HMAC verification failed for shop {shop}")  # Add logging
        raise HTTPException(status_code=403, detail="Invalid HMAC signature")

    # 2. Verify state (CSRF protection)
    stored_state = request.session.get("shopify_oauth_state")
    if not stored_state or not hmac.compare_digest(stored_state, state):
        print(
            f"State verification failed for shop {shop}. Stored: {stored_state}, Received: {state}"
        )  # Add logging
        raise HTTPException(status_code=403, detail="Invalid state parameter")

    # Clear the state from session now that it's verified
    request.session.pop("shopify_oauth_state", None)

    try:
        # 3. Exchange code for token
        token_data = auth_service.exchange_shopify_code_for_token(
            shop_domain=shop, code=code
        )
        access_token = token_data.get("access_token")
        scopes = token_data.get("scope")  # Use the scopes granted by Shopify
        # associated_user = token_data.get('associated_user') # Info about the user who authorized

        if not access_token or not scopes:
            print(
                f"Failed to get token or scope from Shopify for shop {shop}"
            )  # Add logging
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve access token details from Shopify",
            )

        # 4. Store credentials, linking to the currently logged-in user
        print(
            f"Storing credentials for user {current_user.id}, shop {shop}"
        )  # Add logging
        auth_service.store_shopify_credentials(
            db=db,
            user_id=current_user.id,
            shop_domain=shop,
            access_token=access_token,
            scopes=scopes,
        )

        # 5. Redirect user to a success page in the frontend
        # TODO: Make the redirect URL configurable
        frontend_success_url = f"{settings.CORS_ALLOWED_ORIGINS[0].strip('/')}/settings/connections?success=shopify"
        print(
            f"Successfully linked Shopify account for user {current_user.id}, shop {shop}"
        )  # Add logging
        return RedirectResponse(url=frontend_success_url)

    except ValueError as e:
        # Handle errors from service functions (e.g., config issues, token exchange failure)
        print(f"Error during Shopify callback for shop {shop}: {e}")  # Add logging
        raise HTTPException(status_code=400, detail=str(e))
    except requests.exceptions.RequestException as e:
        print(
            f"HTTP Request error during Shopify callback for shop {shop}: {e}"
        )  # Add logging
        raise HTTPException(
            status_code=502, detail="Failed to communicate with Shopify"
        )
    except Exception as e:
        print(
            f"Unexpected error during Shopify callback for shop {shop}: {e}"
        )  # Add logging
        # Generic error handler
        raise HTTPException(
            status_code=500, detail=f"An unexpected server error occurred: {e}"
        )


# Example route to test authentication (optional - now uses User model)
# @router.get("/users/me", response_model=schemas.User)
# async def read_users_me(current_user: User = Depends(auth_service.get_current_user)):
#     return current_user

# Verify CSRF token
csrf_token_cookie = request.cookies.get("csrf_token")
csrf_token_header = request.headers.get("X-CSRF-Token")

if not csrf_token_cookie or not csrf_token_header:
    raise HTTPException(status_code=400, detail="CSRF token missing")
# if csrf_token_cookie != csrf_token_header:
if not hmac.compare_digest(
    csrf_token_cookie, csrf_token_header
):  # Use hmac.compare_digest
    raise HTTPException(status_code=403, detail="CSRF token mismatch")
