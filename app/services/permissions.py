# Placeholder for Shopify scope constants

# Read scopes
READ_PRODUCTS = "read_products"
READ_ORDERS = "read_orders"
READ_CUSTOMERS = "read_customers"
READ_INVENTORY = "read_inventory"
READ_LOCATIONS = "read_locations"
READ_PRICE_RULES = "read_price_rules"
READ_DISCOUNTS = "read_discounts"
# Add other read scopes as needed...

# Write scopes
WRITE_PRODUCTS = "write_products"
WRITE_ORDERS = "write_orders"  # Use with caution
WRITE_CUSTOMERS = "write_customers"
WRITE_INVENTORY = "write_inventory"
WRITE_DISCOUNTS = "write_discounts"
WRITE_PRICE_RULES = "write_price_rules"
# Add other write scopes as needed...

# Mapping of internal action types to required Shopify scopes
# This needs to be maintained based on the actions the agent can propose.
ACTION_SCOPE_MAPPING = {
    # Example action types (keys should match ProposedAction.action_type)
    "shopify_update_product_price": [READ_PRODUCTS, WRITE_PRODUCTS],
    "shopify_create_discount_code": [
        READ_PRICE_RULES,
        WRITE_PRICE_RULES,
        READ_DISCOUNTS,
        WRITE_DISCOUNTS,
    ],
    "shopify_adjust_inventory": [READ_LOCATIONS, READ_INVENTORY, WRITE_INVENTORY],
    "shopify_tag_customer": [READ_CUSTOMERS, WRITE_CUSTOMERS],
    "shopify_cancel_order": [READ_ORDERS, WRITE_ORDERS],  # Example of a risky action
    # Read-only actions (might still be proposed for confirmation?)
    "shopify_view_order_details": [READ_ORDERS],
    # --- Add mappings for all potential action types --- #
}


def check_scopes(required_scopes: list[str], granted_scopes: list[str]) -> bool:
    """Checks if all required scopes are present in the granted scopes."""
    granted_set = set(granted_scopes)
    for scope in required_scopes:
        if scope not in granted_set:
            return False
    return True


def get_required_scopes(action_type: str) -> list[str]:
    """Returns the list of required Shopify scopes for a given action type."""
    return ACTION_SCOPE_MAPPING.get(action_type, [])
