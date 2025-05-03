import json
import logging
import uuid
from datetime import UTC, datetime
from functools import wraps
from typing import Any, TypedDict

from langchain_core.exceptions import OutputParserException
from langchain_core.load.serializable import JsonPlusSerializer
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointTuple
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.agents.constants import DEPARTMENT_QUEUES, AgentDepartment, AgentTaskStatus
from app.agents.prompts import format_aggregator_prompt, format_planner_prompt
from app.agents.utils import aget_llm_client
from app.database import get_async_db
from app.models.agent_task import AgentTask
from app.models.analysis_request import AnalysisRequest, AnalysisRequestStatus
from app.services.queue_client import RABBITMQ_URL, QueueClient

# Import CRUD functions
from app import crud

logger = logging.getLogger(__name__)

# --- LLM Client Initialization (Example) ---
# This should be configured properly, potentially shared across modules
# llm_client = ChatOpenAI(model="gpt-4-turbo-preview", openai_api_key=settings.OPENAI_API_KEY, temperature=0)

# --- LangGraph State Definition ---


class AgentTaskInfo(TypedDict):
    task_id: uuid.UUID
    department: AgentDepartment
    status: AgentTaskStatus
    input_payload: dict[str, Any]
    result: Any | None
    error_message: str | None


class OrchestratorState(TypedDict):
    analysis_request_id: uuid.UUID
    user_id: uuid.UUID
    shop_domain: str  # Needed if tools require it directly at C1 or for C2 tasks
    original_prompt: str
    plan: list[dict] | None  # Decomposed steps/tasks
    dispatched_tasks: list[AgentTaskInfo]  # Track tasks sent to C2 departments
    aggregated_results: dict[str, Any]  # Store results from completed C2 tasks
    final_result: str | None  # Final summary/response
    error: str | None  # Overall orchestration error
    # Potentially add current_task_index or similar for sequential plans
    # Add db_session_factory if passing via state (alternative to global/arg)
    # db_session_factory: Optional[Any] = None # Example


# --- Helper Functions (Update DB access to async) ---


def _get_log_props(
    state: OrchestratorState | None = None, task_info: AgentTaskInfo | None = None
) -> dict:
    """Helper to build consistent log properties."""
    props = {}
    if state:
        if state.get("analysis_request_id"):
            props["analysis_request_id"] = str(state["analysis_request_id"])
        if state.get("user_id"):
            props["user_id"] = str(state["user_id"])
    if task_info:
        if task_info.get("task_id"):
            props["task_id"] = str(task_info["task_id"])
        if task_info.get("department"):
            props["department"] = task_info["department"].value
        # Get context from payload if state not available
        if not props.get("analysis_request_id") and task_info.get("input_payload"):
            props["analysis_request_id"] = str(
                task_info["input_payload"].get("analysis_request_id")
            )
        if not props.get("user_id") and task_info.get("input_payload"):
            props["user_id"] = str(task_info["input_payload"].get("user_id"))
    return props


async def _aload_state_from_db(
    db: AsyncSession, analysis_request_id: uuid.UUID
) -> dict | None:
    log_props = {"analysis_request_id": str(analysis_request_id)}
    logger.info("Attempting to load state from DB async", extra={"props": log_props})
    # Use CRUD function
    request = await crud.analysis_request.aget(db, analysis_request_id)

    if request and request.agent_state:
        logger.info("Loaded state from DB async", extra={"props": log_props})
        try:
            if isinstance(request.agent_state, str):
                return json.loads(request.agent_state)
            return request.agent_state  # Assume JSONB is dict
        except json.JSONDecodeError:
            logger.error(
                "Failed to decode agent_state JSON", extra={"props": log_props}
            )
            return None
    logger.info("No existing state found in DB async", extra={"props": log_props})
    return None


