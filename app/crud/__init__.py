from app.crud.base import CRUDBase
from app.crud.analysis_request import analysis_request
from app.crud.crud_user import (
    add_user,
    get_user,
    get_user_by_email,
    aget_user,
    aget_user_by_email,
)
from app.crud.crud_linked_account import (
    get_decrypted_token_for_shopify_account,
    get_linked_account_by_user_and_shop,
    get_linked_account,
    aget_linked_account,
    aget_linked_account_by_user_and_shop,
    aget_decrypted_token_for_shopify_account,
    asave_shopify_account,
    get_first_shopify_account_for_user,
)
from app.crud.crud_user_preferences import (
    create_or_update_user_preferences,
    get_user_preferences,
    aget_user_preferences,
    acreate_or_update_user_preferences,
)

# Import other CRUD modules as they are created
from app.crud.crud_agent_task import (
    aget_agent_task,
    create_agent_task,
    get_agent_task,
    get_agent_tasks_by_ids,
    update_agent_task_status,
)
from app.crud.crud_proposed_action import (
    create_proposed_action,
    get_multi_proposed_actions_by_user,
    get_proposed_action,
    update_proposed_action_status,
    acreate_proposed_action,
    aget_proposed_action,
    aupdate_proposed_action_status,
)


__all__ = [
    "CRUDBase",
    "analysis_request",
    "add_user",
    "get_user",
    "get_user_by_email",
    "create_or_update_shopify_account",
    "get_decrypted_token_for_shopify_account",
    "get_linked_account_by_user_and_shop",
    "get_linked_account",
    "create_or_update_user_preferences",
    "get_user_preferences",
    "aget_user_preferences",
    "acreate_or_update_user_preferences",
    # User Async
    "aget_user",
    "aget_user_by_email",
    # LinkedAccount Async
    "aget_linked_account",
    "aget_linked_account_by_user_and_shop",
    "asave_shopify_account",
    "aget_decrypted_token_for_shopify_account",
    "get_first_shopify_account_for_user",
    # AgentTask
    "aget_agent_task",
    "create_agent_task",
    "get_agent_task",
    "get_agent_tasks_by_ids",
    "update_agent_task_status",
    # ProposedAction
    "create_proposed_action",
    "get_multi_proposed_actions_by_user",
    "get_proposed_action",
    "update_proposed_action_status",
    # ProposedAction Async
    "acreate_proposed_action",
    "aget_proposed_action",
    "aupdate_proposed_action_status",
    # Add other CRUD variables here
] 