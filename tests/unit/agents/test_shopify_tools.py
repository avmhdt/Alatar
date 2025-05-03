import pytest
import uuid
from unittest.mock import patch, MagicMock
from datetime import (
    datetime,
    timedelta,
    timezone,
)  # Ensure datetime imports are correct

from sqlalchemy.orm import Session

# Models and Services to Test/Mock
from app.agents.tools.shopify_tools import (
    GetShopifyProductsTool,
    GetShopifyOrdersTool,
    _fetch_with_cache,
    _generate_cache_key,
    DEFAULT_CACHE_TTL_SECONDS,
)
from app.models.linked_account import LinkedAccount
from app.models.cached_shopify_data import CachedShopifyData
from app.services.shopify_client import ShopifyAdminAPIClientError


# --- Fixtures ---
@pytest.fixture
def mock_db_session() -> MagicMock:
    """Provides a MagicMock substitute for a SQLAlchemy Session."""
    session = MagicMock(spec=Session)
    # Mock the query chain
    session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.first.return_value = None
    return session


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def shop_domain() -> str:
    return "test-shop.myshopify.com"


@pytest.fixture
def linked_account_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_linked_account(user_id, shop_domain, linked_account_id) -> MagicMock:
    """Provides a mocked LinkedAccount object."""
    account = MagicMock(spec=LinkedAccount)
    account.id = linked_account_id
    account.user_id = user_id
    account.account_name = shop_domain
    account.account_type = "shopify"
    return account


# --- Unit Tests for Helper Functions ---
def test_generate_cache_key():
    """Test cache key generation consistency and exclusion of specific keys."""
    prefix = "test:prefix"
    args1 = {"first": 10, "cursor": None, "db": "ignore", "user_id": "ignore"}
    args2 = {"cursor": None, "first": 10}  # Same logical args, different order
    args3 = {"first": 20, "cursor": None}  # Different args

    key1 = _generate_cache_key(prefix, args1)
    key2 = _generate_cache_key(prefix, args2)
    key3 = _generate_cache_key(prefix, args3)

    assert key1.startswith(prefix)
    assert key1 == key2  # Keys should be identical for same logical args
    assert key1 != key3  # Keys should differ for different args
    assert len(key1) > len(prefix) + 10  # Ensure hash is appended


# --- Unit Tests for Caching Logic (_fetch_with_cache) ---


@patch("app.agents.tools.shopify_tools.ShopifyAdminAPIClient")
@patch("app.agents.tools.shopify_tools._generate_cache_key")
@patch("app.agents.tools.shopify_tools.datetime")
def test_fetch_with_cache_cache_hit(
    mock_datetime,
    mock_generate_cache_key,
    MockShopifyClient,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
    mock_linked_account: MagicMock,
    linked_account_id: uuid.UUID,
):
    """Test cache hit: data is returned from cache, API client not called."""
    cache_key_prefix = "shopify:products"
    api_method_args = {"first": 10}
    cache_key = f"{cache_key_prefix}:some_hash"
    cached_data = {"data": "cached_product_data"}
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)

    mock_datetime.now.return_value = now
    mock_generate_cache_key.return_value = cache_key

    # Mock DB query for LinkedAccount
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )

    # Mock DB query for CachedShopifyData (cache hit)
    mock_cache_entry = MagicMock(spec=CachedShopifyData)
    mock_cache_entry.data = cached_data
    # Configure the mock chain correctly for the cache query
    mock_db_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = mock_cache_entry

    result = _fetch_with_cache(
        db=mock_db_session,
        user_id=user_id,
        shop_domain=shop_domain,
        cache_key_prefix=cache_key_prefix,
        api_method_name="get_products",
        api_method_args=api_method_args,
    )

    assert result == cached_data
    mock_generate_cache_key.assert_called_once_with(cache_key_prefix, api_method_args)
    # Check linked account query
    assert mock_db_session.query.call_args_list[0].args[0] == LinkedAccount
    # Check cache query filters
    filters = mock_db_session.query.return_value.filter.call_args_list
    assert (
        filters[1]
        .args[0]
        .compare(CachedShopifyData.linked_account_id == linked_account_id)
    )
    assert filters[2].args[0].compare(CachedShopifyData.cache_key == cache_key)
    assert filters[3].args[0].compare(CachedShopifyData.expires_at > now)
    MockShopifyClient.assert_not_called()  # API client should not be initialized
    mock_db_session.add.assert_not_called()  # Should not add to cache


