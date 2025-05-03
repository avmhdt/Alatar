# from app.utils.logger import logger # Removed unused
import logging
import uuid

# from sqlalchemy.orm import Session # Removed unused sync Session
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession  # Added
from sqlalchemy.future import select  # Add select import

from app.database import current_user_id_cv, get_async_db, AsyncSessionLocal
from app.models.linked_account import LinkedAccount
from app.models.proposed_action import ProposedAction, ProposedActionStatus
from app.services.permissions import check_scopes, get_required_scopes  # Added

# from app.clients.shopify_admin_api import ShopifyAdminAPIClient # Changed path
from app.services.shopify_client import (  # Corrected import
    ShopifyAdminAPIClient,
    ShopifyAdminAPIClientError,
)

logger = logging.getLogger(__name__)  # Use standard logger


# TODO: Refactor execute_approved_action and _execute_action_logic to be fully async
async def execute_approved_action(action_id: uuid.UUID):
    """Handles the execution of an approved action.
    This function fetches the action, checks permissions, and attempts execution.
    It updates the action's status and logs accordingly.
    NOTE: This function runs in the background and MUST acquire its own DB session.
    """
    db: AsyncSession = AsyncSessionLocal()  # Changed to AsyncSession
    try:
        # NOTE: _execute_action_logic currently uses sync DB methods and needs refactoring
        await _execute_action_logic(db, action_id)
    finally:
        # NOTE: db.close() should become await db.close() after refactoring
        await db.close()


