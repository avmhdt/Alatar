"""Export service components for use throughout the application."""

# Action related services
from app.services.action_service import (
    create_proposed_action,
    list_pending_actions,
    approve_action,
    reject_action,
)

from app.services.action_executor import (
    execute_approved_action,
    execute_action_async,
)

# Analysis related services
from app.services.analysis_service import (
    get_analysis_request_by_id,
    list_analysis_requests,
    submit_new_request,
)

from app.services.analysis_queue_service import AnalysisQueueService

# Real-time update services
from app.services.pubsub_service import (
    publish,
    subscribe,
    publish_analysis_update,
    subscribe_to_analysis_request,
)

# Queue related services
from app.services.queue_client import (
    QueueClient,
    RABBITMQ_URL,
    QUEUE_C1_INPUT,
    QUEUE_C2_DATA_RETRIEVAL,
    QUEUE_C2_QUANTITATIVE_ANALYSIS,
)

# Shopify related services
from app.services.shopify_client import (
    ShopifyAdminAPIClient,
    ShopifyAdminAPIClientError,
)

from app.services.shopify_service import fetch_store_details

# Permission related services
from app.services.permissions import (
    check_scopes,
    get_required_scopes,
    ACTION_SCOPE_MAPPING,
    # Read scopes
    READ_PRODUCTS,
    READ_ORDERS,
    READ_CUSTOMERS,
    READ_INVENTORY,
    READ_LOCATIONS,
    READ_PRICE_RULES,
    READ_DISCOUNTS,
    # Write scopes
    WRITE_PRODUCTS,
    WRITE_ORDERS,
    WRITE_CUSTOMERS,
    WRITE_INVENTORY,
    WRITE_DISCOUNTS,
    WRITE_PRICE_RULES,
)

__all__ = [
    # Action related services
    "create_proposed_action",
    "list_pending_actions",
    "approve_action",
    "reject_action",
    "execute_approved_action",
    "execute_action_async",
    
    # Analysis related services
    "get_analysis_request_by_id",
    "list_analysis_requests",
    "submit_new_request",
    "AnalysisQueueService",
    
    # Real-time update services
    "publish",
    "subscribe",
    "publish_analysis_update",
    "subscribe_to_analysis_request",
    
    # Queue related services
    "QueueClient",
    "RABBITMQ_URL",
    "QUEUE_C1_INPUT",
    "QUEUE_C2_DATA_RETRIEVAL",
    "QUEUE_C2_QUANTITATIVE_ANALYSIS",
    
    # Shopify related services
    "ShopifyAdminAPIClient",
    "ShopifyAdminAPIClientError",
    "fetch_store_details",
    
    # Permission related services
    "check_scopes",
    "get_required_scopes",
    "ACTION_SCOPE_MAPPING",
    # Read scopes
    "READ_PRODUCTS",
    "READ_ORDERS",
    "READ_CUSTOMERS",
    "READ_INVENTORY",
    "READ_LOCATIONS",
    "READ_PRICE_RULES",
    "READ_DISCOUNTS",
    # Write scopes
    "WRITE_PRODUCTS",
    "WRITE_ORDERS",
    "WRITE_CUSTOMERS",
    "WRITE_INVENTORY",
    "WRITE_DISCOUNTS",
    "WRITE_PRICE_RULES",
]
