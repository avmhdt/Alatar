import base64
import uuid
import strawberry
from typing import TypeVar, NewType

T = TypeVar("T")  # Generic type var for models

# Define ConnectionCursor as a strawberry scalar for use in pagination
ConnectionCursor = strawberry.scalar(
    NewType("ConnectionCursor", str),
    description="Opaque cursor for use in pagination",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

# --- Node Interface ---
@strawberry.interface
class Node:
    """An object with an ID, conforming to Relay Node interface."""

    id: strawberry.ID

# --- Global ID Functions ---


def to_global_id(type_name: str, id: str | int | uuid.UUID) -> strawberry.ID:
    """Encodes a type name and ID into a global ID string."""
    combined = f"{type_name}:{id}"
    return strawberry.ID(base64.b64encode(combined.encode("utf-8")).decode("utf-8"))


def from_global_id(global_id: strawberry.ID) -> tuple[str, str]:
    """Decodes a global ID string into a type name and ID."""
    try:
        decoded_bytes = base64.b64decode(global_id.encode("utf-8"))
        decoded_str = decoded_bytes.decode("utf-8")
        type_name, id_str = decoded_str.split(":", 1)
        return type_name, id_str
    except (ValueError, TypeError, base64.binascii.Error) as e:
        raise ValueError(f"Invalid Global ID: {global_id}. Error: {e}")