async def _asave_state_to_db(
    db: AsyncSession, analysis_request_id: uuid.UUID, state: dict
):
    log_props = {"analysis_request_id": str(analysis_request_id)}
    logger.info("Saving state to DB async", extra={"props": log_props})
    try:
        # Use CRUD function
        await crud.analysis_request.update_agent_state(
            db, analysis_request_id=analysis_request_id, agent_state=state
        )
        logger.info("Successfully saved state async", extra={"props": log_props})
    except crud.analysis_request.NotFoundException:
        logger.error(
            "Cannot save state: Analysis Request not found.",
            extra={"props": log_props}
        )
    except Exception:
        await db.rollback() # Rollback async if update_agent_state doesn't handle it
        logger.exception("Failed to save state async", extra={"props": log_props})


async def _publish_to_department_queue(
    task_info: AgentTaskInfo, queue_client: QueueClient
):
    log_props = _get_log_props(task_info=task_info)
    queue_name = DEPARTMENT_QUEUES.get(task_info["department"])
    if not queue_name:
        logger.error(
            f"No queue defined for department: {task_info['department']}",
            extra={"props": log_props},
        )
        raise ValueError(f"Invalid department: {task_info['department']}")

    message_body = {
        "task_id": str(task_info["task_id"]),
        "analysis_request_id": str(task_info["input_payload"]["analysis_request_id"]),
        "user_id": str(task_info["input_payload"]["user_id"]),
        "shop_domain": task_info["input_payload"]["shop_domain"],
        "task_details": task_info["input_payload"]["task_details"],
    }
    logger.info(
        f"Attempting to publish message to queue '{queue_name}'",
        extra={"props": log_props},
    )
    try:
        await queue_client.publish_message(queue_name, message_body)
        logger.info(
            f"Successfully published message to queue '{queue_name}'",
            extra={"props": log_props},
        )
    except Exception:
        logger.exception(
            f"Failed to publish message to queue '{queue_name}'",
            extra={"props": log_props},
        )
        raise


async def _acreate_agent_task_record(
    db: AsyncSession, task_info: AgentTaskInfo
) -> uuid.UUID:
    log_props = _get_log_props(task_info=task_info)
    logger.info("Creating AgentTask record async", extra={"props": log_props})
    # Use CRUD function
    new_task = await crud.create_agent_task(
        db=db,
        analysis_request_id=task_info["input_payload"]["analysis_request_id"],
        user_id=task_info["input_payload"]["user_id"],
        task_type=task_info["department"].value,
        input_data=task_info["input_payload"]["task_details"],
    )
    # CRUD function handles commit/refresh
    log_props["task_id"] = str(new_task.id)
    logger.info("Created AgentTask record async", extra={"props": log_props})
    return new_task.id


async def _acheck_c2_task_status(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[AgentTaskStatus, Any | None, str | None]]:
    task_ids_str = [str(tid) for tid in task_ids]
    logger.info(f"Checking status for AgentTask IDs async: {task_ids_str}")
    if not task_ids:
        return {}
    # Use CRUD function
    tasks = await crud.get_agent_tasks_by_ids(db, task_ids)

    status_map = {
        task.id: (AgentTaskStatus(task.status), task.output_data, task.logs)
        for task in tasks
    }
    status_summary = {
        str(tid): status.value for tid, (status, _, _) in status_map.items()
    }
    logger.info(f"Status check result summary async: {status_summary}")
    return status_map


# --- LangGraph Nodes (Update DB access to async) ---


async def plan_request(state: OrchestratorState, db: AsyncSession) -> dict:
    log_props = _get_log_props(state=state)
    logger.info(
        f"Planning request async: '{state['original_prompt'][:50]}...'",
        extra={"props": log_props},
    )
    try:
        planner_llm = await aget_llm_client(
            db=db, user_id=state["user_id"], model_type="planner"
        )
        prompt = format_planner_prompt(state["original_prompt"])
        planner_chain = planner_llm | JsonOutputParser()
        logger.info(
            f"Invoking planner LLM ({planner_llm.model_name}) async.",
            extra={"props": log_props},
        )
        plan = await planner_chain.ainvoke(prompt)
        logger.info(
            f"Raw plan from LLM (first 100 chars) async: {str(plan)[:100]}...",
            extra={"props": log_props},
        )

        if not isinstance(plan, list):
            logger.error(
                "Planner LLM did not return list async", extra={"props": log_props}
            )
            raise ValueError("Planner output not list.")
        for step in plan:
            if "department" in step:
                try:
                    step["department"] = AgentDepartment(step["department"])
                except ValueError:
                    logger.error(
                        f"Invalid department in plan: {step['department']}",
                        extra={"props": log_props},
                    )
                    raise ValueError(
                        f"Invalid department specified in plan: {step['department']}"
                    )

        logger.info(
            f"Parsed plan with {len(plan)} steps async.", extra={"props": log_props}
        )
        return {"plan": plan, "dispatched_tasks": [], "aggregated_results": {}}

    except OutputParserException as e:
        logger.error(
            f"Failed to parse planner LLM output async: {e}", extra={"props": log_props}
        )
        return {"error": f"Parse fail: {e}"}
    except Exception as e:
        logger.exception(
            f"Error during planning async: {e}", extra={"props": log_props}
        )
        return {"error": f"Plan error: {e}"}


