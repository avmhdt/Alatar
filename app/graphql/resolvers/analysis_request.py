import logging
import uuid
import asyncio

import strawberry
from strawberry.types import Info
from sqlalchemy.ext.asyncio import AsyncSession

# Import exceptions for error handling
from graphql import GraphQLError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id_from_info, get_required_user_id_from_info, get_current_user_id_context
from app.core.exceptions import PermissionDeniedError, ValidationError

# Assuming this exists
from app import crud

# Import cursor utils and Node type
# Import relay helpers for global ID decoding
from app.graphql.relay import from_global_id, to_global_id
from app.graphql.types import UserError

# Import GQL types (will be defined in types/analysis_request.py)
from app.graphql.types.analysis_request import (
    AnalysisRequest as AnalysisRequestGQL,
)
from app.graphql.types.analysis_request import (
    AnalysisRequestConnection,
    AnalysisRequestEdge,
    PageInfo,  # Import PageInfo
    SubmitAnalysisRequestInput,
    SubmitAnalysisRequestPayload,
)

# Update import for utils
from app.graphql.utils import decode_cursor, encode_cursor
from app.models import AnalysisRequest as AnalysisRequestModel
from app.models.analysis_request import AnalysisRequestStatus
from app.schemas.analysis_request import AnalysisRequestCreate
from app.services.analysis_queue_service import (
    AnalysisQueueService,
)

# Assume QueueClient is available (e.g., via dependency injection or global instance)
# Placeholder import - replace with actual access method
from app.services.queue_client import QueueClient, RABBITMQ_URL
from app.agents.constants import QUEUE_C1_INPUT # Renamed from INPUT_QUEUE

logger = logging.getLogger(__name__)

# --- Queue Client Initialization (Placeholder - same as action_service) ---
_queue_client_instance = QueueClient(RABBITMQ_URL)
async def get_queue_client():
    await _queue_client_instance.connect()
    return _queue_client_instance


def map_analysis_request_model_to_gql(
    request: AnalysisRequestModel,
) -> AnalysisRequestGQL:
    """Maps the SQLAlchemy model to the Strawberry GQL type."""
    # Implementation will depend on the final AnalysisRequestGQL definition
    return AnalysisRequestGQL(
        id=strawberry.ID(f"AnalysisRequest:{request.id}"),  # Example Global ID
        prompt=request.prompt,
        status=AnalysisRequestStatus(request.status).name,  # Map enum to string name
        result_summary=request.result_summary,
        # result_data=request.result_data, # Needs serialization handling if exposed
        error_message=request.error_message,
        created_at=request.created_at,
        updated_at=request.updated_at,
        completed_at=request.completed_at,
        user_id=strawberry.ID(f"User:{request.user_id}"),  # Example Global ID
        # Add other fields like proposed_actions if needed
    )


# --- submitAnalysisRequest Mutation --- #
async def submit_analysis_request(
    info: Info,
    input: SubmitAnalysisRequestInput,
) -> SubmitAnalysisRequestPayload:
    """Submits a new analysis request and queues it for processing."""
    db: AsyncSession = info.context.db
    user_id: uuid.UUID | None = await get_current_user_id_from_info(info)
    user_errors: list[UserError] = []

    if not user_id:
        # This is an authentication error, better handled by auth layer or extension
        # But if it reaches here, return a user error
        user_errors.append(
            UserError(message="Authentication required.", code="AUTH_REQUIRED")
        )
        return SubmitAnalysisRequestPayload(
            analysis_request=None, userErrors=user_errors
        )

    # --- Input Validation Example ---
    if not input.prompt or len(input.prompt.strip()) < 5:
        user_errors.append(
            UserError(
                field="prompt",
                message="Prompt must be at least 5 characters long.",
                code="VALIDATION_ERROR",
            )
        )

    # --- Validate linked_account_id ---
    linked_account_pk: uuid.UUID | None = None
    shop_domain: str | None = None
    linked_account = None
    try:
        type_name, linked_account_pk_str = from_global_id(input.linked_account_id)
        if type_name != 'LinkedAccount': # Ensure it's the right type
            raise ValueError("Invalid ID type for linked account.")
        linked_account_pk = uuid.UUID(linked_account_pk_str)

        # Fetch the account using CRUD to verify existence and ownership
        linked_account = crud.get_linked_account(db=db, account_id=linked_account_pk)
        if not linked_account:
            raise ValueError("Linked account not found.")
        if linked_account.user_id != user_id:
            # Raise permission error instead of validation error
            raise PermissionDeniedError("Linked account does not belong to the current user.")
        # Extract shop_domain (account_name)
        shop_domain = linked_account.account_name
        if not shop_domain:
            # This shouldn't happen for Shopify accounts, but check defensively
            raise ValueError("Shop domain (account name) missing from linked account.")

    except ValueError as e:
        user_errors.append(
            UserError(
                field="linkedAccountId", message=str(e), code="VALIDATION_ERROR"
            )
        )
    except PermissionDeniedError as e:
        # We could return a UserError or re-raise for a higher-level handler
        user_errors.append(
            UserError(
                field="linkedAccountId", message=str(e), code="PERMISSION_DENIED"
            )
        )
    except Exception as e:
        # Catch unexpected errors during validation
        logger.error(f"Unexpected error validating linked account {input.linked_account_id}: {e}", exc_info=True)
        user_errors.append(
            UserError(
                field="linkedAccountId", message="Error validating linked account.", code="INTERNAL_ERROR"
            )
        )

    if user_errors:
        # Return validation errors without proceeding
        return SubmitAnalysisRequestPayload(
            analysis_request=None, userErrors=user_errors
        )

    # --- Create and Queue Request --- (Wrap in try/except for unexpected errors)
    try:
        # Create the AnalysisRequest in the database
        analysis_req_in = AnalysisRequestCreate(
            prompt=input.prompt.strip(),
            user_id=user_id,
            linked_account_id=linked_account_pk, # Pass the validated UUID
            # status defaults to PENDING in schema/model
        )
        created_request: AnalysisRequestModel = crud.analysis_request.create(
            db=db, obj_in=analysis_req_in
        )
        db.commit()
        db.refresh(created_request)
        logger.info(f"Created AnalysisRequest {created_request.id} for user {user_id}")

        # Queue the request for background processing (Example)
        queue_service = AnalysisQueueService()
        await queue_service.enqueue_request(
            analysis_request_id=created_request.id,
            user_id=user_id,
            prompt=created_request.prompt,
            shop_domain=shop_domain, # Pass the retrieved shop domain
        )
        logger.info(f"Enqueued AnalysisRequest {created_request.id} for processing")

        # Convert DB model to GQL type
        gql_request = AnalysisRequestGQL.from_orm(created_request)

        return SubmitAnalysisRequestPayload(
            analysis_request=gql_request,
            userErrors=[],  # Success
        )

    except Exception as e:
        # Catch unexpected errors during creation/queuing
        logger.error(
            f"Failed to submit analysis request for user {user_id}: {e}",
            exc_info=True,
            extra={"props": {"user_id": str(user_id), "prompt": input.prompt}},
        )
        db.rollback()  # Rollback DB changes on error
        # Option 1: Let CustomErrorHandler catch and format as INTERNAL_SERVER_ERROR
        # raise e # Re-raise the exception

        # Option 2: Return a generic user error in the payload
        user_errors.append(
            UserError(
                message="Failed to submit request due to an internal error.",
                code="SUBMISSION_FAILED",
            )
        )
        return SubmitAnalysisRequestPayload(
            analysis_request=None, userErrors=user_errors
        )


