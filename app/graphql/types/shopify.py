import strawberry

from app.graphql.relay import Node  # Assuming Node interface is defined here


@strawberry.type
class ShopifyStore(Node):
    """Represents a linked Shopify store."""

    # id field inherited from Node (global ID)
    shop_domain: str = strawberry.field(
        description="The myshopify.com domain of the store."
    )
    # Add other relevant fields as needed, e.g.:
    # name: Optional[str] = strawberry.field(description="The display name of the Shopify store.", default=None)
    # is_active: bool = strawberry.field(description="Indicates if the connection is currently active.", default=True)
    # created_at: datetime = strawberry.field(description="Timestamp when the store was linked.")
    # updated_at: datetime = strawberry.field(description="Timestamp when the store link was last updated.")
