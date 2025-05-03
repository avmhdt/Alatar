import uuid
from collections.abc import AsyncGenerator

import strawberry
from sqlalchemy.orm import Session
from strawberry.fastapi import BaseContext
from strawberry.types import Info as StrawberryInfo

from app import schemas
from app.auth.dependencies import get_optional_user_id_from_token
from app.database import current_user_id_cv, get_db
from app.graphql.resolvers.analysis_request import (
    get_analysis_request,  # Import query
    list_analysis_requests,  # Import query
    submit_analysis_request,
)
from app.graphql.resolvers.proposed_action import (
    list_proposed_actions,
    user_approves_action,
    user_rejects_action,
)

# Import analysis request types and resolvers
from app.graphql.types.analysis_request import (
    AnalysisRequest as AnalysisRequestGQL,  # Rename to avoid conflict if needed
)
from app.graphql.types.analysis_request import (
    AnalysisRequestConnection,  # Import connection type
    SubmitAnalysisRequestInput,
    SubmitAnalysisRequestPayload,
)

# Import proposed action types and resolvers
from app.graphql.types.proposed_action import (
    ProposedActionConnection,
    UserApproveActionInput,
    UserApproveActionPayload,
    UserRejectActionInput,
    UserRejectActionPayload,
)

# Import the custom error handler extension
from .extensions.error_handler import CustomErrorHandler  # Updated import path

# Import Node interface and resolver
from .relay import Node, get_node
from .resolvers.auth import (
    complete_shopify_oauth,  # Import the new resolver
)

# Import subscription resolver
from .resolvers.subscription import (
    analysis_request_updates,  # Import the subscription resolver
)
from .resolvers.user import (
    get_current_user_info,
    update_user_preferences,
)

# Import publisher if needed elsewhere (e.g., testing)
# Import specific types needed for schema definition (if not covered by resolvers)
from .types import UserPreferences, UserPreferencesPayload, UserPreferencesUpdateInput

# Import auth types and resolver
from .types.auth import (
    AuthPayload,  # Keep if needed
    CompleteShopifyOAuthInput,
    CompleteShopifyOAuthPayload,
    RegisterPayload,  # Keep if needed
    ShopifyOAuthStartPayload,  # Keep if needed
)

# Import common types needed for schema registration
from .types.common import (
    AnalysisResult,
    LinkedAccount,
    UserPreferences,
    Visualization,
    VisualizationType,
)

# Import newly defined Shopify types
from .types.shopify import ShopifyStore

# Import User related types and resolvers
from .types.user import (
    User,
    UserPreferencesPayload,
    UserPreferencesUpdateInput,
)

# Import base types and resolvers - Structure needs review
# Assuming RootQuery/Mutation/Subscription are defined elsewhere or combined
# from .resolvers import Query as RootQuery # Placeholder
# from .resolvers import Mutation as RootMutation # Placeholder
# from .resolvers import Subscription as RootSubscription # Placeholder
# Import the UserError type
from .types.user_error import UserError  # Updated import


# --- Custom Context ---
# Useful for passing request-scoped objects like DB session
class Context(BaseContext):
    db: Session

    async def get_context(self) -> "Context":
        # Ensure get_db yields a session correctly
        db_gen = get_db()
        user_id: uuid.UUID | None = None
        try:
            # --- RLS Context Setup ---
            # Attempt to get user_id from token *before* session is used further.
            # This relies on the `request` being available in BaseContext.
            if self.request:
                user_id = get_optional_user_id_from_token(self.request)
                if user_id:
                    # Set the context variable. The SQLAlchemy 'after_begin' listener
                    # in database.py will use this to set app.current_user_id.
                    token = current_user_id_cv.set(user_id)
                    # We might need to reset this token later, although get_db also resets
                    # print(f"GraphQL Context: Set current_user_id_cv to {user_id}") # Optional logging

            # --- Get DB Session ---
            session = next(db_gen)
            self.db = session

            # --- Yield Context ---
            # The db session now has the RLS context set (if user_id was found)
            # via the SQLAlchemy event listener triggered by current_user_id_cv.
            yield self

        finally:
            # --- Cleanup ---
            # Close the session via the generator's finally block
            next(
                db_gen, None
            )  # Consumes the closing part of the context manager from get_db

            # Optional: Reset the context var if it was set here, though get_db should handle it.
            # if user_id and 'token' in locals():
            #     current_user_id_cv.reset(token)
            #     print("GraphQL Context: Reset current_user_id_cv") # Optional logging


