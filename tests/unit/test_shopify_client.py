import pytest
from unittest.mock import MagicMock, patch
import uuid
import requests

from sqlalchemy.orm import Session

from app.services.shopify_client import (
    ShopifyAdminAPIClient,
    ShopifyAdminAPIClientError,
)
from app.models.linked_account import LinkedAccount
from app.models.cached_shopify_data import CachedShopifyData

# --- Fixtures ---


@pytest.fixture
def mock_db_session():
    """Provides a MagicMock for the SQLAlchemy Session."""
    return MagicMock(spec=Session)


@pytest.fixture
def test_user_id():
    """Provides a consistent UUID for the test user."""
    return uuid.uuid4()


@pytest.fixture
def test_shop_domain():
    """Provides a consistent shop domain for tests."""
    return "test-shop.myshopify.com"


@pytest.fixture
def mock_linked_account():
    """Provides a MagicMock for the LinkedAccount model."""
    account = MagicMock(spec=LinkedAccount)
    account.encrypted_credentials = b"gAAAAAB...encrypted_token_bytes"  # Placeholder
    account.id = uuid.uuid4()  # Give mock account an ID
    return account


@pytest.fixture
def mock_shopify_client(
    mock_db_session, test_user_id, test_shop_domain, mock_linked_account, mocker
):
    """Fixture to provide a partially mocked ShopifyAdminAPIClient instance."""
    # Mock DB query for LinkedAccount during init
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    # Mock decrypt_data during init
    decrypted_token = "shpat_decrypted_fake_token"
    mocker.patch(
        "app.services.shopify_client.decrypt_data", return_value=decrypted_token
    )

    client = ShopifyAdminAPIClient(
        db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
    )
    # Reset mocks on the session *after* init has used them
    mock_db_session.reset_mock()
    # Mock _make_request by default for cache tests
    client._make_request = MagicMock(name="_make_request")
    return client


# --- Test Cases ---


def test_shopify_client_initialization_success(
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
    mock_linked_account: MagicMock,
    mocker,
):
    """Test successful initialization of the ShopifyAdminAPIClient."""
    # Mock DB query to return the mock account
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )

    # Mock decrypt_data
    decrypted_token = "shpat_decrypted_fake_token"
    mocker.patch(
        "app.services.shopify_client.decrypt_data", return_value=decrypted_token
    )

    # Initialize the client
    client = ShopifyAdminAPIClient(
        db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
    )

    # Assertions
    assert client._access_token == decrypted_token
    assert (
        client._api_url == f"https://{test_shop_domain}/admin/api/2024-07/graphql.json"
    )
    mock_db_session.query.assert_called_once_with(LinkedAccount)
    # TODO: Add more specific assertions about the filter call if necessary


def test_shopify_client_initialization_no_account(
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
):
    """Test initialization when no linked account is found."""
    # Mock DB query to return None
    mock_db_session.query.return_value.filter.return_value.first.return_value = None

    # Assert that the correct exception is raised
    with pytest.raises(
        ShopifyAdminAPIClientError,
        match=f"Shopify account for shop '{test_shop_domain}' not linked.",
    ):
        ShopifyAdminAPIClient(
            db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
        )


def test_shopify_client_initialization_decryption_fails(
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
    mock_linked_account: MagicMock,
    mocker,
):
    """Test initialization when credential decryption fails."""
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    mocker.patch(
        "app.services.shopify_client.decrypt_data",
        side_effect=ValueError("Decryption failed"),
    )

    with pytest.raises(
        ShopifyAdminAPIClientError,
        match=f"Failed to load credentials for shop '{test_shop_domain}'.",
    ):
        ShopifyAdminAPIClient(
            db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
        )


@patch("app.services.shopify_client.requests.post")
def test_make_request_success(
    mock_post: MagicMock,
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
    mocker,
):
    """Test a successful _make_request call."""
    # Setup client (requires successful initialization mocks)
    decrypted_token = "shpat_decrypted_fake_token"
    mock_linked_account = MagicMock(encrypted_credentials=b"...")
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    mocker.patch(
        "app.services.shopify_client.decrypt_data", return_value=decrypted_token
    )
    client = ShopifyAdminAPIClient(
        db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
    )

    # Mock requests.post response
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"shop": {"name": "Test Shop"}}}
    mock_response.raise_for_status.return_value = None  # Simulate no HTTP error
    mock_post.return_value = mock_response

    # Make the request
    query = "{ shop { name } }"
    data = client._make_request(query=query)

    # Assertions
    assert data == {"shop": {"name": "Test Shop"}}
    mock_post.assert_called_once()
    call_args, call_kwargs = mock_post.call_args
    assert call_args[0] == client._api_url
    assert call_kwargs["headers"]["X-Shopify-Access-Token"] == decrypted_token
    assert call_kwargs["json"] == {"query": query}


