import logging
from typing import Any

from graphql.errors import GraphQLError
from graphql.errors import format_graphql_error
from strawberry.extensions import Extension

logger = logging.getLogger(__name__)


# Define custom exception types if needed for specific error handling
class PermissionDeniedError(Exception):
    """Custom exception for permission errors."""

    def __init__(self, message="Permission denied."):
        self.message = message
        super().__init__(self.message)


class AuthenticationError(Exception):
    """Custom exception for authentication errors."""

    def __init__(self, message="Authentication required."):
        self.message = message
        super().__init__(self.message)


class InputValidationError(Exception):
    """Custom exception for input validation errors."""

    def __init__(self, message="Input validation failed.", field: str | None = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


class CustomErrorHandler(Extension):
    def on_execute(self):
        """Handles errors after execution."""
        yield  # Let the operation execute first

        execution_context = self.execution_context
        if (
            execution_context
            and execution_context.result
            and execution_context.result.errors
        ):
            processed_errors: list[GraphQLError] = []
            for error in execution_context.result.errors:
                original_error = getattr(error, "original_error", None)

                # Log the original error with stack trace for internal debugging
                logger.error(
                    f"GraphQL Error: {error.message}",
                    exc_info=original_error or error,  # Log original_error if available
                    extra={
                        "props": {
                            "path": error.path,
                            "locations": [loc.formatted for loc in error.locations]
                            if error.locations
                            else None,
                            "query": execution_context.query,
                            "operation_name": execution_context.operation_name,
                            "variables": execution_context.variable_values,
                        }
                    },
                )

                # --- Format the user-facing error ---
                # Default generic message
                user_message = "An unexpected error occurred. Please contact support if the issue persists."
                extensions: dict[str, Any] = {"code": "INTERNAL_SERVER_ERROR"}

                # Handle specific custom exceptions raised in resolvers
                if isinstance(original_error, AuthenticationError):
                    user_message = original_error.message
                    extensions["code"] = "AUTHENTICATION_ERROR"
                elif isinstance(original_error, PermissionDeniedError):
                    user_message = original_error.message
                    extensions["code"] = "PERMISSION_DENIED"
                elif isinstance(original_error, InputValidationError):
                    user_message = original_error.message
                    extensions["code"] = "BAD_USER_INPUT"
                    if original_error.field:
                        extensions["field"] = original_error.field
                elif isinstance(original_error, GraphQLError):
                    # Handle errors explicitly raised as GraphQLError in resolvers
                    # Potentially use their message if considered safe
                    user_message = original_error.message
                    # Inherit extensions if provided, otherwise default
                    extensions = original_error.extensions or extensions

                # Create a new GraphQLError with the potentially formatted message and extensions
                # We reuse the original locations and path
                processed_errors.append(
                    GraphQLError(
                        message=user_message,
                        nodes=error.nodes,
                        source=error.source,
                        positions=error.positions,
                        path=error.path,
                        original_error=None,  # Don't expose original error details to client
                        extensions=extensions,
                    )
                )

            # Replace original errors with processed ones
            execution_context.result.errors = processed_errors

    def format(self) -> dict[str, Any]:
        """Formats the final GraphQL response including errors."""
        response = super().format()  # Get the default Strawberry formatting
        if response.get("errors"):
            # Apply standard GraphQL error formatting to our processed errors
            response["errors"] = [
                format_graphql_error(error) for error in response["errors"]
            ]
        return response
