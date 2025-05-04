"""Export resolvers for easy combination in the main schema."""

# Analysis Request resolvers
from .analysis_request import (
    submit_analysis_request,
    get_analysis_request,
    list_analysis_requests,
)

# Proposed Action resolvers
from .proposed_action import (
    list_proposed_actions,
    user_approves_action,
    user_rejects_action,
    map_action_model_to_gql,
)

# Subscription resolvers
from .subscription import (
    analysis_request_updates,
)

# User resolvers
from .user import (
    get_current_user_info,
    update_user_preferences,
)

# Common resolvers
from .common import (
    Query,
    Mutation,
    Subscription,
    map_analysis_request_model_to_gql,
    map_proposed_action_model_to_gql,
    map_dict_to_analysis_request_gql,
)


__all__ = [
    # Analysis Request
    "submit_analysis_request",
    "get_analysis_request",
    "list_analysis_requests",
    
    # Proposed Action
    "list_proposed_actions",
    "user_approves_action",
    "user_rejects_action",
    "map_action_model_to_gql",
    
    # Subscription
    "analysis_request_updates",
    
    # User
    "get_current_user_info",
    "update_user_preferences",
    
    # Common
    "Query",
    "Mutation",
    "Subscription",
    "map_analysis_request_model_to_gql",
    "map_proposed_action_model_to_gql",
    "map_dict_to_analysis_request_gql",
]
