import asyncio
import json
import logging
import signal
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

# Attempt to import and configure OpenTelemetry auto-instrumentation
try:
    import opentelemetry.instrumentation.auto_instrumentation.sitecustomize

    # You might need to configure exporters, etc., via environment variables
    # e.g., OTEL_TRACES_EXPORTER=otlp_http, OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    opentelemetry.instrumentation.auto_instrumentation.sitecustomize.bootstrap()
    logging.info("OpenTelemetry auto-instrumentation bootstrapped successfully.")
except ImportError:
    logging.warning("OpenTelemetry auto-instrumentation not found. Skipping.")
except Exception as otel_err:
    logging.error(f"Error bootstrapping OpenTelemetry: {otel_err}", exc_info=True)

from aio_pika.abc import AbstractIncomingMessage
from langgraph.graph import StateGraph  # Import base StateGraph
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Import the orchestrator graph creator and state definition
from app.agents.orchestrator import OrchestratorState, create_orchestrator_graph

# Import the publisher function
from app.core.redis_client import (
    publish_analysis_update_to_redis,
)

# Assuming database setup is in app.database
from app.database import (
    AsyncSessionLocal,
    current_user_id_cv,
)

# Import new redis publisher
from app.graphql.types.common import AnalysisResult  # Import nested type

# , set_db_session_context # Placeholder for RLS context setter
from app.models.analysis_request import AnalysisRequest as AnalysisRequestModel

# Assuming status enum is defined here or in a shared location
from app.models.analysis_request import AnalysisRequestStatus

# Import queue client and constants
from app.services.queue_client import QUEUE_C1_INPUT, RABBITMQ_URL, QueueClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("worker_c1")

# --- Global Variables ---
# Compile the graph once when the worker starts
# Pass the SessionLocal factory during creation
COMPILED_C1_ORCHESTRATOR: StateGraph | None = None  # Initialize as None


# --- Database Context Management ---