# TODO: Refactor this function to be fully async (use await db.execute(select(...)), await db.commit(), etc.)
async def execute_action_async(action_id: uuid.UUID, user_id: uuid.UUID): # Accept IDs
    """Handles the execution of an approved action asynchronously.
    Fetches action, checks permissions, executes via Shopify client, updates status.
    Acquires its own DB session and manages RLS context.
    Should be called by the action execution worker.
    """
    log_props = {"action_id": str(action_id), "user_id": str(user_id)}
    cv_token = current_user_id_cv.set(user_id) # Set RLS context for this task
    action: ProposedAction | None = None
    shopify_client: ShopifyAdminAPIClient | None = None
    db: AsyncSession | None = None # Define db in outer scope

    try:
        # Acquire session using async context manager
        async with get_async_db() as db:
            # get_async_db sets RLS using current_user_id_cv

            # Fetch the action using AsyncSession
            action_stmt = select(ProposedAction).filter(ProposedAction.id == action_id)
            result = await db.execute(action_stmt)
            action = result.scalar_one_or_none()

            if not action:
                logger.error(
                    f"Action execution failed: Non-existent action ID: {action_id}",
                    extra=log_props,
                )
                return # Action doesn't exist, nothing more to do

            # Ensure the action is in the correct state to be executed
            if action.status != ProposedActionStatus.APPROVED:
                logger.warning(
                    f"Attempted to execute action {action_id} which is not in APPROVED state (state: {action.status}). Skipping.",
                    extra={
                        "audit": True,
                        "audit_event": "ACTION_EXECUTION_SKIPPED",
                        "reason": f"Invalid state: {action.status.value}",
                        **log_props,
                        "action_type": action.action_type,
                    },
                )
                # Do not change status here, let the approval step handle the state machine logic
                return

            # Audit Log: Execution Started
            logger.info(
                f"Starting execution for action {action.id} (Type: {action.action_type})",
                extra={
                    "audit": True,
                    "audit_event": "ACTION_EXECUTION_STARTED",
                    **log_props,
                    "action_type": action.action_type,
                    "parameters": action.parameters,
                },
            )
            action.status = ProposedActionStatus.EXECUTING
            action.execution_logs = "Starting execution..."
            db.add(action)
            await db.commit() # Commit EXECUTING status
            await db.refresh(action)

            execution_outcome = "UNKNOWN"
            error_details = None
            try:
                # 1. Fetch Linked Account credentials and info (Async)
                linked_account_stmt = select(LinkedAccount).filter(
                    LinkedAccount.id == action.linked_account_id
                )
                result = await db.execute(linked_account_stmt)
                linked_account = result.scalar_one_or_none()

                if not linked_account:
                    raise ValueError(
                        f"ProposedAction {action.id} is missing required linked_account {action.linked_account_id}."
                    )

                if linked_account.account_type != "shopify":
                    raise NotImplementedError(
                        f"Action execution only implemented for 'shopify', not '{linked_account.account_type}'"
                    )

                granted_scopes_str = linked_account.scopes or ""
                granted_scopes = [
                    scope.strip() for scope in granted_scopes_str.split(",") if scope.strip()
                ]
                shop_domain = linked_account.account_name

                # 2. Check Permissions
                required_scopes = get_required_scopes(action.action_type)
                if not required_scopes:
                    logger.warning(
                        f"No scopes defined for action type '{action.action_type}'. Assuming permitted, but configuration needed.",
                        extra=log_props
                    )

                if not check_scopes(required_scopes, granted_scopes):
                    permission_error_msg = (
                        f"Permission denied. Action '{action.action_type}' requires scopes: "
                        f"{required_scopes}, but user only granted: {granted_scopes}."
                    )
                    raise PermissionError(permission_error_msg)

                # 3. Initialize Shopify Client (Async)
                # Pass the async db session
                shopify_client = ShopifyAdminAPIClient(
                    db=db, user_id=action.user_id, shop_domain=shop_domain
                )
                # Initialization (_ensure_initialized) happens lazily within client methods

                # 4. Execute Action based on type (Async)
                execution_result = None
                if action.action_type == "shopify_update_product_price":
                    product_id = action.parameters.get("product_id")
                    new_price = action.parameters.get("new_price")
                    if not product_id or new_price is None:
                        raise ValueError(
                            "Missing 'product_id' (variant GID) or 'new_price' in parameters for shopify_update_product_price"
                        )

                    logger.info(
                        f"Executing shopify_update_product_price async: Variant GID {product_id}, New Price {new_price}",
                        extra=log_props
                    )
                    # Call async client method, passing db session
                    execution_result = await shopify_client.aupdate_product_price(
                        product_variant_gid=product_id, new_price=float(new_price), db=db
                    )

                elif action.action_type == "shopify_create_discount_code":
                    discount_details = action.parameters.get("discount_details")
                    if not discount_details or not isinstance(discount_details, dict):
                        raise ValueError(
                            "Missing or invalid 'discount_details' (dict) in parameters for shopify_create_discount_code"
                        )

                    logger.info(
                        f"Executing shopify_create_discount_code async with details: {discount_details}",
                        extra=log_props
                    )
                    execution_result = await shopify_client.acreate_discount(
                        discount_details=discount_details, db=db
                    )

                elif action.action_type == "shopify_adjust_inventory":
                    inventory_item_gid = action.parameters.get("inventory_item_gid")
                    location_gid = action.parameters.get("location_gid")
                    delta = action.parameters.get("delta")
                    if not inventory_item_gid or not location_gid or delta is None:
                        raise ValueError(
                            "Missing 'inventory_item_gid', 'location_gid', or 'delta' in parameters for shopify_adjust_inventory"
                        )

                    logger.info(
                        f"Executing shopify_adjust_inventory async: Item {inventory_item_gid}, Location {location_gid}, Delta {delta}",
                        extra=log_props
                    )
                    execution_result = await shopify_client.aadjust_inventory(
                        inventory_item_gid=inventory_item_gid,
                        location_gid=location_gid,
                        delta=int(delta),
                        db=db,
                    )

                else:
                    raise NotImplementedError(
                        f"Execution logic for action type '{action.action_type}' is not defined."
                    )

                # 5. Update Action Status to Executed (Async)
                action.status = ProposedActionStatus.EXECUTED
                action.executed_at = datetime.now(UTC)
                exec_log_str = f"Execution successful. Result summary: {str(execution_result)[:500]}"
                action.execution_logs = exec_log_str
                execution_outcome = "SUCCESS"
                logger.info(f"Action {action.id} executed successfully async.", extra=log_props)

            # --- Exception Handling within the 'try' for action execution ---
            except PermissionError as pe:
                action.status = ProposedActionStatus.FAILED
                error_details = f"Permission denied: {pe}"
                action.execution_logs = error_details
                execution_outcome = "FAILED_PERMISSION"
                logger.error(f"Permission error executing action {action.id} async: {pe}", extra=log_props)
            except NotImplementedError as nie:
                action.status = ProposedActionStatus.FAILED
                error_details = f"Action type not implemented: {nie}"
                action.execution_logs = error_details
                execution_outcome = "FAILED_NOT_IMPLEMENTED"
                logger.error(f"Action type not implemented for action {action.id} async: {nie}", extra=log_props)
            except ShopifyAdminAPIClientError as se:
                action.status = ProposedActionStatus.FAILED
                error_details = f"Shopify API error: {se} (Status: {se.status_code}, Errors: {se.shopify_errors})"
                action.execution_logs = error_details
                execution_outcome = "FAILED_API_ERROR"
                logger.error(
                    f"Shopify API error executing action {action.id} async: {se}", exc_info=True, extra=log_props
                )
            except ValueError as ve: # Catch parameter validation errors
                action.status = ProposedActionStatus.FAILED
                error_details = f"Invalid parameters: {ve}"
                action.execution_logs = error_details
                execution_outcome = "FAILED_INVALID_PARAMS"
                logger.error(f"Invalid parameters for action {action.id} async: {ve}", exc_info=True, extra=log_props)
            except Exception as e:
                action.status = ProposedActionStatus.FAILED
                error_details = f"Unexpected error: {e}"
                action.execution_logs = error_details
                execution_outcome = "FAILED_UNEXPECTED"
                logger.exception(f"Unexpected error executing action {action.id} async: {e}", extra=log_props)

            # --- Final Status Update & Audit Log (within async session) ---
            finally:
                # Log finished event regardless of outcome
                logger.info(
                    f"Action execution finished async with outcome: {execution_outcome}",
                    extra={
                        "audit": True,
                        "audit_event": "ACTION_EXECUTION_FINISHED",
                        **log_props,
                        "action_type": action.action_type,
                        "final_status": action.status.value,
                        "outcome": execution_outcome,
                        "error_details": error_details,
                    },
                )
                # Commit the final status (EXECUTED or FAILED)
                db.add(action)
                await db.commit()

    # --- Outer Exception Handling (for session acquisition or other unexpected errors) ---
    except Exception as outer_err:
        logger.exception(f"Critical error in execute_action_async for action {action_id}: {outer_err}", extra=log_props)
        # If action was loaded, try to mark as FAILED with this critical error message
        # This requires another DB session attempt if the first one failed critically
        if action and action.status not in [ProposedActionStatus.EXECUTED, ProposedActionStatus.FAILED]:
             try:
                 async with get_async_db() as db_fail_safe:
                    # Re-fetch in new session to avoid detached instance errors
                    fail_action_stmt = select(ProposedAction).filter(ProposedAction.id == action_id)
                    result = await db_fail_safe.execute(fail_action_stmt)
                    fail_action = result.scalar_one_or_none()
                    if fail_action and fail_action.status not in [ProposedActionStatus.EXECUTED, ProposedActionStatus.FAILED]:
                        fail_action.status = ProposedActionStatus.FAILED
                        fail_action.execution_logs = f"Critical executor failure: {outer_err}"
                        db_fail_safe.add(fail_action)
                        await db_fail_safe.commit()
             except Exception as fail_safe_err:
                  logger.error(f"Failed to perform fail-safe status update for action {action_id}: {fail_safe_err}", extra=log_props)

    # --- Resource Cleanup ---
    finally:
        # Close Shopify client if it was initialized
        if shopify_client:
            await shopify_client.aclose()
            logger.debug(f"Closed Shopify client for action {action_id}", extra=log_props)
        # Reset RLS context variable
        current_user_id_cv.reset(cv_token)
        logger.debug(f"Reset RLS context for action {action_id}", extra=log_props)

