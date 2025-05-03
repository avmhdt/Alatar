import strawberry


# Base User Error Interface (as per design doc)
@strawberry.interface
class UserError:
    message: str
    code: str | None = None  # Make code optional initially for easier adoption
    field: str | None = None  # Optional field identifier


# Concrete Error Implementations
@strawberry.type
class InputValidationError(UserError):
    code: str = "INVALID_INPUT"
    field: str | None = None  # Specific field causing the error


@strawberry.type
class AuthenticationError(UserError):
    code: str = "AUTHENTICATION_REQUIRED"
    field: str | None = None


@strawberry.type
class AuthorizationError(UserError):
    code: str = "PERMISSION_DENIED"
    field: str | None = None


@strawberry.type
class NotFoundError(UserError):
    code: str = "NOT_FOUND"
    field: str | None = None  # e.g., the ID field for the resource not found


@strawberry.type
class ExternalServiceError(UserError):
    code: str = "EXTERNAL_SERVICE_ERROR"
    field: str | None = None  # e.g., 'shopify' or 'openrouter'


@strawberry.type
class AgentProcessingError(UserError):
    code: str = "AGENT_PROCESSING_ERROR"
    field: str | None = None


@strawberry.type
class TaskCancelledError(UserError):
    code: str = "TASK_CANCELLED"
    field: str | None = None


@strawberry.type
class InternalServerError(UserError):
    code: str = "INTERNAL_SERVER_ERROR"
    field: str | None = None


# Add other specific error codes from design doc as needed
# RATE_LIMIT_EXCEEDED (Might be handled differently by middleware)