async def dispatch_tasks(state: OrchestratorState, db: AsyncSession) -> dict:
    log_props = _get_log_props(state=state)
    logger.info("Dispatching tasks based on plan async.", extra={"props": log_props})
    plan = state.get("plan")
    dispatched_tasks = state.get("dispatched_tasks", [])
    aggregated_results = state.get("aggregated_results", {})
    newly_dispatched = []

    if not plan:
        logger.warning("No plan available async.", extra={"props": log_props})
        return {"error": "Plan missing."}

    next_step_index = len(dispatched_tasks)
    if next_step_index < len(plan):
        task_to_dispatch = plan[next_step_index]
        step_number = task_to_dispatch.get("step", next_step_index + 1)
        step_log_props = {
            **log_props,
            "step": step_number,
            "department": task_to_dispatch["department"].value,
        }
        logger.info(
            f"Preparing to dispatch task for step {step_number} async",
            extra={"props": step_log_props},
        )

        task_details = task_to_dispatch["task_details"]
        if (
            task_to_dispatch["department"] == AgentDepartment.QUANTITATIVE_ANALYSIS
            and next_step_index > 0
        ):
            previous_task_id_str = str(dispatched_tasks[next_step_index - 1]["task_id"])
            previous_result = aggregated_results.get(previous_task_id_str)
            if previous_result:
                logger.info(
                    f"Injecting result from task {previous_task_id_str}",
                    extra={"props": step_log_props},
                )
                task_details["retrieved_data"] = previous_result
            else:
                logger.error(
                    f"Missing result from previous task {previous_task_id_str}",
                    extra={"props": step_log_props},
                )
                return {
                    "error": f"Dependency error: Result from task {previous_task_id_str} not found."
                }

        input_payload = {
            "analysis_request_id": state["analysis_request_id"],
            "user_id": state["user_id"],
            "shop_domain": state["shop_domain"],
            "task_details": task_details,
        }

        task_info = AgentTaskInfo(
            task_id=uuid.uuid4(),
            department=task_to_dispatch["department"],
            status=AgentTaskStatus.PENDING,
            input_payload=input_payload,
            result=None,
            error_message=None,
        )

        queue_client = QueueClient(rabbitmq_url=RABBITMQ_URL)
        try:
            await queue_client.connect()
            task_log_props = {}  # Define before try block
            try:
                db_task_id = await _acreate_agent_task_record(db, task_info)
                task_info["task_id"] = db_task_id
                task_log_props = {**step_log_props, "task_id": str(db_task_id)}

                await _publish_to_department_queue(task_info, queue_client)
                newly_dispatched.append(task_info)
                logger.info(
                    "Successfully dispatched task async",
                    extra={"props": task_log_props},
                )

            except Exception as e:
                logger.exception(
                    "Failed to dispatch task async", extra={"props": task_log_props}
                )
                return {"error": f"Failed to dispatch task: {e}"}
        finally:
            await queue_client.close()
    else:
        logger.info(
            "All planned tasks already dispatched async.", extra={"props": log_props}
        )

    return {"dispatched_tasks": dispatched_tasks + newly_dispatched}


