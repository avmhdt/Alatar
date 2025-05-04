# This file will contain the resolver logic for Queries, Mutations, and Subscriptions.
# We will import necessary services, models, and types here as we build them.

import asyncio
import logging  # Added
import uuid  # Added
from collections.abc import AsyncGenerator
from datetime import timedelta  # Added datetime

import strawberry
from fastapi import HTTPException  # Added HTTPException
from sqlalchemy.exc import IntegrityError  # For catching DB errors
from sqlalchemy.orm import Session
from strawberry.types import Info as StrawberryInfo  # Keep alias for clarity if needed

from app import schemas
from app.auth import service as auth_service
from app.auth.dependencies import get_optional_user_id_from_token as get_current_user_id  # Updated import
from app.models.analysis_request import AnalysisRequest as AnalysisRequestModel  # Added
from app.models.proposed_action import ProposedAction as ProposedActionModel  # Added
from app.models.user import User as UserModel  # Avoid name clash
from app.models.user_preferences import (
    UserPreferences as UserPreferencesModel,
)

# Added model
# Import services
from app.services import (
    action_service,  # Added
    analysis_service,  # Added
    pubsub_service,  # Added PubSub service
)
from app.services.queue_client import QUEUE_C1_INPUT, QueueClient  # Added QueueClient

from app.graphql.errors import map_exception_to_user_errors  # For handling unexpected errors

from app.graphql.types.user_error import *
from app.graphql.types.user import *
from app.graphql.types.analysis_request import *
from app.graphql.types.proposed_action import *
from app.graphql.types.common import *
from app.graphql.types.auth import *
from app.graphql.types.shopify import *


logger = logging.getLogger(__name__)  # Added logger

# Placeholder types (Define actual types in types.py)
# @strawberry.type # Removed placeholder
# class AnalysisRequest:
#     id: strawberry.ID
#     status: str  # Consider Enum later
#     prompt: str


# @strawberry.type # Removed placeholder
# class ProposedAction:
#     id: strawberry.ID
#     status: str  # Consider Enum later
#     description: str


# --- Helper function for auth ---
async def _get_auth_context(info: StrawberryInfo) -> uuid.UUID:
    """Extracts user ID from context, raising appropriate GQL errors."""
    db: Session = info.context["db"]
    request = info.context.get("request")  # Use .get for safer access
    if not request:
        # This should ideally not happen if context is set up correctly
        raise AuthorizationError(message="Request context not found.")
    try:
        user_id: uuid.UUID = await get_current_user_id(request=request)
        return user_id
    except HTTPException as e:
        if e.status_code == 401:
            raise AuthenticationError(message=e.detail)
        elif e.status_code == 403:
            raise AuthorizationError(message=e.detail)
        else:
            # Re-raise other HTTP errors as InternalServerErrors or specific GQL errors
            raise InternalServerError(
                message=f"Authentication/Authorization HTTP Error: {e.detail}"
            )
    except Exception as e:
        # Log unexpected errors during auth check
        logger.exception(
            "Unexpected error getting current user ID",
            extra={"props": {"error": str(e)}},
        )
        raise InternalServerError(
            message="An internal error occurred during authentication."
        )


