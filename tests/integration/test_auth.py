import pytest
import httpx
import uuid
from sqlalchemy.orm import Session
from httpx import AsyncClient  # Use AsyncClient if testing async endpoints

from app.core.config import settings
from app.models.user import User

# Base URL for the running application (assuming default Docker port mapping)
BASE_URL = "http://localhost:8000"
GRAPHQL_URL = f"{BASE_URL}/graphql"


@pytest.mark.asyncio
async def test_user_registration_and_login():
    """
    Tests user registration and subsequent login via GraphQL mutations.
    """
    email = f"testuser_{uuid.uuid4()}@example.com"
    password = "strongpassword123"

    async with httpx.AsyncClient() as client:
        # 1. Test Registration
        register_mutation = """
            mutation Register($email: String!, $password: String!) {
                register(input: {email: $email, password: $password}) {
                    user {
                        id
                        email
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
        """
        register_vars = {"email": email, "password": password}
        print(f"\nAttempting to register user: {email}")
        response = await client.post(
            GRAPHQL_URL, json={"query": register_mutation, "variables": register_vars}
        )

        assert response.status_code == 200
        register_data = response.json()
        print(f"Registration response: {register_data}")
        assert (
            "errors" not in register_data
        ), f"GraphQL errors: {register_data.get('errors')}"
        assert (
            register_data["data"]["register"]["userErrors"] == []
        ), f"User errors: {register_data['data']['register']['userErrors']}"
        assert register_data["data"]["register"]["user"]["email"] == email
        assert "id" in register_data["data"]["register"]["user"]
        user_id = register_data["data"]["register"]["user"]["id"]
        print(f"Successfully registered user with ID: {user_id}")

        # 2. Test Registration Conflict (optional but good)
        print(f"Attempting to register conflicting user: {email}")
        response = await client.post(
            GRAPHQL_URL, json={"query": register_mutation, "variables": register_vars}
        )
        assert (
            response.status_code == 200
        )  # GraphQL handles business logic errors in the response body
        register_conflict_data = response.json()
        print(f"Conflict registration response: {register_conflict_data}")
        assert "errors" not in register_conflict_data
        assert register_conflict_data["data"]["register"]["user"] is None
        assert len(register_conflict_data["data"]["register"]["userErrors"]) == 1
        assert (
            register_conflict_data["data"]["register"]["userErrors"][0]["field"]
            == "email"
        )
        assert (
            "already registered"
            in register_conflict_data["data"]["register"]["userErrors"][0]["message"]
        )
        print("Successfully tested registration conflict.")

        # 3. Test Login
        login_mutation = """
            mutation Login($email: String!, $password: String!) {
                login(input: {email: $email, password: $password}) {
                    token
                    user {
                        id
                        email
                    }
                    userErrors {
                        field
                        message
                    }
                }
            }
        """
        login_vars = {"email": email, "password": password}
        print(f"Attempting to login user: {email}")
        response = await client.post(
            GRAPHQL_URL, json={"query": login_mutation, "variables": login_vars}
        )

        assert response.status_code == 200
        login_data = response.json()
        print(f"Login response: {login_data}")
        assert "errors" not in login_data, f"GraphQL errors: {login_data.get('errors')}"
        assert (
            login_data["data"]["login"]["userErrors"] == []
        ), f"User errors: {login_data['data']['login']['userErrors']}"
        assert login_data["data"]["login"]["user"]["email"] == email
        assert login_data["data"]["login"]["user"]["id"] == user_id
        assert "token" in login_data["data"]["login"]
        assert len(login_data["data"]["login"]["token"]) > 0
        access_token = login_data["data"]["login"]["token"]
        print(f"Successfully logged in. Token: {access_token[:10]}...")

        # Optional: Test login with wrong password
        wrong_login_vars = {"email": email, "password": "wrongpassword"}
        print(f"Attempting to login user with wrong password: {email}")
        response = await client.post(
            GRAPHQL_URL, json={"query": login_mutation, "variables": wrong_login_vars}
        )
        assert response.status_code == 200
        wrong_login_data = response.json()
        print(f"Wrong password login response: {wrong_login_data}")
        assert "errors" not in wrong_login_data
        assert wrong_login_data["data"]["login"]["token"] is None
        assert wrong_login_data["data"]["login"]["user"] is None
        assert len(wrong_login_data["data"]["login"]["userErrors"]) == 1
        assert (
            wrong_login_data["data"]["login"]["userErrors"][0]["field"] == "credentials"
        )
        print("Successfully tested login with wrong password.")


@pytest.mark.asyncio
async def test_shopify_oauth_start(
    client: AsyncClient, test_user_token: str, test_db: Session
):
    """Test the /auth/shopify/start endpoint."""
    shop_domain = "test-shop.myshopify.com"
    headers = {"Authorization": f"Bearer {test_user_token}"}

    response = await client.get(
        f"/auth/shopify/start?shop={shop_domain}",
        headers=headers,
        follow_redirects=False,
    )

    assert response.status_code == 307  # Check for redirect status
    assert "Location" in response.headers
    redirect_url = response.headers["Location"]

    assert redirect_url.startswith(f"https://{shop_domain}/admin/oauth/authorize")
    assert f"client_id={settings.SHOPIFY_API_KEY}" in redirect_url
    assert "scope=" in redirect_url  # Check if scopes are included
    assert "redirect_uri=" in redirect_url
    assert "state=" in redirect_url
    assert "grant_options[]=per-user" in redirect_url

    # TODO: Check if the state was correctly stored in the session.
    # This might require mocking the session middleware or inspecting session data
    # if the TestClient allows access to it.
    # Example (pseudo-code, depends on TestClient/middleware setup):
    # session_data = await client.get_session()
    # assert "shopify_oauth_state" in session_data
    # state_from_url = ... # Extract state from redirect_url
    # assert session_data["shopify_oauth_state"] == state_from_url

    # TODO: Add test case for invalid shop domain
    # TODO: Add test case for unauthenticated user