async def check_task_status(state: OrchestratorState, db: AsyncSession) -> dict:
    log_props = _get_log_props(state=state)
    logger.info(
        "Checking status of dispatched tasks async.", extra={"props": log_props}
    )
    dispatched_tasks = state.get("dispatched_tasks", [])
    aggregated_results = state.get("aggregated_results", {})

    task_ids_to_check = [
        t["task_id"]
        for t in dispatched_tasks
        if t["status"]
        in [AgentTaskStatus.PENDING, AgentTaskStatus.RUNNING, AgentTaskStatus.RETRYING]
    ]

    if not task_ids_to_check:
        logger.info("No active tasks to check async.", extra={"props": log_props})
        return {
            "dispatched_tasks": dispatched_tasks,
            "aggregated_results": aggregated_results,
        }

    status_map = await _acheck_c2_task_status(db, task_ids_to_check)
    updated_dispatched_tasks = []
    state_changed = False

    for task_info in dispatched_tasks:
        task_log_props = {**log_props, "task_id": str(task_info["task_id"])}
        if task_info["task_id"] in status_map:
            new_status, new_result, new_error = status_map[task_info["task_id"]]

            status_updated = new_status != task_info["status"]
            result_updated = json.dumps(new_result, default=str) != json.dumps(
                task_info.get("result"), default=str
            )
            error_updated = new_error != task_info.get("error_message")

            if status_updated or result_updated or error_updated:
                state_changed = True
                logger.info(
                    f"Task {task_info['task_id']} state updated async. Status: {task_info['status']}->{new_status}, Result: {result_updated}, Error: {error_updated}",
                    extra={"props": task_log_props},
                )
                task_info["status"] = new_status
                task_info["result"] = new_result
                task_info["error_message"] = new_error

                if new_status == AgentTaskStatus.COMPLETED and new_result is not None:
                    aggregated_results[str(task_info["task_id"])] = new_result
                    logger.info(
                        "Stored result for completed task async.",
                        extra={"props": task_log_props},
                    )
                elif new_status == AgentTaskStatus.FAILED:
                    aggregated_results[str(task_info["task_id"])] = {
                        "error": new_error
                        or "Task failed without specific error message"
                    }
                    logger.warning(
                        "Stored error for failed task async.",
                        extra={"props": task_log_props},
                    )

        updated_dispatched_tasks.append(task_info)

    if state_changed:
        logger.info(
            "Task states or results changed, graph state updated async.",
            extra={"props": log_props},
        )

    return {
        "dispatched_tasks": updated_dispatched_tasks,
        "aggregated_results": aggregated_results,
    }


async def aggregate_results(state: OrchestratorState, db: AsyncSession) -> dict:
    log_props = _get_log_props(state=state)
    logger.info("Aggregating results async.", extra={"props": log_props})
    aggregated_results = state.get("aggregated_results", {})
    try:
        aggregator_llm = await aget_llm_client(
            db=db, user_id=state["user_id"], model_type="aggregator"
        )
        prompt = format_aggregator_prompt(
            user_prompt=state["original_prompt"],
            aggregated_results=aggregated_results,
        )
        aggregator_chain = aggregator_llm | StrOutputParser()
        logger.info(
            f"Invoking aggregator LLM ({aggregator_llm.model_name}) async.",
            extra={"props": log_props},
        )
        final_summary = await aggregator_chain.ainvoke(prompt)
        logger.info(
            f"Generated final result (first 200 chars) async: {final_summary[:200]}...",
            extra={"props": log_props},
        )
        return {"final_result": final_summary}

    except Exception as e:
        logger.exception(
            f"Error during result aggregation async: {e}", extra={"props": log_props}
        )
        fallback_summary = f"Analysis completed, but failed to generate final summary. Error: {e}\nResults: {json.dumps(aggregated_results, indent=2, default=str)}"
        return {"final_result": fallback_summary, "error": f"Aggregation failed: {e}"}


# --- LangGraph Conditional Edges ---


