import logging
from typing import Any

import strawberry
from graphql import GraphQLError
from sqlalchemy.exc import SQLAlchemyError
from strawberry.extensions import Extension

logger = logging.getLogger(__name__)


class CustomErrorHandler(Extension):
    """A Strawberry extension to catch specific exceptions and format them as UserErrors.

    Catches SQLAlchemyError and general Exceptions during the execution phase.
    """

    def on_execute(self):
        """Called before the execution phase starts."""
        logger.debug("GraphQL execution starting...")
        yield
        # Called after the execution phase finishes
        logger.debug("GraphQL execution finished.")

    def on_request_end(self):
        """Called after the request processing is finished (including formatting results/errors)."""
        # You can access the final result/errors here if needed
        # result = self.execution_context.result
        # if result and result.errors:
        #     logger.debug(f"GraphQL request finished with errors: {result.errors}")

    def resolve(self, _next, root, info: strawberry.Info, *args, **kwargs):
        """Wraps individual resolver calls.

        This is where we can catch errors originating *within* a specific resolver.
        """
        try:
            return _next(root, info, *args, **kwargs)
        except SQLAlchemyError as e:
            logger.error(
                f"SQLAlchemyError in resolver '{info.field_name}': {e}", exc_info=True
            )
            # Optionally extract more specific info from e if needed
            # You might want to hide detailed DB errors from the client
            raise GraphQLError(
                message="A database error occurred.",
                extensions=self.format_as_user_error(
                    message="A database error occurred.", code="DATABASE_ERROR"
                ),
            )
        except ValueError as e:
            logger.warning(
                f"ValueError in resolver '{info.field_name}': {e}", exc_info=False
            )
            # ValueError often indicates bad input, treat as user error
            raise GraphQLError(
                message=str(e),
                extensions=self.format_as_user_error(
                    message=str(e), code="VALIDATION_ERROR"
                ),
            )
        except (
            PermissionError
        ) as e:  # Assuming you might raise PermissionError for authz
            logger.warning(f"PermissionError in resolver '{info.field_name}': {e}")
            raise GraphQLError(
                message=str(e) or "Permission denied.",
                extensions=self.format_as_user_error(
                    message=str(e) or "Permission denied.", code="PERMISSION_DENIED"
                ),
            )
        except Exception as e:
            # Catch-all for other unexpected errors within resolvers
            logger.error(
                f"Unexpected Exception in resolver '{info.field_name}': {e}",
                exc_info=True,
            )
            raise GraphQLError(
                message="An unexpected error occurred.",
                extensions=self.format_as_user_error(
                    message="An unexpected internal error occurred.",
                    code="INTERNAL_SERVER_ERROR",
                ),
            )

    def format_as_user_error(
        self, message: str, code: str, field: str | None = None
    ) -> dict[str, Any]:
        """Formats error details into the structure expected by GraphQL errors extensions
        when wanting to convey UserError-like information.
        """
        user_error = {
            "message": message,
            "code": code,
        }
        if field:
            user_error["field"] = field

        # Nest it under a key, e.g., "userError", if your frontend expects it
        # Or return directly if you handle the structure flatly in extensions
        return {"userError": user_error}

    # Note: The standard GraphQL `errors` array will contain the messages.
    # The `extensions` part allows adding structured data like `code` and `field`.
    # Your UserError GQL Type is primarily useful for *mutations* where partial success
    # is possible, allowing you to return `userErrors` list alongside partial data in the payload.
    # This extension focuses on formatting the top-level errors array.