# --- analysisRequest Query --- #
async def get_analysis_request(
    info: Info, id: strawberry.ID
) -> AnalysisRequestGQL | None:
    """Resolver to fetch a single analysis request by its global ID."""
    user_id = get_current_user_id_context()
    if not user_id:
        return None # Authentication required

    db: AsyncSession = info.context.db
    try:
        type_name, db_id_str = from_global_id(id)
        if type_name != "AnalysisRequest":
            return None # Invalid ID type
        db_id = uuid.UUID(db_id_str)
    except (ValueError, TypeError):
        return None # Invalid ID format

    # Use async CRUD function - assumes analysis_request CRUD object has an async 'aget_by_owner'
    # Let's assume crud.analysis_request.aget handles owner check implicitly via RLS
    # request_db = await crud.analysis_request.get_by_owner(db=db, id=db_id, owner_id=user_id)
    request_db = await crud.analysis_request.aget(db=db, id=db_id)

    if request_db:
        return AnalysisRequestGQL.from_orm(request_db)
    return None


# --- listAnalysisRequests Query --- #
async def list_analysis_requests(
    info: Info,
    first: int = 10,
    after: str | None = None, # Opaque cursor
) -> AnalysisRequestConnection:
    """Resolver to list analysis requests for the current user."""
    user_id = get_current_user_id_context()
    if not user_id:
        # Return empty connection or raise error?
        # Following Relay spec, usually return empty connection for unauthorized
        return AnalysisRequestConnection(page_info=PageInfo(has_next_page=False, has_previous_page=False), edges=[])

    db: AsyncSession = info.context.db

    # Use the async paginated fetcher from the CRUD class
    # Need to handle cursor decoding appropriately if it contains more than just created_at
    cursor_data = None
    if after:
        # Assuming cursor is just the created_at timestamp for simplicity here
        # Real Relay often uses compound cursors (timestamp, id)
        try:
            # Decode cursor if needed (depends on how it's encoded)
            # For now, assume it's directly usable if crud method expects it.
            # If it's base64 encoded timestamp: after_str = decode_cursor(after)
            # cursor_data = (datetime.fromisoformat(after_str).replace(tzinfo=UTC), None) # Example if cursor was just timestamp
            pass # CRUD method handles opaque cursor if designed for it
        except Exception:
            # Handle invalid cursor
            # For now, ignore invalid cursor and fetch from beginning
            pass

    # Call the async CRUD method
    # Ensure get_multi_by_owner_paginated handles async and cursor logic
    requests_db = await crud.analysis_request.get_multi_by_owner_paginated_async(
        db=db,
        owner_id=user_id,
        limit=first + 1, # Fetch one extra to check for next page
        cursor_data=cursor_data, # Pass decoded cursor tuple if needed
        # cursor_str=after # Or pass opaque cursor if crud method decodes it
    )

    has_next_page = len(requests_db) > first
    items_to_return = requests_db[:first]

    edges = []
    for req in items_to_return:
        # Generate cursor based on the item (e.g., created_at and id)
        # Needs consistent generation based on sorting key(s)
        cursor_val = to_global_id("AnalysisRequestCursor", f"{req.created_at.isoformat()}_{req.id}")
        edges.append(
            Edge(
                node=AnalysisRequestGQL.from_orm(req),
                cursor=cursor_val
            )
        )

    return AnalysisRequestConnection(
        page_info=PageInfo(
            has_next_page=has_next_page,
            has_previous_page=after is not None, # Basic check
            start_cursor=edges[0].cursor if edges else None,
            end_cursor=edges[-1].cursor if edges else None,
        ),
        edges=edges,
    )


# Add analysisRequest and listAnalysisRequests query resolvers here...