def should_continue_dispatch(state: OrchestratorState) -> str:
    """Determines if more tasks need to be dispatched or if we should check status."""
    plan = state.get("plan", [])
    dispatched_tasks = state.get("dispatched_tasks", [])
    if state.get("error"):
        return "handle_error"
    if len(dispatched_tasks) < len(plan):
        return "dispatch_tasks"  # More tasks in the plan to dispatch
    else:
        # Check if all dispatched tasks are finished (completed or failed)
        all_finished = all(
            t["status"] in [AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED]
            for t in dispatched_tasks
        )
        if all_finished:
            logger.info(
                f"[AR: {state['analysis_request_id']}] All dispatched tasks are finished. Moving to decide_next_step."
            )
            return "check_task_status"  # Go to decision node as all dispatched tasks are done
        else:
            logger.info(
                f"[AR: {state['analysis_request_id']}] All planned tasks dispatched, but some are still running. Checking status."
            )
            return "check_task_status"  # Still need to check status of running tasks


def decide_next_step(state: OrchestratorState) -> str:
    """Checks if all dispatched tasks are complete or if errors occurred."""
    analysis_request_id = state["analysis_request_id"]
    dispatched_tasks = state.get("dispatched_tasks", [])
    if state.get("error"):
        return "handle_error"  # Check for C1 errors first
    if not dispatched_tasks and not state.get("plan"):
        logger.warning(
            f"[AR: {analysis_request_id}] No plan and no tasks. Likely planning error."
        )
        return "handle_error"  # Error if no plan and no tasks
    if not dispatched_tasks and state.get("plan"):
        logger.info(
            f"[AR: {analysis_request_id}] Plan exists but no tasks dispatched yet. Should go back to dispatch?"
        )
        # This case shouldn't be hit if should_continue_dispatch is correct, but as a fallback:
        return "dispatch_tasks"

    all_done = True
    has_errors = False
    for task in dispatched_tasks:
        if task["status"] == AgentTaskStatus.FAILED:
            has_errors = True
            # Don't break here, check all tasks
        elif task["status"] not in [AgentTaskStatus.COMPLETED]:
            all_done = False
            # If any task is not completed/failed, we are not done.

    if has_errors:
        # Check if *all* tasks failed or just some
        all_failed = all(
            t["status"] == AgentTaskStatus.FAILED for t in dispatched_tasks
        )
        if all_failed:
            logger.error(f"[AR: {analysis_request_id}] All dispatched tasks failed.")
        else:
            logger.warning(
                f"[AR: {analysis_request_id}] One or more tasks failed, but others may have completed."
            )
        # Consider if partial results should still go to aggregation or always error out
        # For now, any failure leads to handle_error
        return "handle_error"
    elif all_done:
        logger.info(f"[AR: {analysis_request_id}] All tasks completed successfully.")
        return "aggregate_results"
    else:
        logger.info(
            f"[AR: {analysis_request_id}] Tasks still pending/running. Checking status again."
        )
        return "check_task_status"  # Tasks still running, loop back to check status


async def handle_error(state: OrchestratorState, db: AsyncSession) -> dict:
    """Node to handle errors during orchestration async."""
    # Consolidate error checking
    log_props = _get_log_props(state=state)
    error_message = state.get("error", "Unknown orchestration error")  # C1 error
    failed_task_errors = []
    for task in state.get("dispatched_tasks", []):
        if task["status"] == AgentTaskStatus.FAILED:
            failed_task_errors.append(
                f"Task {task['task_id']} ({task['department'].value}) failed: {task.get('error_message', 'No details')}"
            )

    if failed_task_errors:
        error_message += " | Task Errors: " + " ; ".join(failed_task_errors)

    analysis_request_id = state["analysis_request_id"]
    logger.error(
        f"Orchestration failed async: {error_message}", extra={"props": log_props}
    )
    # Update AnalysisRequest status to FAILED in DB
    try:
        # Use CRUD function
        await crud.analysis_request.update_status_and_error(
            db,
            analysis_request_id=analysis_request_id,
            status=AnalysisRequestStatus.FAILED,
            error_message=error_message,
            set_completed_at=True,
        )
        # CRUD function handles commit
    except crud.analysis_request.NotFoundException:
        logger.error(
            f"[AR: {analysis_request_id}] Analysis Request not found for status update on error.",
            extra={"props": log_props},
        )
    except Exception:
        # Rollback might not be needed if crud func handles it, but belt-and-suspenders
        await db.rollback()
        logger.exception(
            f"[AR: {analysis_request_id}] Failed to update AnalysisRequest status on error async",
            extra={"props": log_props},
        )

    # The state itself already contains the error, graph terminates here.
    # Return the updated state including the consolidated error message
    return {"error": error_message}