# TODO: Refactor this function to be fully async (use await db.execute(select(...)), await db.commit(), etc.)
async def _execute_action_logic(db: AsyncSession, action_id: uuid.UUID):  # Made async
    # Renamed original function to _execute_action_logic
    # The rest of the function logic remains the same, operating on the passed 'db' session
    # --- The following code is currently SYNC and needs refactoring for AsyncSession --- #
    # action = db.query(ProposedAction).filter(ProposedAction.id == action_id).first()
    action_stmt = select(ProposedAction).filter(ProposedAction.id == action_id)
    result = await db.execute(action_stmt)
    action = result.scalar_one_or_none()

    if not action:
        logger.error(f"Attempted to execute non-existent action ID: {action_id}")
        return  # Or raise an exception

    # Ensure the action is in the correct state to be executed
    if action.status != ProposedActionStatus.APPROVED:
        logger.warning(
            f"Attempted to execute action {action_id} which is not in APPROVED state (state: {action.status}). Skipping.",
            extra={
                "audit": True,
                "audit_event": "ACTION_EXECUTION_SKIPPED",
                "reason": f"Invalid state: {action.status.value}",
                "action_id": str(action_id),
                "user_id": str(action.user_id),
                "action_type": action.action_type,
            },
        )
        # Optionally set to FAILED if this happens unexpectedly
        # action.status = ProposedActionStatus.FAILED
        # action.execution_logs = f"Execution attempt failed: Action was in state {action.status.value}, expected APPROVED."
        # await db.commit() # Change to await if uncommented
        return

    # Audit Log: Execution Started
    logger.info(
        f"Starting execution for action {action.id} (Type: {action.action_type})",
        extra={
            "audit": True,
            "audit_event": "ACTION_EXECUTION_STARTED",
            "action_id": str(action.id),
            "user_id": str(action.user_id),
            "action_type": action.action_type,
            "parameters": action.parameters,  # Consider summarizing/masking
        },
    )
    action.status = ProposedActionStatus.EXECUTING
    action.execution_logs = "Starting execution..."
    db.add(action)  # Add action before commit/refresh
    await db.commit()
    await db.refresh(action)

    execution_outcome = "UNKNOWN"
    error_details = None
    try:
        # 1. Fetch Linked Account credentials and info
        # linked_account = (
        #     await db.execute(
        #         db.query(LinkedAccount) # This is sync syntax
        #         .filter(LinkedAccount.id == action.linked_account_id)
        #         .select() # select() here is likely incorrect
        #     )
        # ).scalar_one()
        linked_account_stmt = select(LinkedAccount).filter(
            LinkedAccount.id == action.linked_account_id
        )
        result = await db.execute(linked_account_stmt)
        linked_account = result.scalar_one_or_none()

        if not linked_account:
            raise ValueError(
                f"ProposedAction {action.id} is missing required linked_account_id."
            )

        if linked_account.account_type != "shopify":
            raise NotImplementedError(
                f"Action execution only implemented for 'shopify', not '{linked_account.account_type}'"
            )

        granted_scopes_str = linked_account.scopes or ""
        granted_scopes = [
            scope.strip() for scope in granted_scopes_str.split(",") if scope.strip()
        ]
        shop_domain = (
            linked_account.account_name
        )  # Assuming account_name stores the shop domain

        # 2. Check Permissions
        required_scopes = get_required_scopes(action.action_type)
        if not required_scopes:
            logger.warning(
                f"No scopes defined for action type '{action.action_type}'. Assuming permitted, but configuration needed."
            )
            # Decide if this should be an error or allowed

        if not check_scopes(required_scopes, granted_scopes):
            permission_error_msg = (
                f"Permission denied. Action '{action.action_type}' requires scopes: "
                f"{required_scopes}, but user only granted: {granted_scopes}."
            )
            raise PermissionError(permission_error_msg)

        # 3. Initialize Shopify Client
        # Ensure the client is initialized correctly with the user_id and shop_domain
        # Pass the current async db session
        shopify_client = ShopifyAdminAPIClient(
            db=db, user_id=action.user_id, shop_domain=shop_domain
        )

        # 4. Execute Action based on type
        execution_result = None
        if action.action_type == "shopify_update_product_price":
            # Extract parameters safely
            product_id = action.parameters.get("product_id")  # Should be variant GID
            new_price = action.parameters.get("new_price")
            if not product_id or new_price is None:
                raise ValueError(
                    "Missing 'product_id' (variant GID) or 'new_price' in parameters for shopify_update_product_price"
                )

            logger.info(
                f"Executing shopify_update_product_price: Variant GID {product_id}, New Price {new_price}"
            )
            # Pass db session to the client method
            execution_result = await shopify_client.aupdate_product_price(
                product_variant_gid=product_id, new_price=float(new_price), db=db
            )

        elif action.action_type == "shopify_create_discount_code":
            # Extract parameters
            discount_details = action.parameters.get("discount_details")  # Example
            if not discount_details or not isinstance(discount_details, dict):
                raise ValueError(
                    "Missing or invalid 'discount_details' (dict) in parameters for shopify_create_discount_code"
                )

            logger.info(
                f"Executing shopify_create_discount_code with details: {discount_details}"
            )
            # Pass db session to the client method
            execution_result = await shopify_client.acreate_discount(
                discount_details=discount_details, db=db
            )

        elif action.action_type == "shopify_adjust_inventory":
            inventory_item_gid = action.parameters.get("inventory_item_gid")
            location_gid = action.parameters.get("location_gid")
            delta = action.parameters.get("delta")
            if not inventory_item_gid or not location_gid or delta is None:
                raise ValueError(
                    "Missing 'inventory_item_gid', 'location_gid', or 'delta' in parameters for shopify_adjust_inventory"
                )

            logger.info(
                f"Executing shopify_adjust_inventory: Item {inventory_item_gid}, Location {location_gid}, Delta {delta}"
            )
            # Pass db session to the client method
            execution_result = await shopify_client.aadjust_inventory(
                inventory_item_gid=inventory_item_gid,
                location_gid=location_gid,
                delta=int(delta),
                db=db,
            )

        # --- Add elif blocks for other supported action_types --- #

        else:
            raise NotImplementedError(
                f"Execution logic for action type '{action.action_type}' is not defined."
            )

        # 5. Update Action Status to Executed
        action.status = ProposedActionStatus.EXECUTED
        action.executed_at = datetime.now(UTC)
        # Store summary or confirmation. Be careful about storing too much data.
        # Truncate or summarize if needed.
        exec_log_str = f"Execution successful. Result summary: {str(execution_result)[:500]}"  # Example truncation
        action.execution_logs = exec_log_str
        execution_outcome = "SUCCESS"
        logger.info(f"Action {action.id} executed successfully.")

    except PermissionError as pe:
        action.status = ProposedActionStatus.FAILED
        error_details = f"Permission denied: {pe}"
        action.execution_logs = error_details
        execution_outcome = "FAILED_PERMISSION"
        logger.error(f"Permission error executing action {action.id}: {pe}")
    except NotImplementedError as nie:
        action.status = ProposedActionStatus.FAILED
        error_details = f"Action type not implemented: {nie}"
        action.execution_logs = error_details
        execution_outcome = "FAILED_NOT_IMPLEMENTED"
        logger.error(f"Action type not implemented for action {action.id}: {nie}")
    except ShopifyAdminAPIClientError as se:
        action.status = ProposedActionStatus.FAILED
        error_details = f"Shopify API error: {se} (Status: {se.status_code}, Errors: {se.shopify_errors})"
        action.execution_logs = error_details
        execution_outcome = "FAILED_API_ERROR"
        logger.error(
            f"Shopify API error executing action {action.id}: {se}", exc_info=True
        )
    except Exception as e:
        action.status = ProposedActionStatus.FAILED
        error_details = f"Unexpected error: {e}"
        action.execution_logs = error_details
        execution_outcome = "FAILED_UNEXPECTED"
        logger.exception(f"Unexpected error executing action {action.id}: {e}")

    finally:
        # Audit Log: Execution Finished
        logger.info(
            f"Action execution finished with outcome: {execution_outcome}",
            extra={
                "audit": True,
                "audit_event": "ACTION_EXECUTION_FINISHED",
                "action_id": str(action.id),
                "user_id": str(action.user_id),
                "action_type": action.action_type,
                "final_status": action.status.value,
                "outcome": execution_outcome,
                "error_details": error_details,  # Will be None on success
            },
        )
        # Ensure the final status is committed within this session
        # If the session failed mid-operation, this commit might also fail
        # or might commit a FAILED status update.
        try:
            db.add(action)  # Add the possibly modified action back to the session
            await db.commit()
        except Exception as commit_err:
            logger.exception(
                f"Failed to commit final action status for action {action.id}: {commit_err}"
            )
            # Optionally rollback if commit fails, though the session might be unusable
            await db.rollback()
        finally:
            # Close the Shopify client connection if needed (assuming it's managed externally now)
            if "shopify_client" in locals() and hasattr(shopify_client, "aclose"):
                await shopify_client.aclose()
