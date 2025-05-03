import logging
import uuid

import strawberry

# Import exceptions for error handling
from graphql import GraphQLError
from sqlalchemy.orm import Session
from strawberry.types import Info

from app.auth.dependencies import get_current_user_id_from_info  # Get user ID
from app.core.exceptions import PermissionDeniedError

# Assuming this exists
from app.crud.analysis_request import analysis_request as crud_analysis_request

# Import cursor utils and Node type
# Import relay helpers for global ID decoding
from app.graphql.relay import from_global_id
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

logger = logging.getLogger(__name__)


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
    db: Session = info.context.db
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

    # Add other validation logic here...
    # E.g., check if linked account ID is valid and belongs to the user
    # try:
    #     type_name, linked_account_pk = from_global_id(input.linked_account_id)
    #     if type_name != 'LinkedAccount': # Or whatever type name you use
    #         raise ValueError("Invalid ID type")
    #     # TODO: Check if linked_account_pk exists and belongs to user_id
    # except ValueError:
    #     user_errors.append(
    #         UserError(field="linkedAccountId", message="Invalid linked account ID format.", code="INVALID_ID")
    #     )

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
            # linked_account_id=linked_account_pk, # Use decoded PK if validation added
            # status defaults to PENDING in schema/model
        )
        created_request: AnalysisRequestModel = crud_analysis_request.create(
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
            # Pass other necessary info like shop_domain if needed by worker
            # shop_domain = ... # Fetch from linked account maybe?
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
    db: Session = info.context.db
    # Use await here as get_current_user_id_from_info is async
    user_id: uuid.UUID | None = await get_current_user_id_from_info(info)

    if not user_id:
        raise PermissionDeniedError("Authentication required.")

    try:
        type_name, pk_str = from_global_id(id)
        if type_name != "AnalysisRequest":
            raise ValueError("Invalid ID type for analysis request.")
        request_uuid = uuid.UUID(pk_str)
    except ValueError as e:
        logger.warning(f"Invalid analysis request global ID format: {id}, Error: {e}")
        raise GraphQLError(f"Invalid ID format: {id}")

    # Rely on RLS being set via context
    request_db = crud_analysis_request.get(db=db, id=request_uuid)

    if not request_db:
        return None

    # Assuming GQL type has from_orm or similar mapping
    return AnalysisRequestGQL.from_orm(request_db)


# --- listAnalysisRequests Query --- #
async def list_analysis_requests(
    info: Info,
    first: int = 10,
    after: str | None = None,  # After cursor
    # Add before, last for bi-directional pagination if needed
) -> AnalysisRequestConnection:
    db: Session = info.context.db
    # Use await here as get_current_user_id_from_info is async
    user_id: uuid.UUID | None = await get_current_user_id_from_info(info)

    if not user_id:
        raise PermissionDeniedError(
            "Authentication required to list analysis requests."
        )

    if first < 0:
        raise GraphQLError("Argument 'first' must be a non-negative integer.")

    limit = first + 1  # Fetch one extra to check for next page
    primary_sort_column = "created_at"  # Column used for cursor/ordering
    secondary_sort_column = "id"  # Tie-breaker column
    descending = True  # Assuming newest first

    # Decode the cursor
    cursor_data = decode_cursor(after) if after else None
    if after and cursor_data is None:
        raise GraphQLError(f"Invalid cursor format: {after}")

    # Fetch paginated results from CRUD layer
    try:
        requests_db = crud_analysis_request.get_multi_by_owner_paginated(
            db=db,
            owner_id=user_id,
            limit=limit,
            cursor_data=cursor_data,  # Pass decoded tuple
            primary_sort_column=primary_sort_column,
            secondary_sort_column=secondary_sort_column,
            descending=descending,
        )
    except Exception as e:
        logger.error(
            f"Database error during pagination for user {user_id}: {e}", exc_info=True
        )
        raise GraphQLError("Failed to retrieve analysis requests.")

    has_next_page = len(requests_db) > first
    items_to_return = requests_db[:first]

    edges = [
        AnalysisRequestEdge(
            node=AnalysisRequestGQL.from_orm(req),
            # Encode primary and secondary sort keys into the cursor
            cursor=encode_cursor(
                primary_value=getattr(req, primary_sort_column),
                secondary_value=getattr(req, secondary_sort_column),
            ),
        )
        for req in items_to_return
    ]

    page_info = PageInfo(
        hasNextPage=has_next_page,
        hasPreviousPage=after is not None,
        startCursor=edges[0].cursor if edges else None,
        endCursor=edges[-1].cursor if edges else None,
    )

    return AnalysisRequestConnection(edges=edges, pageInfo=page_info)


# Add analysisRequest and listAnalysisRequests query resolvers here...
