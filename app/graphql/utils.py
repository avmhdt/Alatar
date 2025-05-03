import base64
import datetime
import uuid
from enum import Enum
from typing import Any

from fastapi import Request
from strawberry.types import Info

from app.auth.dependencies import get_optional_user_id_from_token
from app.core.exceptions import PermissionDeniedError


class NodeType(Enum):
    """Enum for identifying different node types in Global IDs."""

    USER = "User"
    ANALYSIS_REQUEST = "AnalysisRequest"
    PROPOSED_ACTION = "ProposedAction"
    LINKED_ACCOUNT = "LinkedAccount"
    SHOPIFY_STORE = "ShopifyStore"  # Example
    # Add other node types here


def encode_cursor(
    primary_value: datetime.datetime | str | int,
    secondary_value: uuid.UUID | int | str,
) -> str:
    """Encodes primary and secondary sort values into an opaque cursor string."""
    if isinstance(primary_value, datetime.datetime):
        primary_str = primary_value.isoformat()
    else:
        primary_str = str(primary_value)

    secondary_str = str(secondary_value)
    combined = f"{primary_str}:{secondary_str}"  # Simple delimiter

    return base64.urlsafe_b64encode(combined.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> tuple[Any, Any] | None:
    """Decodes an opaque cursor string back into its primary and secondary values.

    Returns
    -------
        A tuple (primary_value, secondary_value) or None if decoding fails.
        Primary value attempts to parse as datetime.

    """
    try:
        decoded_bytes = base64.urlsafe_b64decode(cursor.encode("utf-8"))
        decoded_str = decoded_bytes.decode("utf-8")
        primary_str, secondary_str = decoded_str.split(":", 1)

        # Attempt to parse primary as datetime
        try:
            if primary_str.endswith("Z"):
                primary_value = datetime.datetime.fromisoformat(
                    primary_str[:-1] + "+00:00"
                )
            elif "+" in primary_str or "-" in primary_str[-6:]:
                primary_value = datetime.datetime.fromisoformat(primary_str)
            else:
                primary_value = datetime.datetime.fromisoformat(primary_str)
        except ValueError:
            primary_value = primary_str  # Fallback to string

        # Secondary value usually remains string or converted based on context (e.g., UUID)
        # For now, return as string. Caller might need to convert.
        secondary_value = secondary_str

        return primary_value, secondary_value
    except (ValueError, TypeError, base64.binascii.Error):
        return None  # Invalid cursor format


def get_validated_user_id(info: Info) -> uuid.UUID:
    """Extracts user_id from context/request and raises PermissionDeniedError if not found."""
    request: Request | None = info.context.get("request")
    if not request:
        # This should not happen if context setup is correct
        raise PermissionDeniedError("Request context not found.")

    user_id: uuid.UUID | None = get_optional_user_id_from_token(request)
    if not user_id:
        raise PermissionDeniedError("Authentication required.")
    return user_id