@pytest.mark.asyncio
async def test_shopify_oauth_callback_success(
    client: AsyncClient, test_user: User, test_user_token: str, test_db: Session, mocker
):
    """Test the /auth/shopify/callback endpoint for successful authorization."""
    shop_domain = "test-shop.myshopify.com"
    auth_code = "fake_auth_code_123"
    state = "fake_state_from_start_flow"  # This should match what was stored in session
    timestamp = "1678886400"

    # Mock the session to contain the expected state
    # TODO: Implement proper session mocking for TestClient
    # Example using hypothetical middleware access:
    # await client.set_session({"shopify_oauth_state": state})

    # Prepare query params and calculate expected HMAC
    query_params = {
        "code": auth_code,
        "shop": shop_domain,
        "state": state,
        "timestamp": timestamp,
        # Other params Shopify might send
    }
    # TODO: Calculate the correct expected HMAC using verify_shopify_hmac logic
    # hmac_val = calculate_expected_hmac(query_params, settings.SHOPIFY_API_SECRET)
    hmac_val = "dummy_hmac"  # Replace with actual calculation
    query_params["hmac"] = hmac_val

    callback_url = f"/auth/shopify/callback?code={auth_code}&hmac={hmac_val}&shop={shop_domain}&state={state}&timestamp={timestamp}"
    headers = {"Authorization": f"Bearer {test_user_token}"}

    # Mock the external call to Shopify to exchange the code for a token
    mock_exchange_response = {
        "access_token": "fake_access_token_xyz",
        "scope": ",".join(settings.SHOPIFY_SCOPES),  # Use configured scopes
    }
    mocker.patch(
        "app.auth.service.exchange_shopify_code_for_token",
        return_value=mock_exchange_response,
    )

    # Mock the store_shopify_credentials function or verify its call later
    mock_store_creds = mocker.patch(
        "app.auth.service.store_shopify_credentials", return_value=None
    )  # Assume it returns None on success

    response = await client.get(callback_url, headers=headers, follow_redirects=False)

    assert response.status_code == 307  # Check for redirect to frontend
    assert "Location" in response.headers
    assert "success=shopify" in response.headers["Location"]

    # Verify that exchange_shopify_code_for_token was called correctly
    # TODO: Add assertion for exchange_shopify_code_for_token call args

    # Verify that store_shopify_credentials was called correctly
    mock_store_creds.assert_called_once()
    call_args, _ = mock_store_creds.call_args
    assert call_args[0] == test_db  # Check db session
    assert call_args[1] == test_user.id  # Check user_id
    assert call_args[2] == shop_domain
    assert call_args[3] == mock_exchange_response["access_token"]
    assert call_args[4] == mock_exchange_response["scope"]

    # TODO: Verify that the state was cleared from the session

    # TODO: Verify that the LinkedAccount was actually created/updated in the DB
    # linked_account = test_db.query(LinkedAccount).filter(...).first()
    # assert linked_account is not None
    # assert linked_account.scopes == mock_exchange_response["scope"]
    # decrypted_token = security.decrypt_data(linked_account.encrypted_credentials)
    # assert decrypted_token == mock_exchange_response["access_token"]


@pytest.mark.asyncio
async def test_shopify_oauth_callback_invalid_hmac(
    client: AsyncClient, test_user_token: str
):
    """Test the callback with an invalid HMAC."""
    # TODO: Implement test logic similar to success case but with wrong HMAC
    # Assert response status code is 403
    pytest.skip("TODO: Implement test_shopify_oauth_callback_invalid_hmac")


@pytest.mark.asyncio
async def test_shopify_oauth_callback_invalid_state(
    client: AsyncClient, test_user_token: str
):
    """Test the callback with an invalid state."""
    # TODO: Implement test logic similar to success case but with wrong state
    # Mock session state differently from the state param in URL
    # Assert response status code is 403
    pytest.skip("TODO: Implement test_shopify_oauth_callback_invalid_state")


@pytest.mark.asyncio
async def test_shopify_oauth_callback_token_exchange_fails(
    client: AsyncClient, test_user_token: str, mocker
):
    """Test the callback when Shopify token exchange fails."""
    # TODO: Mock exchange_shopify_code_for_token to raise an exception
    # Assert response status code is appropriate (e.g., 400 or 502)
    pytest.skip("TODO: Implement test_shopify_oauth_callback_token_exchange_fails")


@pytest.mark.asyncio
async def test_shopify_oauth_callback_unauthenticated(client: AsyncClient):
    """Test the callback when the user is not authenticated."""
    # TODO: Call callback URL without Authorization header
    # Assert response status code is 401
    pytest.skip("TODO: Implement test_shopify_oauth_callback_unauthenticated")


# Add more tests later for RLS, etc.
# For RLS tests, you would typically:
# 1. Register two different users.
# 2. Create data belonging to user A (e.g., a LinkedAccount).
# 3. Log in as user B and attempt to query/mutate user A's data.
# 4. Assert that the operation fails or returns no data due to RLS.
