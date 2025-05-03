"""
Core exceptions for the application.
"""

class APIException(Exception):
    """Base class for API exceptions."""
    def __init__(self, message: str = "An error occurred"):
        self.message = message
        super().__init__(self.message)


class PermissionDeniedError(APIException):
    """Raised when a user doesn't have permission to perform an action."""
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message)


class ValidationError(APIException):
    """Raised when input data fails validation."""
    def __init__(self, message: str = "Validation error", errors: dict = None):
        self.errors = errors or {}
        super().__init__(message)


class NotFoundError(APIException):
    """Raised when a requested resource is not found."""
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class AuthenticationError(APIException):
    """Raised when authentication fails."""
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message) 