@asynccontextmanager
async def get_db_session_with_context(
    user_id: uuid.UUID,
) -> AsyncGenerator[AsyncSession, None]:
    """Provides an ASYNC DB session with the RLS user context set."""
    session: AsyncSession = AsyncSessionLocal()
    rls_set_success = False
    if user_id:
        try:
            # Explicitly set RLS context variable for the transaction
            from sqlalchemy import text

            await session.execute(
                text("SET LOCAL app.current_user_id = :user_id"),
                {"user_id": str(user_id)},
            )
            # logger.debug(f"Set app.current_user_id = {user_id} for session")
            rls_set_success = True
        except Exception as e:
            logger.error(
                f"Failed to set RLS context for user {user_id}: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await session.rollback()
            await session.close()
            current_user_id_cv.set(None)
            raise
    else:
        # If no user_id, proceed without setting RLS
        pass

    # Only yield if RLS was set successfully or if no user_id was present
    if rls_set_success or not user_id:
        try:
            yield session
            await (
                session.commit()
            )  # Commit changes if context manager exits without error
        except SQLAlchemyError as e:
            logger.error(
                f"Database error during async session for user {user_id}: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await session.rollback()
            raise  # Re-raise SQLAlchemy errors
        except Exception as e:
            logger.error(
                f"Unexpected error during async session for user {user_id}: {e}",
                exc_info=True,
                extra={"props": {"user_id": str(user_id)}},
            )
            await session.rollback()
            raise  # Re-raise other exceptions
        finally:
            # Explicitly reset RLS context variable before closing
            if rls_set_success:  # Only reset if it was successfully set
                try:
                    await session.execute(text("RESET app.current_user_id;"))
                except Exception as e:
                    logger.warning(
                        f"Failed to reset RLS user ID for async session (User: {user_id}): {e}"
                    )
            await session.close()
            current_user_id_cv.set(None)  # Ensure context var is cleared


# --- Message Processing Logic ---


# Helper to map DB model to GQL dict for publishing
def map_db_to_gql_dict(req: AnalysisRequestModel) -> dict[str, Any]:
    result_gql = None
    if req.result:
        try:
            # Assuming req.result stores a dict compatible with AnalysisResult
            result_data = (
                json.loads(req.result) if isinstance(req.result, str) else req.result
            )
            # Temporary fix: Check if result_data is a dict before accessing keys
            if isinstance(result_data, dict):
                result_gql = AnalysisResult(
                    summary=result_data.get("summary"),
                    visualizations=result_data.get(
                        "visualizations"
                    ),  # TODO: Map visualizations if structure differs
                    raw_data=result_data.get("raw_data"),
                )
            else:
                # If result is not a dict (e.g., simple string from LLM), wrap it
                result_gql = AnalysisResult(summary=str(result_data))
        except Exception as e:
            logger.error(
                f"Failed to map result JSON/data to AnalysisResult GQL type: {e}"
            )
            # Handle error - maybe publish status without result?

    # TODO: Fetch proposed actions if they should be included in updates
    return {
        "id": str(req.id),  # Use simple ID for now, Relay GlobalID might need context
        "prompt": req.prompt,
        "status": req.status.value if hasattr(req.status, "value") else str(req.status),
        # "result": result_gql, # Pass the mapped result object/dict - needs fix if AnalysisResult isn't JSON serializable directly
        "result_summary": result_gql.summary if result_gql else None,
        "result_data": result_gql.rawData
        if result_gql
        else None,  # Example if rawData is needed
        "error_message": req.error_message,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "user_id": str(req.user_id),
        "proposed_actions": [],  # Placeholder
    }


async def process_message(message: AbstractIncomingMessage) -> bool:
    """Callback function to process a single message from the queue.
    Returns True if processing was successful (message should be ACKed),
    False otherwise (message should be NACKed/rejected).
    """
    # Initialize context vars for logging
    log_props = {"message_id": str(message.message_id)}
    analysis_request_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    try:
        body = message.body.decode()
        # Use log_props from the start
        logger.info("Received C1 message", extra={"props": log_props})
        logger.debug(f"Message Body: {body}", extra={"props": log_props})
        data = json.loads(body)

        user_id_str = data.get("user_id")
        analysis_request_id_str = data.get("analysis_request_id")
        prompt = data.get("prompt")
        shop_domain = data.get("shop_domain")  # Fetch shop_domain from message

        # Add IDs to log_props as soon as available
        log_props["analysis_request_id"] = analysis_request_id_str
        log_props["user_id"] = user_id_str

        if not all(
            [user_id_str, analysis_request_id_str, prompt, shop_domain]
        ):  # Check shop_domain too
            logger.error(
                "Invalid C1 message format",
                extra={"props": {**log_props, "raw_data": data}},
            )
            return False  # Indicate processing failure

        try:
            user_id = uuid.UUID(user_id_str)
            analysis_request_id = uuid.UUID(analysis_request_id_str)
            current_user_id_cv.set(user_id)  # Set context var before getting session
            # Ensure log_props has UUIDs as strings if needed by formatter
            log_props["analysis_request_id"] = str(analysis_request_id)
            log_props["user_id"] = str(user_id)
        except ValueError:
            logger.error(
                "Invalid UUID format in C1 message",
                extra={"props": {**log_props, "raw_data": data}},
            )
            current_user_id_cv.set(None)  # Clear context var on error
            return False  # Indicate processing failure

        logger.info("Processing C1 Task", extra={"props": log_props})

        # Process within an ASYNC DB session with RLS context
        async with get_db_session_with_context(user_id) as db:
            try:
                # Fetch the request using await and select
                from sqlalchemy.future import select  # Ensure select is imported

                stmt = select(AnalysisRequestModel).filter(
                    AnalysisRequestModel.id == analysis_request_id
                )
                result = await db.execute(stmt)
                analysis_request = result.scalars().first()

                if not analysis_request:
                    logger.warning(
                        "AnalysisRequest not found or access denied.",
                        extra={"props": log_props},
                    )
                    return False  # NACK - Do not retry

                # Publish initial PROCESSING status update
                initial_status = AnalysisRequestStatus.PROCESSING
                analysis_request.status = initial_status
                db.add(analysis_request)
                await db.flush()  # Use await for flush
                # Prepare data and publish
                gql_dict = map_db_to_gql_dict(analysis_request)
                await publish_analysis_update_to_redis(
                    str(analysis_request_id), gql_dict
                )
                logger.info(
                    f"Published status update: {initial_status.value}",
                    extra={"props": log_props},
                )

                # --- Call Agent Orchestrator (Real Implementation) ---
                logger.info("Invoking C1 Orchestrator", extra={"props": log_props})
                if COMPILED_C1_ORCHESTRATOR is None:
                    logger.error(
                        "Orchestrator graph not compiled.", extra={"props": log_props}
                    )
                    analysis_request.status = AnalysisRequestStatus.FAILED
                    analysis_request.error_message = (
                        "Worker configuration error: Orchestrator not compiled."
                    )
                    analysis_request.completed_at = datetime.now(
                        UTC
                    )  # Use timezone aware
                    db.add(analysis_request)
                    # No commit needed, context manager handles it on successful exit
                    return False  # NACK

                initial_state = OrchestratorState(
                    analysis_request_id=analysis_request_id,
                    user_id=user_id,
                    shop_domain=shop_domain,  # Use shop_domain from message
                    original_prompt=prompt,
                    plan=None,
                    dispatched_tasks=[],
                    aggregated_results={},
                    final_result=None,
                    error=None,
                )
                config = {
                    "configurable": {"thread_id": str(analysis_request_id)},
                    "metadata": {
                        "user_id": str(user_id),
                        "analysis_request_id": str(analysis_request_id),
                    },
                }

                final_state = None
                execution_error = None
                try:
                    final_state = await COMPILED_C1_ORCHESTRATOR.ainvoke(
                        input=initial_state, config=config
                    )
                    logger.info(
                        "Orchestrator finished successfully.",
                        extra={"props": log_props},
                    )

                except Exception as graph_err:
                    logger.exception(
                        "Critical error during graph execution",
                        extra={"props": log_props},
                    )
                    execution_error = graph_err

                # --- Update AnalysisRequest and Publish Final Update ---
                # Re-fetch or refresh the object within the same session
                # Use await for refresh
                await db.refresh(analysis_request)
                final_status_changed = False

                if execution_error or (final_state and final_state.get("error")):
                    if analysis_request.status != AnalysisRequestStatus.FAILED:
                        analysis_request.status = AnalysisRequestStatus.FAILED
                        error_msg = f"Orchestration failed: {execution_error or final_state.get('error')}"
                        analysis_request.error_message = (
                            (error_msg[:1000] + "...")
                            if len(error_msg) > 1000
                            else error_msg
                        )
                        logger.error(
                            "Marking AnalysisRequest as FAILED due to graph error/state.",
                            extra={"props": log_props},
                        )
                        final_status_changed = True
                elif final_state:
                    if analysis_request.status != AnalysisRequestStatus.FAILED:
                        analysis_request.status = AnalysisRequestStatus.COMPLETED
                        final_result = final_state.get(
                            "final_result", "No result generated."
                        )
                        try:
                            # Ensure result is JSON serializable before saving
                            if isinstance(final_result, (dict, list)):
                                analysis_request.result = json.dumps(
                                    final_result, default=str
                                )
                            elif isinstance(final_result, str):
                                # If it's already a string, decide if it needs JSON wrapping
                                # Let's store it as a simple JSON string for consistency
                                analysis_request.result = json.dumps(final_result)
                            else:
                                analysis_request.result = json.dumps(str(final_result))

                        except TypeError as json_err:
                            logger.error(
                                f"Failed to serialize final_result: {json_err}",
                                extra={"props": log_props},
                            )
                            analysis_request.result = json.dumps(
                                {"error": "Result serialization failed"}
                            )

                        logger.info(
                            "Marking AnalysisRequest as COMPLETED.",
                            extra={"props": log_props},
                        )
                        final_status_changed = True
                else:
                    logger.error(
                        "Graph invoke finished inconclusively.",
                        extra={"props": log_props},
                    )
                    if analysis_request.status != AnalysisRequestStatus.FAILED:
                        analysis_request.status = AnalysisRequestStatus.FAILED
                        analysis_request.error_message = (
                            "Internal error: Orchestrator finished inconclusively."
                        )
                        final_status_changed = True

                if analysis_request.status in [
                    AnalysisRequestStatus.COMPLETED,
                    AnalysisRequestStatus.FAILED,
                ]:
                    if analysis_request.completed_at is None:
                        analysis_request.completed_at = datetime.now(
                            UTC
                        )  # Use timezone aware
                        final_status_changed = True

                db.add(analysis_request)
                # Commit happens automatically via context manager exit

                # Publish final update if status changed
                if final_status_changed:
                    # Refresh again before mapping to ensure all changes are loaded
                    await db.refresh(analysis_request)
                    final_gql_dict = map_db_to_gql_dict(analysis_request)
                    await publish_analysis_update_to_redis(
                        str(analysis_request_id), final_gql_dict
                    )
                    logger.info(
                        f"Published final status update: {analysis_request.status.value}",
                        extra={"props": log_props},
                    )

                # ACK only if no critical error occurred during graph execution
                return not bool(execution_error)

            except SQLAlchemyError:
                logger.error(
                    "Database error processing C1 message",
                    exc_info=True,
                    extra={"props": log_props},
                )
                # Rollback handled by context manager
                return False  # NACK/Reject
            except Exception:
                logger.error(
                    "Unexpected error processing C1 message",
                    exc_info=True,
                    extra={"props": log_props},
                )
                # Rollback handled by context manager
                # Attempt to mark the request as failed in DB is difficult here as session is closed
                # Rely on DLQ or monitoring for these cases
                return False  # NACK/Reject

    except json.JSONDecodeError:
        logger.error(
            "Failed to decode JSON from message body", extra={"props": log_props}
        )
        return False  # Reject message permanently
    except Exception:
        final_log_props = log_props if analysis_request_id else {}
        logger.error(
            "Critical error in C1 process_message callback",
            exc_info=True,
            extra={"props": final_log_props},
        )
        return False  # Reject message permanently
    finally:
        # Ensure context var is reset even if initial parsing fails
        if "current_user_id_cv" in locals() and current_user_id_cv.get() is not None:
            current_user_id_cv.set(None)


# --- Worker Lifecycle ---

stop_event = asyncio.Event()


def handle_signal(sig, frame):
    logger.warning(
        f"Received signal {sig}, shutting down...", extra={"props": {"signal": sig}}
    )
    stop_event.set()


async def main():
    logger.info("Starting C1 Worker Service...")
    global COMPILED_C1_ORCHESTRATOR

    try:
        logger.info("Compiling C1 Orchestrator Graph...")
        # Pass the AsyncSessionLocal factory
        COMPILED_C1_ORCHESTRATOR = create_orchestrator_graph(
            db_session_factory=AsyncSessionLocal
        )
        logger.info("C1 Orchestrator Graph compiled successfully.")
    except Exception as compile_err:
        logger.critical(
            f"Failed to compile C1 orchestrator graph: {compile_err}", exc_info=True
        )
        return

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig, None)

    queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)
    consumer_started = False

    try:
        await queue_client.connect()
        await queue_client.consume_messages(
            queue_name=QUEUE_C1_INPUT, callback=process_message
        )
        consumer_started = True
        logger.info(f"C1 Worker consuming from queue: {QUEUE_C1_INPUT}")
        await stop_event.wait()

    except asyncio.CancelledError:
        logger.info("C1 Worker main task cancelled.")
    except Exception as e:
        logger.critical(f"C1 Worker encountered critical error: {e}", exc_info=True)
    finally:
        logger.info("C1 Worker shutting down...")
        await queue_client.close()
        logger.info("C1 Worker shutdown complete.")


if __name__ == "__main__":
    # OpenTelemetry bootstrap is now done conditionally at the top
    asyncio.run(main())