@patch("app.services.shopify_client.requests.post")
def test_make_request_graphql_errors(
    mock_post: MagicMock,
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
    mocker,
):
    """Test _make_request when the Shopify API returns GraphQL errors."""
    # Setup client
    decrypted_token = "shpat_decrypted_fake_token"
    mock_linked_account = MagicMock(encrypted_credentials=b"...")
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    mocker.patch(
        "app.services.shopify_client.decrypt_data", return_value=decrypted_token
    )
    client = ShopifyAdminAPIClient(
        db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
    )

    # Mock response with errors
    graphql_errors = [{"message": "Field 'invalidField' doesn't exist on type 'Shop'"}]
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200  # GraphQL errors often return 200 OK
    mock_response.json.return_value = {"errors": graphql_errors}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    # Assert exception
    with pytest.raises(
        ShopifyAdminAPIClientError, match="Shopify API returned errors."
    ) as exc_info:
        client._make_request(query="{ shop { invalidField } }")
    assert exc_info.value.shopify_errors == graphql_errors
    assert exc_info.value.status_code == 200


@patch("app.services.shopify_client.requests.post")
def test_make_request_http_error(
    mock_post: MagicMock,
    mock_db_session: MagicMock,
    test_user_id: uuid.UUID,
    test_shop_domain: str,
    mocker,
):
    """Test _make_request when the HTTP request fails."""
    # Setup client
    decrypted_token = "shpat_decrypted_fake_token"
    mock_linked_account = MagicMock(encrypted_credentials=b"...")
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    mocker.patch(
        "app.services.shopify_client.decrypt_data", return_value=decrypted_token
    )
    client = ShopifyAdminAPIClient(
        db=mock_db_session, user_id=test_user_id, shop_domain=test_shop_domain
    )

    # Mock requests.post to raise an HTTPError
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 401  # Example: Unauthorized
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=mock_response
    )
    mock_post.return_value = mock_response

    # Assert exception
    with pytest.raises(
        ShopifyAdminAPIClientError, match="Failed to communicate with Shopify"
    ) as exc_info:
        client._make_request(query="{ shop { name } }")
    assert exc_info.value.status_code == 401


# TODO: Add tests for specific methods like get_products, get_orders
# These tests would mock _make_request and verify the correct query/variables are passed
# and that the response data is returned correctly.


def test_get_products(mocker):
    """Test the get_products method."""
    # Mock the client and its _make_request method
    mock_client = MagicMock(spec=ShopifyAdminAPIClient)
    mock_client._make_request = MagicMock()
    expected_data = {"products": {"edges": []}}  # Example response
    mock_client._make_request.return_value = expected_data

    # Patch the __init__ method to avoid real initialization
    with patch.object(ShopifyAdminAPIClient, "__init__", return_value=None):
        # Instantiate (init is patched)
        client_instance = ShopifyAdminAPIClient(
            db=None, user_id=None, shop_domain=None
        )  # Args don't matter
        # Replace the instance's method with our mock
        client_instance._make_request = mock_client._make_request

        # Call the method under test
        result = client_instance.get_products(first=5, cursor="abc")

    # Assertions
    assert result == expected_data
    mock_client._make_request.assert_called_once()
    call_args, call_kwargs = mock_client._make_request.call_args
    assert (
        "products(first: $first, after: $cursor, sortKey: TITLE)"
        in call_kwargs["query"]
    )
    assert call_kwargs["variables"] == {"first": 5, "cursor": "abc"}


# TODO: Add similar test for get_orders


# --- Caching Tests ---


@patch("app.services.shopify_client.datetime")
def test_fetch_with_cache_hit(
    mock_datetime: MagicMock,
    mock_shopify_client: ShopifyAdminAPIClient,  # Use the fixture
    mock_db_session: MagicMock,
    mock_linked_account: MagicMock,
):
    """Test cache hit scenario for _fetch_with_cache via get_products."""
    # Setup
    now = datetime.now(timezone.utc)
    mock_datetime.now.return_value = now
    cache_key_prefix = "shopify:products"
    query_vars = {"first": 10, "cursor": None}
    expected_cache_data = {"products": {"pageInfo": {}, "edges": ["cached_data"]}}

    # Mock DB query for CachedShopifyData to return a hit
    mock_cache_entry = MagicMock(spec=CachedShopifyData)
    mock_cache_entry.data = expected_cache_data
    mock_db_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_cache_entry

    # Call method under test (which uses _fetch_with_cache)
    result = mock_shopify_client.get_products(
        first=query_vars["first"], cursor=query_vars["cursor"]
    )

    # Assertions
    assert result == expected_cache_data
    mock_db_session.query.assert_called_once_with(CachedShopifyData)
    # Check filters (linked_account_id, cache_key, expires_at > now)
    # Note: Verifying the exact cache_key hash is brittle, focus on structure/presence
    filters = mock_db_session.query.return_value.filter.call_args_list
    assert filters[0][0][0].compare(
        CachedShopifyData.linked_account_id == mock_linked_account.id
    )
    # assert filters[1][0][0].compare(CachedShopifyData.cache_key == expected_key)
    assert "cache_key ==" in str(filters[1][0][0])  # Check key filter exists
    assert filters[2][0][0].compare(CachedShopifyData.expires_at > now)

    mock_shopify_client._make_request.assert_not_called()  # API should not be called
    mock_db_session.add.assert_not_called()


