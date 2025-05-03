import base64
import logging
import uuid
from typing import TypeVar

import strawberry
from sqlalchemy.orm import Session
from strawberry.types import Info

from app.models.analysis_request import AnalysisRequest as AnalysisRequestModel
from app.models.proposed_action import ProposedAction as ProposedActionModel

# Import models and GQL types that will be Nodes
# Adjust these imports based on your actual model/type locations
from app.models.user import User as UserModel

from .types.analysis_request import AnalysisRequest as AnalysisRequestGQL
from .types.proposed_action import (
    ProposedAction as ProposedActionGQL,
)

# Import GQL types (ensure they are defined)
from .types.user import User as UserGQL

T = TypeVar("T")  # Generic type var for models


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


# --- Node Fetching Logic ---

# Mapping from GQL type name to DB Model and GQL Type
# Add all Node types here
NODE_MAP: dict[str, tuple[type[T], type]] = {
    "User": (UserModel, UserGQL),
    "AnalysisRequest": (AnalysisRequestModel, AnalysisRequestGQL),
    "ProposedAction": (ProposedActionModel, ProposedActionGQL),
    # Add other Node types (e.g., ShopifyStore if it becomes a Node)
}


async def get_node(info: Info, global_id: strawberry.ID) -> Node | None:
    """Fetches any Node object by its global ID."""
    try:
        type_name, pk_str = from_global_id(global_id)
    except ValueError as e:
        # Handle invalid ID format gracefully (e.g., log and return None)
        # Or raise a specific GraphQL error
        logger.warning(f"Could not decode global ID '{global_id}': {e}")
        return None

    if type_name not in NODE_MAP:
        logger.warning(
            f"Unknown type name '{type_name}' found in global ID '{global_id}'"
        )
        return None

    db_model, gql_type = NODE_MAP[type_name]
    db: Session = info.context.db

    # Fetch from DB using primary key
    # Assumes primary key is 'id' and potentially a UUID
    # Adjust fetching logic based on your models' primary keys
    try:
        # Attempt UUID conversion if it looks like one, otherwise use raw string
        # This needs refinement based on actual PK types
        try:
            pk = uuid.UUID(pk_str)
        except ValueError:
            pk = pk_str  # Use the string PK if not a UUID

        # Use RLS context implicitly provided via session
        db_obj = db.get(db_model, pk)

    except Exception as e:
        logger.error(
            f"Database error fetching node {type_name} with pk '{pk_str}': {e}",
            exc_info=True,
        )
        # Optionally raise a GraphQL error for internal issues
        return None  # Or raise internal server error

    if db_obj:
        # Convert DB model to GQL type
        # Strawberry Pydantic types might handle this with from_orm
        # Otherwise, manual mapping or a helper function is needed.
        if hasattr(gql_type, "from_orm"):
            return gql_type.from_orm(db_obj)
        else:
            # Fallback: Requires manual mapping or a different conversion method
            logger.error(
                f"GQL Type {gql_type.__name__} lacks .from_orm() method for Node conversion."
            )
            # You might need to implement a specific mapping function here
            # Example: return map_db_to_gql(db_obj, gql_type)
            return None  # Cannot convert without mapping
    else:
        logger.debug(
            f"Node {type_name} with pk '{pk_str}' not found or not accessible."
        )
        return None


# Define logger for this module (add if not already present)
logger = logging.getLogger(__name__)