# --- Graph Definition (Update node wrapper) ---


# Async node wrapper
async def node_wrapper_async(func, db_session_factory):
    @wraps(func)
    async def wrapped(state: OrchestratorState):
        # Use async context manager for DB session
        user_id = state.get("user_id")
        if not user_id:
            logger.error("User ID missing in state, cannot proceed.")
            # Handle error appropriately, maybe return error state or raise
            return {"error": "User context missing in orchestration state."}

        # REMOVED: Explicit context var handling - handled by get_async_db_session_with_rls
        # from app.database import current_user_id_cv
        # cv_token = current_user_id_cv.set(user_id)
        try:
            # Use the RLS-enabled async context manager from database.py
            from app.database import get_async_db_session_with_rls # Ensure import

            async with get_async_db_session_with_rls(user_id) as db:
                # No need to set RLS here, get_async_db handles it
                # Pass the async session to the node function
                result = await func(state, db)
                # Commits are handled by get_async_db context manager
                return result
        except Exception as e:
            logger.exception(f"Error executing node {func.__name__}: {e}")
            # Propagate the error or return an error state
            # Returning error state to be handled by graph's error handling edge
            return {"error": f"Node {func.__name__} failed: {e}"}
        # REMOVED: Explicit context var reset - handled by get_async_db_session_with_rls
        # finally:
        #     # Reset context var
        #     current_user_id_cv.reset(cv_token)

    return wrapped


# Graph definition uses async node wrapper
def create_orchestrator_graph(db_session_factory) -> StateGraph:
    """Creates and compiles the LangGraph orchestrator with checkpointing using AsyncSession factory."""
    workflow = StateGraph(OrchestratorState)

    # Wrap nodes with the async session factory wrapper
    workflow.add_node(
        "plan_request", node_wrapper_async(plan_request, db_session_factory)
    )
    workflow.add_node(
        "dispatch_tasks", node_wrapper_async(dispatch_tasks, db_session_factory)
    )
    workflow.add_node(
        "check_task_status", node_wrapper_async(check_task_status, db_session_factory)
    )
    workflow.add_node(
        "aggregate_results", node_wrapper_async(aggregate_results, db_session_factory)
    )
    workflow.add_node(
        "handle_error", node_wrapper_async(handle_error, db_session_factory)
    )

    # Define edges
    workflow.set_entry_point("plan_request")

    # If planning fails directly, go to error handling
    workflow.add_conditional_edges(
        "plan_request",
        lambda state: "handle_error" if state.get("error") else "dispatch_tasks",
        {"dispatch_tasks": "dispatch_tasks", "handle_error": "handle_error"},
    )
    # workflow.add_edge("plan_request", "dispatch_tasks") # Original simpler edge

    workflow.add_conditional_edges(
        "dispatch_tasks",
        should_continue_dispatch,
        {
            "dispatch_tasks": "dispatch_tasks",  # Loop to dispatch next task
            "check_task_status": "check_task_status",  # Move to check status
            "handle_error": "handle_error",  # Go to error if dispatch failed
        },
    )

    workflow.add_conditional_edges(
        "check_task_status",
        decide_next_step,
        {
            "check_task_status": "check_task_status",  # Loop back to check again
            "aggregate_results": "aggregate_results",  # All done, aggregate
            "handle_error": "handle_error",  # Task failed
            "dispatch_tasks": "dispatch_tasks",  # Fallback added
        },
    )

    # If aggregation fails, go to error handling
    workflow.add_conditional_edges(
        "aggregate_results",
        lambda state: "handle_error" if state.get("error") else END,
        {END: END, "handle_error": "handle_error"},
    )
    # workflow.add_edge("aggregate_results", END) # Original simpler edge
    workflow.add_edge("handle_error", END)

    # Compile the graph with the checkpointer
    checkpointer = SqlAlchemyCheckpointAsync(db_session_factory=db_session_factory)
    compiled_graph = workflow.compile(checkpointer=checkpointer)
    return compiled_graph  # Return the compiled graph


# --- Checkpointer (Async SQLAlchemy Implementation) ---