@patch("app.agents.tools.shopify_tools.ShopifyAdminAPIClient")
@patch("app.agents.tools.shopify_tools._generate_cache_key")
@patch("app.agents.tools.shopify_tools.datetime")
def test_fetch_with_cache_cache_miss(
    mock_datetime,
    mock_generate_cache_key,
    MockShopifyClient,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
    mock_linked_account: MagicMock,
    linked_account_id: uuid.UUID,
):
    """Test cache miss: API is called, result is stored and returned."""
    cache_key_prefix = "shopify:orders"
    api_method_args = {"first": 5, "query_filter": "status:open"}
    cache_key = f"{cache_key_prefix}:another_hash"
    api_result = {"data": "fresh_order_data"}
    now = datetime(2023, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)

    mock_datetime.now.return_value = now
    mock_generate_cache_key.return_value = cache_key

    # Mock DB query for LinkedAccount
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )

    # Mock DB query for CachedShopifyData (cache miss)
    mock_db_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None

    # Mock Shopify Client instance and its method
    mock_api_client_instance = MockShopifyClient.return_value
    mock_api_client_instance.get_orders.return_value = api_result

    result = _fetch_with_cache(
        db=mock_db_session,
        user_id=user_id,
        shop_domain=shop_domain,
        cache_key_prefix=cache_key_prefix,
        api_method_name="get_orders",
        api_method_args=api_method_args,
        ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
    )

    assert result == api_result
    MockShopifyClient.assert_called_once_with(
        db=mock_db_session, user_id=user_id, shop_domain=shop_domain
    )
    mock_api_client_instance.get_orders.assert_called_once_with(**api_method_args)

    # Assert cache store was attempted
    mock_db_session.add.assert_called_once()
    # Check the object added
    added_object = mock_db_session.add.call_args[0][0]
    assert isinstance(added_object, CachedShopifyData)
    assert added_object.user_id == user_id
    assert added_object.linked_account_id == linked_account_id
    assert added_object.cache_key == cache_key
    assert added_object.data == api_result
    assert added_object.expires_at == expires_at
    mock_db_session.commit.assert_called_once()


@patch("app.agents.tools.shopify_tools.ShopifyAdminAPIClient")
@patch("app.agents.tools.shopify_tools._generate_cache_key")
@patch("app.agents.tools.shopify_tools.datetime")
def test_fetch_with_cache_expired(
    mock_datetime,
    mock_generate_cache_key,
    MockShopifyClient,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
    mock_linked_account: MagicMock,
    linked_account_id: uuid.UUID,
):
    """Test expired cache: API is called, new value stored."""
    cache_key_prefix = "shopify:products"
    api_method_args = {"first": 10}
    cache_key = f"{cache_key_prefix}:expired_hash"
    expired_data = {"data": "old_product_data"}
    fresh_api_result = {"data": "fresh_product_data"}
    now = datetime(2023, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    # Cache entry expires *just* before now
    expired_entry_expires_at = now - timedelta(seconds=1)

    mock_datetime.now.return_value = now
    mock_generate_cache_key.return_value = cache_key

    # Mock LinkedAccount query
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )

    # Mock DB query for CachedShopifyData (finds expired entry)
    mock_cache_entry = MagicMock(spec=CachedShopifyData)
    mock_cache_entry.data = expired_data
    # IMPORTANT: Mock the filter chain to return the expired entry
    # This means the expires_at > now check effectively fails
    mock_db_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None  # Simulates expiry check failing

    # Mock Shopify Client instance and its method
    mock_api_client_instance = MockShopifyClient.return_value
    mock_api_client_instance.get_products.return_value = fresh_api_result

    result = _fetch_with_cache(
        db=mock_db_session,
        user_id=user_id,
        shop_domain=shop_domain,
        cache_key_prefix=cache_key_prefix,
        api_method_name="get_products",
        api_method_args=api_method_args,
    )

    assert result == fresh_api_result
    MockShopifyClient.assert_called_once()
    mock_api_client_instance.get_products.assert_called_once_with(**api_method_args)
    mock_db_session.add.assert_called_once()
    # Check added object has the *fresh* data
    added_object = mock_db_session.add.call_args[0][0]
    assert added_object.data == fresh_api_result
    assert added_object.expires_at == now + timedelta(seconds=DEFAULT_CACHE_TTL_SECONDS)