# --- Object Types (Example: Define directly or import from types) ---
@strawberry.experimental.pydantic.type(model=schemas.User, all_fields=True)
class UserGQLTypeFromPydantic:  # Renamed to avoid conflict with imported User type
    pass


@strawberry.type
class AuthPayload:
    token: str
    user: User | None = None  # Use the GQL User type
    userErrors: list[UserError] = strawberry.field(default_factory=list)


@strawberry.type
class RegisterPayload:
    user: User | None = None  # Use the GQL User type
    userErrors: list[UserError] = strawberry.field(default_factory=list)


@strawberry.type
class ShopifyOAuthStartPayload:
    authorization_url: str | None = None
    state: str | None = None  # Return state for frontend to handle
    userErrors: list[UserError] = strawberry.field(default_factory=list)


# --- Input Types ---
@strawberry.experimental.pydantic.input(model=schemas.UserCreate)
class UserRegisterInput:
    pass


@strawberry.input
class UserLoginInput:
    email: str
    password: str


@strawberry.input
class StartShopifyOAuthInput:
    shop_domain: str = strawberry.field(
        description="The user's myshopify.com domain (e.g., your-store.myshopify.com)"
    )
    # frontend_callback_url: str # Optional: if callback needs to be dynamic


# --- Root Query/Mutation/Subscription Definitions ---

# Define Root types here or import them if split into multiple files


@strawberry.type
class Query:
    # Node field for Relay
    @strawberry.field
    async def node(self, info: StrawberryInfo, id: strawberry.ID) -> Node | None:
        """Fetches an object given its globally unique ID."""
        return await get_node(info=info, global_id=id)

    # Placeholder for root query fields
    # Inherit from imported base RootQuery if using that pattern
    @strawberry.field
    def hello(self) -> str:
        return "World"

    # Add me query
    @strawberry.field
    async def me(self, info: StrawberryInfo) -> User | None:
        """Retrieves information about the currently authenticated user."""
        # Delegate to resolver function
        return await get_current_user_info(info=info)

    # Add list_proposed_actions from its resolver
    @strawberry.field
    def list_proposed_actions(
        self,
        info: StrawberryInfo,
        first: int = 10,
        after: strawberry.relay.ConnectionCursor | None = None,
    ) -> ProposedActionConnection:
        """List pending proposed actions for the current user."""
        # Actual call is delegated to the imported function
        return list_proposed_actions(info=info, first=first, after=after)

    # Add analysis request queries
    @strawberry.field
    def analysis_request(
        self, info: StrawberryInfo, id: strawberry.ID
    ) -> AnalysisRequestGQL | None:
        """Retrieves a single analysis request by its global ID, if accessible by the current user."""
        # Actual call is delegated to the imported function
        return get_analysis_request(info=info, id=id)

    @strawberry.field
    def list_analysis_requests(
        self,
        info: StrawberryInfo,
        first: int = 10,
        after: str | None = None,
    ) -> AnalysisRequestConnection:
        """Lists the analysis requests for the current user, paginated."""
        # Actual call is delegated to the imported function
        return list_analysis_requests(info=info, first=first, after=after)

    # Add me, myPreferences etc. later