class JsonPlusStateSerializer(JsonPlusSerializer):
    """Custom serializer to handle specific types if needed."""

    def _default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, AgentDepartment) or isinstance(obj, AgentTaskStatus):
            return obj.value
        # Let base class handle others, or add more types
        return super()._default(obj)


class SqlAlchemyCheckpointAsync(BaseCheckpointSaver):
    serializer = JsonPlusStateSerializer()

    def __init__(self, db_session_factory):
        self.db_session_factory = db_session_factory
        super().__init__()

    # Update get_tuple to be async
    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id_str = config["configurable"].get("thread_id")
        if not thread_id_str:
            logger.error("Checkpoint GET failed: 'thread_id' not found in config.")
            return None
        logger.debug(
            f"Checkpoint GET tuple async called for thread_id: {thread_id_str}"
        )
        try:
            async with self.db_session_factory() as db: # Use async session
                # Load state using CRUD
                saved = await crud.analysis_request.get_agent_state(
                    db, uuid.UUID(thread_id_str)
                )
                if saved:
                    checkpoint_dict = self.serializer.loads(
                        json.dumps(saved["checkpoint"])
                    )  # Deserialize dict
                    # Construct Checkpoint object - schema might vary slightly by langgraph version
                    checkpoint = Checkpoint(
                        v=1,
                        ts=datetime.now(UTC).isoformat(),  # Placeholder timestamp
                        channel_values=checkpoint_dict.get(
                            "channel_values", checkpoint_dict
                        ),  # Adapt based on actual structure
                        channel_versions={},  # Placeholder
                        versions_seen={},  # Placeholder
                    )
                    parent_config = saved.get("parent_config")
                    return CheckpointTuple(
                        config=config,
                        checkpoint=checkpoint,
                        parent_config=parent_config,
                    )
                return None
        except Exception as e:
            logger.exception(
                f"Checkpoint GET tuple async error for thread_id {thread_id_str}: {e}"
            )
            return None

    # Update put to be async
    async def aput(self, config: dict[str, Any], checkpoint: Checkpoint) -> None:
        thread_id_str = config["configurable"].get("thread_id")
        if not thread_id_str:
            logger.error("Checkpoint PUT failed: 'thread_id' not found in config.")
            return
        logger.debug(f"Checkpoint PUT async called for thread_id: {thread_id_str}")
        try:
            # Serialize Checkpoint object to dict
            # LangGraph internal structure might differ slightly, adapt serialization as needed
            checkpoint_dict = {
                "channel_values": checkpoint.channel_values,
                # Include other necessary fields from Checkpoint if required by deserialization
            }
            serialized_checkpoint = self.serializer.dumps(checkpoint_dict)
            state_to_save = {
                "checkpoint": json.loads(serialized_checkpoint),
                # Include parent_config if needed
                # "parent_config": checkpoint.parent_config, # Check if parent_config is part of Checkpoint or outer config
            }
            async with self.db_session_factory() as db: # Use async session
                # Save state using CRUD
                await crud.analysis_request.update_agent_state(
                    db, analysis_request_id=uuid.UUID(thread_id_str), agent_state=state_to_save
                )
        except crud.analysis_request.NotFoundException:
             logger.error(
                f"Checkpoint PUT async failed: Analysis Request {thread_id_str} not found."
            )
        except Exception as e:
            logger.exception(
                f"Checkpoint PUT async error for thread_id {thread_id_str}: {e}"
            )

    # Implement sync methods if BaseCheckpointSaver requires them (wrap async calls)
    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        # return asyncio.run(self.aget_tuple(config)) # Avoid asyncio.run if possible
        # Or raise NotImplementedError if sync access isn't supported
        raise NotImplementedError(
            "Sync get_tuple not supported by SqlAlchemyCheckpointAsync"
        )

    def put(self, config: dict[str, Any], checkpoint: Checkpoint) -> None:
        # return asyncio.run(self.aput(config, checkpoint))
        raise NotImplementedError("Sync put not supported by SqlAlchemyCheckpointAsync")


# --- Main Invocation Logic (Placeholder in Worker) ---