# --- Helper function for model mapping ---
def map_analysis_request_model_to_gql(model: AnalysisRequestModel) -> AnalysisRequest:
    """Maps SQLAlchemy AnalysisRequest model to Strawberry GQL type."""
    # Note: Add more fields as needed based on GQL type definition
    return AnalysisRequest(
        id=model.id,
        prompt=model.prompt,
        status=model.status,  # Enum should map directly if registered
        result_summary=model.result_summary,
        result_data=model.result_data,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def map_dict_to_analysis_request_gql(data: dict) -> AnalysisRequest:
    """Maps a dictionary (e.g., from pubsub) to Strawberry AnalysisRequest GQL type."""
    # Basic mapping, assuming dict keys match model attributes used in GQL type
    # Add error handling and default values as needed
    return AnalysisRequest(
        id=data.get("id"),
        prompt=data.get("prompt"),
        status=data.get(
            "status"
        ),  # Assumes status is already the correct Enum member name/value
        result_summary=data.get("result_summary"),
        result_data=data.get("result_data"),
        error_message=data.get("error_message"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        completed_at=data.get("completed_at"),
    )


def map_proposed_action_model_to_gql(model: ProposedActionModel) -> ProposedAction:
    """Maps SQLAlchemy ProposedAction model to Strawberry GQL type."""
    # Note: Add more fields as needed based on GQL type definition
    return ProposedAction(
        id=model.id,
        analysis_request_id=model.analysis_request_id,
        linked_account_id=model.linked_account_id,
        action_type=model.action_type,
        description=model.description,
        parameters=model.parameters,
        status=model.status,  # Enum should map directly
        execution_logs=model.execution_logs,
        created_at=model.created_at,
        updated_at=model.updated_at,
        approved_at=model.approved_at,
        executed_at=model.executed_at,
    )


@strawberry.type
class Query:
    @strawberry.field
    async def me(self, info: StrawberryInfo) -> User | None:
        """Get the current authenticated user."""
        log_props = {}
        try:
            user_id = await _get_auth_context(info)
            log_props["user_id"] = str(user_id)
            logger.info("Executing 'me' query", extra={"props": log_props})
            db: Session = info.context["db"]
            user_model = db.query(UserModel).filter(UserModel.id == user_id).first()
            if user_model:
                pydantic_user = schemas.User.from_orm(user_model)
                return User.from_pydantic(pydantic_user)
            else:
                logger.error(
                    "Authenticated user not found in database.",
                    extra={"props": log_props},
                )
                raise NotFoundError(message="Authenticated user not found in database.")
        except (AuthenticationError, AuthorizationError, NotFoundError) as e:
            logger.warning(
                f"Auth/Not Found error in 'me': {e.message}", extra={"props": log_props}
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error in 'me' resolver", extra={"props": log_props}
            )
            return None  # Or raise, depending on desired behavior for unexpected errors

    @strawberry.field
    async def myPreferences(self, info: StrawberryInfo) -> UserPreferences | None:
        """Get the current authenticated user's preferences."""
        log_props = {}
        db: Session = info.context["db"]
        try:
            user_id = await _get_auth_context(info)
            log_props["user_id"] = str(user_id)
            logger.info("Executing 'myPreferences' query", extra={"props": log_props})
            prefs = (
                db.query(UserPreferencesModel)
                .filter(UserPreferencesModel.user_id == user_id)
                .first()
            )
            if not prefs:
                logger.info(
                    "No preferences found for user.", extra={"props": log_props}
                )
                return None
            pydantic_prefs = schemas.UserPreferences.from_orm(prefs)
            return UserPreferences.from_pydantic(pydantic_prefs)
        except (AuthenticationError, AuthorizationError) as e:
            logger.warning(
                f"Auth error getting preferences: {e.message}",
                extra={"props": log_props},
            )
            # Depending on schema nullability, might raise or return None
            return None
        except Exception:
            logger.exception(
                "Unexpected error getting preferences", extra={"props": log_props}
            )
            # Optionally return InternalServerError via UserError union if needed
            return None

    @strawberry.field
    async def listAnalysisRequests(
        self, info: StrawberryInfo, first: int = 10, after: str | None = None
    ) -> AnalysisRequestConnection:
        """List analysis requests for the current user."""
        log_props = {"limit": first, "after_cursor": after}
        logger.info(f"Resolver 'listAnalysisRequests' called (first={first}, after={after})")
        db: Session = info.context["db"]
        edges: list[Edge[AnalysisRequest]] = []
        page_info = PageInfo(has_next_page=False, has_previous_page=False)  # Defaults

        try:
            user_id = await _get_auth_context(info)
            log_props["user_id"] = str(user_id)
            logger.info(
                "Executing 'listAnalysisRequests' query", extra={"props": log_props}
            )
            # Call the updated service
            request_models, has_next = await analysis_service.list_analysis_requests(
                db=db, user_id=user_id, limit=first, cursor=after
            )

            # Create edges and cursors
            for model in request_models:
                gql_node = map_analysis_request_model_to_gql(model)
                # Define cursor based on ordering (e.g., created_at)
                # Ensure created_at is consistently timezone-aware if used
                cursor_value = (
                    model.created_at.isoformat() if model.created_at else str(model.id)
                )
                edges.append(Edge(node=gql_node, cursor=encode_cursor(cursor_value)))

            # Set PageInfo
            page_info.has_next_page = has_next
            # has_previous_page is harder with forward-only cursors
            page_info.has_previous_page = bool(
                after
            )  # Simple check if 'after' was provided
            page_info.start_cursor = edges[0].cursor if edges else None
            page_info.end_cursor = edges[-1].cursor if edges else None

        except (AuthenticationError, AuthorizationError, InputValidationError) as e:
            # Re-raise auth/input errors if schema requires non-null connection
            # Or handle gracefully depending on schema design
            logger.warning(
                f"Error in listAnalysisRequests: {e.message}",
                extra={"props": log_props},
            )
            # Return empty connection on error for now
        except NotImplementedError:
            logger.error(
                "list_analysis_requests service not implemented",
                extra={"props": log_props},
            )
            # Return empty connection
        except Exception:
            logger.exception(
                "Unexpected error in listAnalysisRequests", extra={"props": log_props}
            )
            # Log error
            # Return empty connection on unexpected error

        return AnalysisRequestConnection(page_info=page_info, edges=edges)

    @strawberry.field
    async def listProposedActions(
        self, info: StrawberryInfo, first: int = 10, after: str | None = None
    ) -> ProposedActionConnection:
        """List proposed actions for the current user."""
        log_props = {"limit": first, "after_cursor": after}
        logger.info(f"Resolver 'listProposedActions' called (first={first}, after={after})")
        db: Session = info.context["db"]
        edges: list[Edge[ProposedAction]] = []
        page_info = PageInfo(has_next_page=False, has_previous_page=False)

        try:
            user_id = await _get_auth_context(info)
            log_props["user_id"] = str(user_id)
            logger.info(
                "Executing 'listProposedActions' query", extra={"props": log_props}
            )
            action_models, has_next = await action_service.list_pending_actions(
                db=db, user_id=user_id, limit=first, cursor=after
            )

            for model in action_models:
                gql_node = map_proposed_action_model_to_gql(model)
                cursor_value = (
                    model.created_at.isoformat() if model.created_at else str(model.id)
                )
                edges.append(Edge(node=gql_node, cursor=encode_cursor(cursor_value)))

            page_info.has_next_page = has_next
            page_info.has_previous_page = bool(after)
            page_info.start_cursor = edges[0].cursor if edges else None
            page_info.end_cursor = edges[-1].cursor if edges else None

        except (AuthenticationError, AuthorizationError, InputValidationError) as e:
            logger.warning(
                f"Error in listProposedActions: {e.message}", extra={"props": log_props}
            )
        except NotImplementedError:
            logger.error(
                "list_pending_actions service not implemented",
                extra={"props": log_props},
            )
        except Exception:
            logger.exception(
                "Unexpected error in listProposedActions", extra={"props": log_props}
            )

        return ProposedActionConnection(page_info=page_info, edges=edges)

    # Add other query resolvers as needed


@strawberry.type
class Mutation:
    # --- Auth Mutations ---

    @strawberry.mutation
    def register(
        self, input: UserRegisterInput, info: StrawberryInfo
    ) -> RegisterPayload:
        log_props = {"email": input.email}  # Mask email if needed via filter
        logger.info("Executing 'register' mutation", extra={"props": log_props})
        db: Session = info.context["db"]
        existing_user = auth_service.get_user_by_email(db, email=input.email)
        if existing_user:
            logger.warning(
                "Registration failed: Email already registered",
                extra={"props": log_props},
            )
            return RegisterPayload(
                userErrors=[
                    InputValidationError(
                        field="email", message="Email already registered."
                    )
                ]
            )

        try:
            user_data = schemas.UserCreate(email=input.email, password=input.password)
            new_user = auth_service.create_user(db=db, user_data=user_data)
            log_props["user_id"] = str(new_user.id)
            # Also create default preferences on registration
            default_prefs = UserPreferencesModel(user_id=new_user.id)
            db.add(default_prefs)
            db.commit()  # Commit user and prefs
            db.refresh(new_user)
            pydantic_user = schemas.User.from_orm(new_user)
            strawberry_user = User.from_pydantic(pydantic_user)
            logger.info("User registered successfully", extra={"props": log_props})
            return RegisterPayload(user=strawberry_user)
        except Exception as e:
            logger.exception("Error during registration", extra={"props": log_props})
            user_errors = map_exception_to_user_errors(e)
            return RegisterPayload(userErrors=user_errors)

    @strawberry.mutation
    def login(self, input: UserLoginInput, info: StrawberryInfo) -> AuthPayload:
        log_props = {"email": input.email}  # Mask email if needed
        logger.info("Executing 'login' mutation", extra={"props": log_props})
        db: Session = info.context["db"]
        user = auth_service.authenticate_user(
            db, email=input.email, password=input.password
        )

        if not user:
            logger.warning(
                "Login failed: Invalid credentials", extra={"props": log_props}
            )
            return AuthPayload(
                userErrors=[
                    AuthenticationError(
                        field="credentials", message="Invalid email or password."
                    )
                ]
            )

        try:
            access_token_expires = timedelta(
                minutes=auth_service.ACCESS_TOKEN_EXPIRE_MINUTES
            )
            access_token = auth_service.create_access_token(
                data={"sub": str(user.id)}, expires_delta=access_token_expires
            )

            pydantic_user = schemas.User.from_orm(user)
            strawberry_user = User.from_pydantic(pydantic_user)

            return AuthPayload(token=access_token, user=strawberry_user)
        except Exception as e:
            logger.error(f"Error during login token creation: {e}")  # Log error
            user_errors = map_exception_to_user_errors(e)
            return AuthPayload(userErrors=user_errors)

    @strawberry.mutation
    async def start_shopify_oauth(
        self,
        input: StartShopifyOAuthInput,
        info: StrawberryInfo,
    ) -> ShopifyOAuthStartPayload:
        """Generates the URL to start the Shopify OAuth flow."""
        # db: Session = info.context["db"] # Removed unused
        # request = info.context["request"] # Removed unused

        try:
            # Use helper for consistency
            # user_id = await get_current_user_id_from_context(info) # Replaced below
            await _get_auth_context(
                info
            )  # Call auth helper to ensure user is authenticated

            shop_domain = input.shop_domain.strip()
            if not shop_domain or not shop_domain.endswith(".myshopify.com"):
                return ShopifyOAuthStartPayload(
                    userErrors=[
                        InputValidationError(
                            field="shop_domain",
                            message="Invalid shop domain format. Must end with .myshopify.com",
                        )
                    ]
                )

            auth_url, state = auth_service.generate_shopify_auth_url(
                shop_domain=shop_domain
            )
            return ShopifyOAuthStartPayload(authorization_url=auth_url, state=state)

        except (AuthenticationError, AuthorizationError, InputValidationError) as e:
            # Handle expected errors from helper or validation
            return ShopifyOAuthStartPayload(userErrors=[e])
        except ValueError as e:
            # Handle configuration errors from service
            logger.error(f"ValueError during Shopify OAuth start: {e}")
            return ShopifyOAuthStartPayload(
                userErrors=[
                    InputValidationError(
                        field="config", message=f"Server configuration error: {e}"
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Unexpected error during Shopify OAuth start: {e}")  # Log error
            user_errors = map_exception_to_user_errors(e)
            return ShopifyOAuthStartPayload(userErrors=user_errors)

    # --- User Preferences Mutation ---
    @strawberry.mutation
    async def updatePreferences(
        self, info: StrawberryInfo, input: UserPreferencesUpdateInput
    ) -> UserPreferencesPayload:
        """Update the current authenticated user's preferences."""
        db: Session = info.context["db"]
        try:
            # user_id = await get_current_user_id_from_context(info)
            user_id = await _get_auth_context(info)  # Use defined helper
            prefs = (
                db.query(UserPreferencesModel)
                .filter(UserPreferencesModel.user_id == user_id)
                .first()
            )

            if not prefs:
                # Create preferences if they don't exist
                prefs = UserPreferencesModel(user_id=user_id)
                db.add(prefs)

            # Update fields from input if they are provided (not None)
            updated = False
            update_data = input.to_pydantic()
            for field, value in update_data.model_dump(exclude_unset=True).items():
                if hasattr(prefs, field):
                    setattr(prefs, field, value)
                    updated = True

            if updated:
                db.commit()
                db.refresh(prefs)
                logger.info(f"Updated preferences for user {user_id}")
            else:
                logger.info(f"No preference fields provided to update for user {user_id}")

            pydantic_prefs = schemas.UserPreferences.from_orm(prefs)
            return UserPreferencesPayload(
                preferences=UserPreferences.from_pydantic(pydantic_prefs)
            )

        except (AuthenticationError, AuthorizationError) as e:
            return UserPreferencesPayload(userErrors=[e])
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Database integrity error updating preferences: {e}")
            return UserPreferencesPayload(
                userErrors=[
                    InternalServerError(message="Database error saving preferences.")
                ]
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Unexpected error updating preferences: {e}")
            user_errors = map_exception_to_user_errors(e)
            return UserPreferencesPayload(userErrors=user_errors)

    # --- Analysis/Action Mutations ---

    @strawberry.mutation
    async def submitAnalysisRequest(
        self, info: StrawberryInfo, prompt: str
    ) -> SubmitAnalysisRequestPayload:
        """Submit a new analysis request."""
        logger.info(
            f"Mutation 'submitAnalysisRequest' called with prompt: '{prompt[:50]}...'"
        )
        db: Session = info.context["db"]
        # Assume QueueClient is injected into context similar to db
        queue_client: QueueClient | None = info.context.get("queue_client")

        if not queue_client:
            # Log this critical configuration error
            logger.error("ERROR: QueueClient not found in Strawberry context!")
            # Return an error payload
            return SubmitAnalysisRequestPayload(
                userErrors=[
                    InternalServerError(
                        message="Server configuration error: Queue service unavailable."
                    )
                ]
            )

        try:
            # user_id = await get_current_user_id_from_context(info)
            user_id = await _get_auth_context(info)  # Use defined helper
            # Call service to create the request (should set status to 'pending')
            result = await analysis_service.submit_new_request(
                db=db, user_id=user_id, prompt=prompt
            )

            if isinstance(result, str):  # Service returned an error message
                return SubmitAnalysisRequestPayload(
                    userErrors=[InternalServerError(message=result)]
                )
            elif isinstance(result, AnalysisRequestModel):
                # Map result to GQL type
                gql_request = map_analysis_request_model_to_gql(result)

                # --- Publish to RabbitMQ ---
                try:
                    message_body = {
                        "user_id": str(user_id),
                        "analysis_request_id": str(result.id),
                        "prompt": prompt,
                        # Add other relevant info if needed by worker
                    }
                    await queue_client.publish_message(
                        queue_name=QUEUE_C1_INPUT, message_body=message_body
                    )
                    logger.info(
                        f"Successfully published task for AnalysisRequest {result.id} to queue {QUEUE_C1_INPUT}"
                    )
                except Exception as pub_err:
                    # Log the publishing error
                    logger.error(
                        f"ERROR: Failed to publish task for AnalysisRequest {result.id} to queue {QUEUE_C1_INPUT}: {pub_err}"
                    )
                    # Decide how to handle:
                    # 1. Still return success (request created, but won't process)?
                    # 2. Return an error payload indicating processing might be delayed/failed?
                    # 3. Attempt to update request status to 'failed_to_queue'?
                    # For now, return success but include an error message
                    # Note: The client won't see this specific error unless we add it to userErrors
                    # Consider adding a specific UserError type for queueing issues if needed
                    return SubmitAnalysisRequestPayload(
                        analysis_request=gql_request,
                        userErrors=[
                            InternalServerError(
                                message="Analysis request submitted, but failed to queue for processing. Please contact support."
                            )
                        ],  # Example user-facing error
                    )
                # --- End Publish ---

                return SubmitAnalysisRequestPayload(analysis_request=gql_request)
            else:
                # Should not happen if service signature is correct
                logger.error(
                    f"ERROR: Unexpected return type from submit_new_request service: {type(result)}"
                )
                raise Exception(
                    "Unexpected return type from submit_new_request service"
                )

        except (AuthenticationError, AuthorizationError) as e:
            return SubmitAnalysisRequestPayload(userErrors=[e])
        except NotImplementedError:
            logger.error("submit_new_request service not implemented")
            return SubmitAnalysisRequestPayload(
                userErrors=[
                    InternalServerError(
                        message="Submit request feature not implemented."
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Unexpected error in submitAnalysisRequest: {e}")
            # Log error
            user_errors = map_exception_to_user_errors(e)
            return SubmitAnalysisRequestPayload(userErrors=user_errors)

    @strawberry.mutation
    async def userApprovesAction(
        self, info: StrawberryInfo, action_id: strawberry.ID
    ) -> ApproveActionPayload:
        """Approve a proposed action."""
        logger.info(f"Mutation 'userApprovesAction' called with action_id: {action_id}")
        db: Session = info.context["db"]
        try:
            # user_id = await get_current_user_id_from_context(info)
            user_id = await _get_auth_context(info)  # Use defined helper
            action_uuid = uuid.UUID(str(action_id))  # Convert GQL ID to UUID

            # Call service
            result = await action_service.approve_action(
                db=db, user_id=user_id, action_id=action_uuid
            )

            if isinstance(result, str):  # Service returned an error message
                # Determine if it was Not Found or other error
                if "not found" in result.lower():
                    return ApproveActionPayload(
                        userErrors=[NotFoundError(message=result, field="action_id")]
                    )
                else:
                    # Treat other service errors as Input/Validation or Internal errors
                    return ApproveActionPayload(
                        userErrors=[
                            InputValidationError(message=result, field="action_id")
                        ]
                    )  # Or InternalServerError
            elif isinstance(result, ProposedActionModel):
                gql_action = map_proposed_action_model_to_gql(result)
                return ApproveActionPayload(proposed_action=gql_action)
            else:
                raise Exception("Unexpected return type from approve_action service")

        except (AuthenticationError, AuthorizationError) as e:
            return ApproveActionPayload(userErrors=[e])
        except ValueError:  # Handle invalid UUID format for action_id
            return ApproveActionPayload(
                userErrors=[
                    InputValidationError(
                        message="Invalid action ID format.", field="action_id"
                    )
                ]
            )
        except NotImplementedError:
            logger.error("approve_action service not implemented")
            return ApproveActionPayload(
                userErrors=[
                    InternalServerError(
                        message="Approve action feature not implemented."
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Unexpected error in userApprovesAction: {e}")
            user_errors = map_exception_to_user_errors(e)
            return ApproveActionPayload(userErrors=user_errors)

    @strawberry.mutation
    async def userRejectsAction(
        self, info: StrawberryInfo, action_id: strawberry.ID
    ) -> RejectActionPayload:
        """Reject a proposed action."""
        logger.info(f"Mutation 'userRejectsAction' called with action_id: {action_id}")
        db: Session = info.context["db"]
        try:
            # user_id = await get_current_user_id_from_context(info)
            user_id = await _get_auth_context(info)  # Use defined helper
            action_uuid = uuid.UUID(str(action_id))

            # Call service
            result = await action_service.reject_action(
                db=db, user_id=user_id, action_id=action_uuid
            )

            if isinstance(result, str):
                if "not found" in result.lower():
                    return RejectActionPayload(
                        userErrors=[NotFoundError(message=result, field="action_id")]
                    )
                else:
                    return RejectActionPayload(
                        userErrors=[
                            InputValidationError(message=result, field="action_id")
                        ]
                    )  # Or InternalServerError
            elif isinstance(result, ProposedActionModel):
                gql_action = map_proposed_action_model_to_gql(result)
                return RejectActionPayload(proposed_action=gql_action)
            else:
                raise Exception("Unexpected return type from reject_action service")

        except (AuthenticationError, AuthorizationError) as e:
            return RejectActionPayload(userErrors=[e])
        except ValueError:  # Handle invalid UUID format
            return RejectActionPayload(
                userErrors=[
                    InputValidationError(
                        message="Invalid action ID format.", field="action_id"
                    )
                ]
            )
        except NotImplementedError:
            logger.error("reject_action service not implemented")
            return RejectActionPayload(
                userErrors=[
                    InternalServerError(
                        message="Reject action feature not implemented."
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Unexpected error in userRejectsAction: {e}")
            user_errors = map_exception_to_user_errors(e)
            return RejectActionPayload(userErrors=user_errors)


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def analysisRequestUpdates(
        self, info: StrawberryInfo, request_id: strawberry.ID
    ) -> AsyncGenerator[AnalysisRequest, None]:
        """Subscribe to updates for a specific analysis request."""
        logger.info(
            f"Subscription 'analysisRequestUpdates' requested for request_id: {request_id}"
        )
        db: Session = info.context["db"]
        try:
            # user_id = await get_current_user_id_from_context(info)
            user_id = await _get_auth_context(info)  # Use defined helper
            request_uuid = uuid.UUID(str(request_id))

            # 1. Validate ownership (using the existing service function)
            initial_request = await analysis_service.get_analysis_request_by_id(
                db=db, request_id=request_uuid, user_id=user_id
            )
            if not initial_request:
                # Important: Don't reveal if the ID exists but belongs to another user.
                # Raise an error or simply yield nothing / close the generator.
                # Raising might be better to signal the issue to the client immediately.
                logger.error(
                    f"Auth Error: User {user_id} cannot subscribe to request {request_uuid}"
                )
                # Option 1: Raise Auth error (might disconnect client)
                # raise AuthorizationError(message="Permission denied for this analysis request.")
                # Option 2: Yield nothing and return (client waits indefinitely)
                # return
                # Option 3: Yield an error object if the schema supports it (less common for subscriptions)
                # yield AnalysisRequestUpdateError(...)
                # For now, just log and return, effectively yielding nothing.
                return

            # 2. Subscribe using the pubsub service
            logger.info(f"User {user_id} subscribing to updates for {request_uuid}")
            async for message_data in pubsub_service.subscribe_to_analysis_request(
                request_uuid
            ):
                try:
                    # 3. Map message data to GQL type and yield
                    # Ensure the message_data contains necessary fields
                    # Might need to refetch the full object if message is partial
                    gql_update = map_dict_to_analysis_request_gql(message_data)
                    yield gql_update
                except Exception as e:
                    # Log mapping errors but keep the subscription alive if possible
                    logger.error(
                        f"Error mapping pubsub message to GQL type: {e} - Data: {message_data}"
                    )
                    continue  # Skip this message

        except (AuthenticationError, AuthorizationError, InputValidationError) as e:
            # Handle errors during initial auth/validation
            # Log and end the generator gracefully
            logger.error(f"Subscription setup error for request {request_id}: {e.message}")
            # Depending on client library, might need to yield an error or just return
            # yield SomeErrorType(...) # If schema supports
            return
        except ValueError:  # Handle invalid UUID format for request_id
            logger.error(f"Subscription error: Invalid request ID format '{request_id}'")
            # yield InputValidationError(...) # If schema supports
            return
        except NotImplementedError as e:
            logger.error(f"Subscription setup error: Service not implemented ({e})")
            # yield InternalServerError(...) # If schema supports
            return
        except asyncio.CancelledError:
            logger.error(f"Subscription cancelled by client for request {request_id}")
            # Let the cancellation propagate
            raise
        except Exception as e:
            # Log unexpected errors during subscription setup or stream
            logger.error(
                f"Unexpected error in analysisRequestUpdates subscription for {request_id}: {e}"
            )
            # Depending on severity, might yield an error or just return
            # yield InternalServerError(...) # If schema supports
            return
        finally:
            logger.info(f"Subscription ended for request {request_id}")

        # Placeholder implementation (remove after implementing above)
        # print(f"Subscription 'analysisRequestUpdates' requested (placeholder) for request_id: {request_id}")
        # yield AnalysisRequest(id=uuid.UUID(str(request_id)), status="PENDING", prompt="Initial Placeholder", created_at=datetime.now(), updated_at=datetime.now()) # Dummy data
        # import asyncio
        # await asyncio.sleep(5)
        # yield AnalysisRequest(id=uuid.UUID(str(request_id)), status="COMPLETED", prompt="Final Placeholder", created_at=datetime.now(), updated_at=datetime.now()) # Dummy data
        # pass
