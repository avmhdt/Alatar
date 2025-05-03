import pytest
import uuid
from sqlalchemy.orm import Session
from unittest.mock import patch, MagicMock

from app.services.action_executor import _execute_action_logic
from app.models.proposed_action import ProposedActionStatus
from app.models.user import User
from app.services.shopify_client import (
    ShopifyAdminAPIClient,
    ShopifyAdminAPIClientError,
)
from app.tests.utils import create_test_linked_account, create_test_proposed_action

# Assume db session fixture is available


@pytest.fixture
def mock_shopify_client():
    with patch(
        "app.services.action_executor.ShopifyAdminAPIClient"
    ) as mock_client_class:
        mock_instance = MagicMock(spec=ShopifyAdminAPIClient)
        # Mock specific methods if needed for success/failure cases
        mock_instance.update_product_price.return_value = {
            "productVariant": {"id": "gid://variant/1"}
        }
        mock_instance.create_discount.return_value = {
            "codeDiscountNode": {"id": "gid://discount/1"}
        }
        mock_instance.adjust_inventory.return_value = {
            "inventoryAdjustmentGroup": {"id": "gid://adjustment/1"}
        }
        mock_client_class.return_value = mock_instance
        yield mock_instance


def test_execute_action_success_update_price(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(
        db,
        user_id=test_user.id,
        account_type="shopify",
        scopes="read_products,write_products",
    )
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_update_product_price",
        parameters={
            "product_id": "gid://shopify/ProductVariant/123",
            "new_price": 99.99,
        },
        status=ProposedActionStatus.APPROVED,  # Start in approved state for direct test
    )

    # Call the logic directly for testing (background task wrapper calls this)
    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.EXECUTED
    assert "Execution successful" in action.execution_logs
    assert action.executed_at is not None
    mock_shopify_client.update_product_price.assert_called_once_with(
        product_variant_gid="gid://shopify/ProductVariant/123", new_price=99.99
    )


def test_execute_action_success_create_discount(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(
        db,
        user_id=test_user.id,
        account_type="shopify",
        scopes="read_price_rules,write_price_rules,read_discounts,write_discounts",
    )
    discount_details = {
        "title": "Test Discount",
        "code": "TEST25",
        "customerGets": {"value": {"percentage": 0.25}, "items": {"all": True}},
    }
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_create_discount_code",
        parameters={"discount_details": discount_details},
        status=ProposedActionStatus.APPROVED,
    )

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.EXECUTED
    mock_shopify_client.create_discount.assert_called_once_with(
        discount_details=discount_details
    )


def test_execute_action_success_adjust_inventory(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(
        db,
        user_id=test_user.id,
        account_type="shopify",
        scopes="read_locations,read_inventory,write_inventory",
    )
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_adjust_inventory",
        parameters={
            "inventory_item_gid": "gid://shopify/InventoryItem/1",
            "location_gid": "gid://shopify/Location/1",
            "delta": -5,
        },
        status=ProposedActionStatus.APPROVED,
    )

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.EXECUTED
    mock_shopify_client.adjust_inventory.assert_called_once_with(
        inventory_item_gid="gid://shopify/InventoryItem/1",
        location_gid="gid://shopify/Location/1",
        delta=-5,
    )


def test_execute_action_permission_denied(
    db: Session, test_user: User, mock_shopify_client
):
    # Grant insufficient scopes
    linked_account = create_test_linked_account(
        db, user_id=test_user.id, account_type="shopify", scopes="read_products"
    )
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_update_product_price",
        parameters={
            "product_id": "gid://shopify/ProductVariant/123",
            "new_price": 99.99,
        },
        status=ProposedActionStatus.APPROVED,
    )

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.FAILED
    assert "Permission denied" in action.execution_logs
    assert (
        "requires scopes: ['read_products', 'write_products']" in action.execution_logs
    )
    mock_shopify_client.update_product_price.assert_not_called()


def test_execute_action_shopify_api_error(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(
        db,
        user_id=test_user.id,
        account_type="shopify",
        scopes="read_products,write_products",
    )
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_update_product_price",
        parameters={
            "product_id": "gid://shopify/ProductVariant/invalid",
            "new_price": 99.99,
        },
        status=ProposedActionStatus.APPROVED,
    )

    # Configure mock to raise an error
    shopify_error = ShopifyAdminAPIClientError(
        "Invalid ID",
        status_code=422,
        shopify_errors=[{"field": ["id"], "message": "Product variant not found"}],
    )
    mock_shopify_client.update_product_price.side_effect = shopify_error

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.FAILED
    assert "Execution failed due to Shopify API error" in action.execution_logs
    assert "Product variant not found" in action.execution_logs
    mock_shopify_client.update_product_price.assert_called_once()


def test_execute_action_not_approved_state(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(db, user_id=test_user.id)
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="shopify_update_product_price",
        parameters={},
        status=ProposedActionStatus.PROPOSED,  # Incorrect starting state
    )

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.PROPOSED  # Status should not change
    assert action.execution_logs is None
    mock_shopify_client.update_product_price.assert_not_called()


def test_execute_action_not_found(db: Session, test_user: User):
    non_existent_id = uuid.uuid4()
    # No need to mock Shopify client as it won't be reached

    _execute_action_logic(db=db, action_id=non_existent_id)
    # No assertion possible on action status, just check that it doesn't raise unexpected errors


def test_execute_action_unsupported_type(
    db: Session, test_user: User, mock_shopify_client
):
    linked_account = create_test_linked_account(
        db, user_id=test_user.id, scopes="read_something,write_something"
    )
    action = create_test_proposed_action(
        db,
        user_id=test_user.id,
        linked_account_id=linked_account.id,
        action_type="unsupported_action_type",
        parameters={},
        status=ProposedActionStatus.APPROVED,
    )

    _execute_action_logic(db=db, action_id=action.id)

    db.refresh(action)
    assert action.status == ProposedActionStatus.FAILED
    assert (
        "Execution logic for action type 'unsupported_action_type' is not defined"
        in action.execution_logs
    )
    mock_shopify_client.update_product_price.assert_not_called()
    mock_shopify_client.create_discount.assert_not_called()
    mock_shopify_client.adjust_inventory.assert_not_called()


# TODO: Add tests for missing parameters in action.parameters
# TODO: Add tests for execute_approved_action wrapper function (ensuring session handling)