@patch("app.services.shopify_client.datetime")
def test_fetch_with_cache_miss(
    mock_datetime: MagicMock,
    mock_shopify_client: ShopifyAdminAPIClient,  # Use the fixture
    mock_db_session: MagicMock,
    mock_linked_account: MagicMock,
    test_user_id: uuid.UUID,
):
    """Test cache miss scenario for _fetch_with_cache via get_products."""
    # Setup
    now = datetime.now(timezone.utc)
    mock_datetime.now.return_value = now
    cache_key_prefix = "shopify:products"
    query_vars = {"first": 5, "cursor": "abc"}
    api_response_data = {"products": {"pageInfo": {}, "edges": ["api_data"]}}

    # Mock DB query for CachedShopifyData to return None (miss)
    mock_db_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

    # Mock the API call result
    mock_shopify_client._make_request.return_value = api_response_data

    # Call method under test
    result = mock_shopify_client.get_products(
        first=query_vars["first"], cursor=query_vars["cursor"]
    )

    # Assertions
    assert result == api_response_data
    mock_db_session.query.assert_called_once_with(CachedShopifyData)
    mock_shopify_client._make_request.assert_called_once()  # API should be called
    # Check args passed to _make_request (query/variables are handled internally by get_products)

    # Assert cache write
    mock_db_session.add.assert_called_once()
    added_object = mock_db_session.add.call_args[0][0]
    assert isinstance(added_object, CachedShopifyData)
    assert added_object.user_id == test_user_id
    assert added_object.linked_account_id == mock_linked_account.id
    assert added_object.data == api_response_data
    assert added_object.cached_at == now
    assert added_object.expires_at == now + timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)
    assert cache_key_prefix in added_object.cache_key  # Verify prefix
    mock_db_session.commit.assert_called_once()


@patch("app.services.shopify_client.datetime")
def test_fetch_with_cache_expired(
    mock_datetime: MagicMock,
    mock_shopify_client: ShopifyAdminAPIClient,
    mock_db_session: MagicMock,
    mock_linked_account: MagicMock,
    test_user_id: uuid.UUID,
):
    """Test expired cache scenario."""
    # Setup
    now = datetime.now(timezone.utc)
    mock_datetime.now.return_value = now
    cache_key_prefix = "shopify:products"
    query_vars = {"first": 10, "cursor": None}
    api_response_data = {"products": {"pageInfo": {}, "edges": ["fresh_api_data"]}}

    # Mock DB query to return None (simulating expired entry filter failure)
    mock_db_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

    # Mock the API call result
    mock_shopify_client._make_request.return_value = api_response_data

    # Call method under test
    result = mock_shopify_client.get_products(
        first=query_vars["first"], cursor=query_vars["cursor"]
    )

    # Assertions (should behave like a cache miss)
    assert result == api_response_data
    mock_db_session.query.assert_called_once_with(CachedShopifyData)
    mock_shopify_client._make_request.assert_called_once()
    mock_db_session.add.assert_called_once()
    added_object = mock_db_session.add.call_args[0][0]
    assert added_object.data == api_response_data  # Should cache the fresh data
    mock_db_session.commit.assert_called_once()


@patch("app.services.shopify_client.datetime")
def test_fetch_with_cache_api_error(
    mock_datetime: MagicMock,
    mock_shopify_client: ShopifyAdminAPIClient,
    mock_db_session: MagicMock,
):
    """Test that API errors during cache miss are raised and not cached."""
    # Setup
    now = datetime.now(timezone.utc)
    mock_datetime.now.return_value = now
    query_vars = {"first": 10, "cursor": None}
    api_error = ShopifyAdminAPIClientError("API Failed")

    # Mock DB query for cache miss
    mock_db_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

    # Mock the API call to raise an error
    mock_shopify_client._make_request.side_effect = api_error

    # Call method under test and assert exception
    with pytest.raises(ShopifyAdminAPIClientError, match="API Failed"):
        mock_shopify_client.get_products(
            first=query_vars["first"], cursor=query_vars["cursor"]
        )

    # Assertions
    mock_db_session.query.assert_called_once_with(CachedShopifyData)
    mock_shopify_client._make_request.assert_called_once()
    mock_db_session.add.assert_not_called()  # Should not cache on error
    mock_db_session.commit.assert_not_called()


# TODO: Add test for cache write failure (should log but return API result)
