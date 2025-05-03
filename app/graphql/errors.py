# This file will contain logic for mapping application exceptions to GraphQL UserErrors.

import logging

from fastapi import HTTPException
from strawberry.exceptions import GraphQLError

from .types import (  # -> ignore unused import for now
    ActionExecutionError,
    AnalysisTaskError,
    AuthenticationError,
    AuthorizationError,
    InputValidationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ShopifyAuthError,
    UserError,
)

logger = logging.getLogger(__name__)

# Placeholder for specific application exceptions if defined elsewhere
# from ...core.exceptions import ApplicationException, PermissionDeniedError, ResourceNotFoundError, ...


# --- Placeholder Imports for Custom Application Exceptions ---
# These should be defined in the respective service/core modules
class ShopifyAuthenticationError(Exception):
    pass


class ShopifyRateLimitError(Exception):
    pass


class ShopifyAPIError(Exception):
    pass


class ActionFailedError(Exception):
    pass


class AgentTaskFailedError(Exception):
    pass


# from app.services.shopify_client import ShopifyAuthenticationError, ShopifyRateLimitError, ShopifyAPIError
# from app.services.action_service import ActionFailedError
# from app.agents.exceptions import AgentTaskFailedError # Example path


def format_graphql_error(error: GraphQLError, context: dict) -> dict:
    """Format GraphQL errors, potentially mapping them to UserError types."""
    # TODO: Implement mapping logic based on original exception for richer error details
    # This function is less critical when mapping is done in resolvers/payloads
    # original_error = getattr(error, 'original_error', None)
    # if isinstance(original_error, ...):
    #     ...

    # Default formatting provided by Strawberry
    formatted_error = error.formatted
    # Optionally add custom extensions based on error type if needed
    # if isinstance(getattr(error, 'original_error', None), ...):
    #    formatted_error["extensions"]["code"] = "SOME_SPECIFIC_CODE"
    return formatted_error


def map_exception_to_user_errors(exc: Exception) -> list[UserError]:
    """Maps a caught exception to a list of UserError types for mutation payloads."""
    # Log the original exception for debugging purposes, especially if unhandled
    logger.debug(
        f"Mapping exception to UserError: {type(exc).__name__}: {exc}", exc_info=True
    )

    # --- Specific Exception Mappings ---
    # Add mappings for custom application exceptions here
    if isinstance(exc, ShopifyAuthenticationError):
        return [ShopifyAuthError(message=str(exc) or ShopifyAuthError.message)]
    elif isinstance(exc, ShopifyRateLimitError):
        return [RateLimitError(message=str(exc) or RateLimitError.message)]
    elif isinstance(exc, ShopifyAPIError):
        return [ShopifyAPIError(message=str(exc) or ShopifyAPIError.message)]
    elif isinstance(exc, ActionFailedError):
        return [ActionExecutionError(message=str(exc) or ActionExecutionError.message)]
    elif isinstance(exc, AgentTaskFailedError):
        # TODO: Extract field/context if available from the exception
        return [AnalysisTaskError(message=str(exc) or AnalysisTaskError.message)]

    # --- FastAPI/HTTP Exceptions ---
    if isinstance(exc, HTTPException):
        if exc.status_code == 401:
            return [AuthenticationError(message=exc.detail)]
        if exc.status_code == 403:
            return [AuthorizationError(message=exc.detail)]
        if exc.status_code == 404:
            return [NotFoundError(message=exc.detail)]
        # Treat other HTTP errors as internal for now, or map specific ones
        logger.warning(
            f"Unhandled HTTPException mapped to InternalServerError: Status={exc.status_code}, Detail={exc.detail}"
        )
        return [InternalServerError(message="Unexpected API error occurred.")]

    # --- Common Built-in Exceptions ---
    elif isinstance(exc, ValueError):  # Often indicates bad input if not caught earlier
        # Be specific if possible, otherwise this might hide other issues
        return [InputValidationError(message=str(exc), field="unknown")]
    elif isinstance(exc, NotImplementedError):
        logger.warning(f"Caught NotImplementedError: {exc}")
        return [InternalServerError(message="This feature is not yet implemented.")]

    # --- Default Fallback ---
    else:
        # Log unhandled exceptions with full traceback for diagnosis
        logger.exception(
            f"Unhandled exception mapped to InternalServerError: {type(exc).__name__}: {exc}"
        )
        return [InternalServerError()]  # Generic message for client