@strawberry.type
class Mutation:
    # Placeholder for root mutation fields
    # Inherit from imported base RootMutation if using that pattern

    # Add HITL mutations from proposed_action resolver
    @strawberry.mutation
    def user_approves_action(
        self, info: StrawberryInfo, input: UserApproveActionInput
    ) -> UserApproveActionPayload:
        """Approve a proposed action, triggering its execution if permissions allow."""
        # Actual call is delegated to the imported function
        return user_approves_action(info=info, input=input)

    @strawberry.mutation
    def user_rejects_action(
        self, info: StrawberryInfo, input: UserRejectActionInput
    ) -> UserRejectActionPayload:
        """Reject a proposed action."""
        # Actual call is delegated to the imported function
        return user_rejects_action(info=info, input=input)

    # Add submit_analysis_request mutation
    @strawberry.mutation
    async def submit_analysis_request(
        self, info: StrawberryInfo, input: SubmitAnalysisRequestInput
    ) -> SubmitAnalysisRequestPayload:
        """Submits a new analysis request and queues it for processing."""
        # Actual call is delegated to the imported function
        return await submit_analysis_request(info=info, input=input)

    # Add update_preferences mutation
    @strawberry.mutation
    async def update_preferences(
        self, info: StrawberryInfo, input: UserPreferencesUpdateInput
    ) -> UserPreferencesPayload:
        """Updates the preferences for the currently authenticated user."""
        # Delegate to resolver function
        return await update_user_preferences(info=info, input=input)

    # Add complete_shopify_oauth mutation
    @strawberry.mutation
    async def complete_shopify_oauth(
        self, info: StrawberryInfo, input: CompleteShopifyOAuthInput
    ) -> CompleteShopifyOAuthPayload:
        """Completes the Shopify OAuth flow by exchanging the code for a token and linking the account."""
        return await complete_shopify_oauth(info=info, input=input)

    # Add register, login later if needed


@strawberry.type
class Subscription:
    # Placeholder for root subscription fields
    # Inherit from imported base RootSubscription if using that pattern
    # @strawberry.subscription
    # async def count(self, target: int = 10) -> AsyncGenerator[int, None]:
    #     for i in range(target):
    #         yield i
    #         await asyncio.sleep(0.5)

    # Add analysisRequestUpdates subscription
    @strawberry.subscription
    async def analysis_request_updates(
        self, info: StrawberryInfo, request_id: strawberry.ID
    ) -> AsyncGenerator[AnalysisRequestGQL, None]:
        """Subscribe to real-time status and result updates for an AnalysisRequest."""
        # Delegate to the imported resolver function
        async for update in analysis_request_updates(
            self, info=info, request_id=request_id
        ):
            yield update


# --- Schema Definition ---
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    # Ensure all custom types used (directly or indirectly) are listed here
    # if not automatically discovered by Strawberry.
    types=[
        # Auth/User types
        User,
        AuthPayload,
        RegisterPayload,
        ShopifyOAuthStartPayload,
        CompleteShopifyOAuthPayload,  # Add new payload
        # Preferences types
        UserPreferences,
        UserPreferencesPayload,
        UserPreferencesUpdateInput,
        # HITL types
        ProposedActionConnection,
        UserApproveActionPayload,
        UserRejectActionPayload,
        # Analysis types
        AnalysisRequestGQL,
        SubmitAnalysisRequestPayload,
        AnalysisRequestConnection,
        AnalysisResult,
        Visualization,
        VisualizationType,
        # Shopify types
        ShopifyStore,  # Added ShopifyStore type
        # Other common types
        LinkedAccount,
        # Include other GQL types used explicitly or implicitly if needed
    ],
    # Enable Relay support
    enable_federation_v2=False,  # Assuming not using federation
    # Add extensions if needed (e.g., for performance monitoring)
    extensions=[
        CustomErrorHandler,  # Add our custom error handler
        # Add other extensions like performance monitoring here if needed
    ],
)

# --- TODO ---
# 1. [Done(Partial)] Moved register, login, start_shopify_oauth mutations to REST router.
# 2. [Done] Moved HITL types/resolvers to separate files.
# 3. [Done] Moved Analysis Request types/resolvers to separate files.
# 4. [Done] Implemented 'me' query.
# 5. [Done] Implemented 'updatePreferences' mutation.
# 6. [Done] Implemented Subscriptions (analysisRequestUpdates) via Redis PubSub.
# 7. [Done] Implement 'completeShopifyOAuth' mutation.
# 8. [Done] Added basic WebSocket support via GraphQLRouter.
# 9. [Done] Defined missing GQL type (ShopifyStore).
# 10. [Done] Implemented Relay Node interface and base pagination structure.
#    - [Done] Verified pagination logic within list_* resolvers.
# 11. [Next] Configure and verify WebSocket deployment (external infra).
# 12. [Done] Implemented CustomErrorHandler extension (app/graphql/extensions/error_handler.py).
# 13. [Next] Write tests for GQL endpoints and WebSocket subscriptions.