def test_fetch_with_cache_no_linked_account(
    mock_db_session: MagicMock, user_id: uuid.UUID, shop_domain: str
):
    """Test _fetch_with_cache raises ValueError if linked account not found."""
    # Mock LinkedAccount query to return None
    mock_db_session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(ValueError, match=f"Shopify account '{shop_domain}' not found"):
        _fetch_with_cache(
            db=mock_db_session,
            user_id=user_id,
            shop_domain=shop_domain,
            cache_key_prefix="any",
            api_method_name="get_products",
            api_method_args={},
        )


@patch("app.agents.tools.shopify_tools.ShopifyAdminAPIClient")
@patch("app.agents.tools.shopify_tools._generate_cache_key")
@patch("app.agents.tools.shopify_tools.datetime")
def test_fetch_with_cache_api_error(
    mock_datetime,
    mock_generate_cache_key,
    MockShopifyClient,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
    mock_linked_account: MagicMock,
):
    """Test API error is raised and cache is not stored."""
    cache_key_prefix = "shopify:products"
    api_method_args = {"first": 10}
    cache_key = f"{cache_key_prefix}:api_error_hash"
    now = datetime(2023, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
    api_error_message = "Invalid API Key"

    mock_datetime.now.return_value = now
    mock_generate_cache_key.return_value = cache_key
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_linked_account
    )
    mock_db_session.query.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = None  # Cache miss

    # Mock Shopify Client to raise an error
    mock_api_client_instance = MockShopifyClient.return_value
    mock_api_client_instance.get_products.side_effect = ShopifyAdminAPIClientError(
        api_error_message
    )

    with pytest.raises(ShopifyAdminAPIClientError, match=api_error_message):
        _fetch_with_cache(
            db=mock_db_session,
            user_id=user_id,
            shop_domain=shop_domain,
            cache_key_prefix=cache_key_prefix,
            api_method_name="get_products",
            api_method_args=api_method_args,
        )

    MockShopifyClient.assert_called_once()
    mock_api_client_instance.get_products.assert_called_once()
    mock_db_session.add.assert_not_called()  # Cache should not be added on error
    mock_db_session.commit.assert_not_called()  # Commit should not happen if add wasn't called


# --- Unit Tests for Tools ---


@patch("app.agents.tools.shopify_tools._fetch_with_cache")
def test_get_shopify_products_tool_success(
    mock_fetch_with_cache,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
):
    """Test GetShopifyProductsTool calls _fetch_with_cache correctly."""
    tool = GetShopifyProductsTool()
    args = {
        "db": mock_db_session,
        "user_id": user_id,
        "shop_domain": shop_domain,
        "first": 5,
        "cursor": "abc",
    }
    expected_result = {"pageInfo": {"endCursor": "xyz"}, "edges": [{"node": "prod1"}]}
    mock_fetch_with_cache.return_value = expected_result

    # Use tool.invoke to simulate LCEL call style if needed, or _run for direct call
    # result = tool.invoke(args)
    result = tool._run(
        db=args["db"],
        user_id=args["user_id"],
        shop_domain=args["shop_domain"],
        first=args["first"],
        cursor=args["cursor"],
    )

    assert result == expected_result
    mock_fetch_with_cache.assert_called_once_with(
        db=mock_db_session,
        user_id=user_id,
        shop_domain=shop_domain,
        cache_key_prefix="shopify:products",
        api_method_name="get_products",
        api_method_args={"first": 5, "cursor": "abc"},  # Pass through provided args
    )


@patch("app.agents.tools.shopify_tools._fetch_with_cache")
def test_get_shopify_orders_tool_error(
    mock_fetch_with_cache,
    mock_db_session: MagicMock,
    user_id: uuid.UUID,
    shop_domain: str,
):
    """Test GetShopifyOrdersTool returns error string on failure."""
    tool = GetShopifyOrdersTool()
    args = {
        "db": mock_db_session,
        "user_id": user_id,
        "shop_domain": shop_domain,
        "first": 1,
        "query_filter": "invalid",
    }
    error_message = "Shopify API error detail"
    # Simulate different error types
    # mock_fetch_with_cache.side_effect = ShopifyAdminAPIClientError(error_message)
    mock_fetch_with_cache.side_effect = ValueError(
        "Linked account not found"
    )  # Example ValueError

    result = tool._run(
        db=args["db"],
        user_id=args["user_id"],
        shop_domain=args["shop_domain"],
        first=args["first"],
        query_filter=args["query_filter"],
    )

    assert isinstance(result, str)
    assert result == "Error fetching orders: Linked account not found"
    mock_fetch_with_cache.assert_called_once()


# --- Placeholder Tests for C2/C1 Components (Keep placeholders or remove if not testing here) ---