# async def process_c1_input_message(message_body: dict):
#     analysis_request_id_str = message_body.get('analysis_request_id')
#     user_id_str = message_body.get('user_id')
#     prompt = message_body.get('prompt')
#     shop_domain = message_body.get('shop_domain') # Assuming shop_domain is needed and passed
#
#     if not all([analysis_request_id_str, user_id_str, prompt, shop_domain]):
#         logger.error(f"Worker received incomplete C1 input message: {message_body}")
#         # Potentially Nack the message or move to DLQ
#         return
#
#     analysis_request_id = uuid.UUID(analysis_request_id_str)
#     user_id = uuid.UUID(user_id_str)
#
#     logger.info(f"[Worker] Starting orchestration for Analysis Request: {analysis_request_id}")
#
#     # --- Get DB Session Factory & Checkpointer ---
#     db_session_factory = SessionLocal # Your actual factory
#     checkpointer = SqlAlchemyCheckpoint(db_session_factory=db_session_factory)
#     # --- Compile Graph ---
#     # Compile the graph with the checkpointer
#     # Consider compiling once globally if checkpointer is thread-safe or managed per request
#     graph = create_orchestrator_graph().compile(checkpointer=checkpointer)
#
#     # --- Initial State & Config ---
#     initial_state = OrchestratorState(
#         analysis_request_id=analysis_request_id,
#         user_id=user_id,
#         shop_domain=shop_domain,
#         original_prompt=prompt,
#         plan=None,
#         dispatched_tasks=[],
#         aggregated_results={},
#         final_result=None,
#         error=None
#     )
#     config = {"configurable": {"thread_id": str(analysis_request_id)}}
#
#     # --- Execute Graph ---
#     final_state = None
#     try:
#         # Run the graph. LangGraph handles loading/saving state via checkpointer.
#         # Use graph.ainvoke for async execution if nodes/checkpointer support it
#         final_state = await graph.ainvoke(initial_state, config=config) # Assuming async invoke
#         logger.info(f"[AR: {analysis_request_id}] Orchestration finished.")
#         # Final state is implicitly saved by checkpointer on successful completion
#
#     except Exception as e:
#         logger.exception(f"[AR: {analysis_request_id}] Critical error during graph execution: {e}")
#         # State might be partially saved by checkpointer. Mark request as failed manually.
#         try:
#             with db_session_factory() as db:
#                 request = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_request_id).first()
#                 if request and request.status != 'failed': # Avoid overwriting specific failure states
#                     request.status = 'failed'
#                     error_msg = f"Graph execution error: {e}"
#                     truncated_error = (error_msg[:1000] + '...') if len(error_msg) > 1000 else error_msg
#                     request.result = json.dumps({"error": truncated_error})
#                     db.commit()
#         except Exception as db_err:
#             logger.exception(f"[AR: {analysis_request_id}] Failed to update AnalysisRequest status after graph error: {db_err}")
#
#     # --- Final DB Update (Status/Result) ---
#     # Update DB based on the final state, only if no critical error occurred during invoke
#     if final_state:
#          try:
#              with db_session_factory() as db:
#                  request = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_request_id).first()
#                  if request:
#                      if final_state.get('error'):
#                          if request.status != 'failed': # Don't overwrite if already marked failed by handle_error node
#                             request.status = 'failed'
#                             error_msg = final_state['error']
#                             truncated_error = (error_msg[:1000] + '...') if len(error_msg) > 1000 else error_msg
#                             request.result = json.dumps({"error": truncated_error})
#                      elif request.status != 'failed': # Ensure we don't mark a failed request as completed
#                          request.status = 'completed'
#                          final_result = final_state.get('final_result', 'No result generated.')
#                          request.result = json.dumps(final_result, default=str) # Store final result
#                      db.commit()
#                      logger.info(f"[AR: {analysis_request_id}] Final AnalysisRequest status updated in DB.")
#                  else:
#                      logger.error(f"[AR: {analysis_request_id}] Could not find request in DB for final update.")
#          except Exception as e:
#               logger.exception(f"[AR: {analysis_request_id}] Failed during final DB update: {e}")
#
#     logger.info(f"[Worker] Finished processing for Analysis Request: {analysis_request_id}")
