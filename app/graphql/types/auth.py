import strawberry

# Import base types
from .common import LinkedAccount
from .user_error import UserError


# --- Input Types ---
@strawberry.input
class CompleteShopifyOAuthInput:
    code: str = strawberry.field(
        description="The authorization code from Shopify callback."
    )
    shop: str = strawberry.field(
        description="The user's myshopify.com domain used to initiate the flow."
    )
    state: str = strawberry.field(
        description="The state parameter received from Shopify callback for CSRF verification."
    )
    # host: Optional[str] = None # Maybe needed if dynamically generated
    # timestamp: Optional[str] = None # Maybe needed if dynamically generated


# --- Payloads ---
@strawberry.type
class CompleteShopifyOAuthPayload:
    linked_account: LinkedAccount | None = None
    userErrors: list[UserError] = strawberry.field(default_factory=list)


# Placeholder for other Auth types if needed
@strawberry.type
class User:
    pass  # Define fully elsewhere or import


@strawberry.type
class AuthPayload:
    token: str
    user: User | None
    userErrors: list[UserError] = strawberry.field(default_factory=list)


@strawberry.type
class RegisterPayload:
    user: User | None
    userErrors: list[UserError] = strawberry.field(default_factory=list)


@strawberry.type
class ShopifyOAuthStartPayload:
    authorization_url: str | None
    state: str | None
    userErrors: list[UserError] = strawberry.field(default_factory=list)
