import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel  # Added for type hinting
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from app.agents.constants import AgentTaskStatus
from app.core.config import settings  # Import settings for defaults and keys
from app.models.agent_task import AgentTask  # Assuming model exists at this path
from app.models.user_preferences import UserPreferences  # Import UserPreferences

logger = logging.getLogger(__name__)

# Default models (using provider prefix)
DEFAULT_TOOL_LLM_MODEL = settings.DEFAULT_TOOL_MODEL  # "openai:gpt-4o-mini"
DEFAULT_PLANNER_LLM_MODEL = (
    settings.DEFAULT_PLANNER_MODEL
)  # "anthropic:claude-3-5-sonnet-20240620"
DEFAULT_AGGREGATOR_LLM_MODEL = (
    settings.DEFAULT_AGGREGATOR_MODEL
)  # "google:gemini-1.5-pro-latest"
DEFAULT_CREATIVE_LLM_MODEL = (
    settings.DEFAULT_CREATIVE_MODEL
)  # Added for recommendations


# Revert this to sync to match runnable usage
# async def update_agent_task_status(...):
# Change to async and expect AsyncSession
async def update_agent_task_status(
    db: AsyncSession,  # Use AsyncSession
    task_id: uuid.UUID,
    status: AgentTaskStatus,
    result: Any | None = None,
    error_message: str | None = None,
    retry_count: int | None = None,
):
    """Updates the status and optionally other fields of an AgentTask record asynchronously."""
    log_props = {"task_id": str(task_id), "new_status": status.value}
    try:
        # Use async session methods
        stmt = select(AgentTask).filter(AgentTask.id == task_id)
        res = await db.execute(stmt)
        agent_task = res.scalars().first()
        # agent_task = db.query(AgentTask).filter(AgentTask.id == task_id).first()

        if agent_task:
            agent_task.status = status.value
            if result is not None:
                # Ensure result is JSON serializable
                try:
                    agent_task.output_data = json.loads(json.dumps(result, default=str))
                except (TypeError, json.JSONDecodeError) as json_err:
                    logger.warning(
                        f"Failed to serialize result for task {task_id}: {json_err}. Storing as string."
                    )
                    agent_task.output_data = {"raw_output": str(result)}
            if error_message is not None:
                agent_task.logs = (
                    (agent_task.logs + "\n---\n" if agent_task.logs else "")
                    + error_message[:2000]  # Append error, limit size
                )
            if retry_count is not None:
                agent_task.retry_count = retry_count

            # Update timestamp based on status
            now = datetime.now(UTC)
            if status == AgentTaskStatus.RUNNING and not agent_task.started_at:
                agent_task.started_at = now
            elif status in [AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED]:
                agent_task.completed_at = now

            db.add(agent_task)
            await db.commit()  # Commit async
            await db.refresh(agent_task)  # Refresh async
            # logger.info(f"Updated AgentTask status", extra={"props": log_props})
        else:
            logger.warning(
                "AgentTask not found for status update.", extra={"props": log_props}
            )
    except Exception:
        logger.exception(
            "Failed to update AgentTask status", extra={"props": log_props}
        )
        await db.rollback()  # Rollback async
        # Re-raise the exception so the caller knows the update failed
        raise


# --- LLM Client Helper ---

# Removed client cache as instantiation is cheap and avoids potential state issues
# LLM_CLIENT_CACHE = {} # Simple in-memory cache for LLM clients


# Modify to accept either Session or AsyncSession, prefer AsyncSession logic
async def aget_llm_client(
    db: Session | AsyncSession, user_id: uuid.UUID, model_type: str = "tool"
) -> BaseChatModel:
    """Retrieves the appropriate LLM client based on user preferences or defaults asynchronously."""
    preferred_model = None
    prefs = None
    try:
        # Check if session is async or sync
        if isinstance(db, AsyncSession):
            # Load preferences asynchronously
            stmt = select(UserPreferences).filter(UserPreferences.user_id == user_id)
            result = await db.execute(stmt)
            prefs = result.scalars().first()
        elif isinstance(db, Session):
            # Load preferences synchronously
            prefs = (
                db.query(UserPreferences)
                .filter(UserPreferences.user_id == user_id)
                .first()
            )
        else:
            logger.error("Invalid DB session type passed to get_llm_client")

        if prefs:
            # Get the specific model preference based on type
            if model_type == "planner":
                preferred_model = prefs.preferred_planner_model
            elif model_type == "aggregator":
                preferred_model = prefs.preferred_aggregator_model
            elif model_type == "tool":
                preferred_model = prefs.preferred_tool_model
            elif model_type == "creative":
                preferred_model = prefs.preferred_creative_model
            else:
                preferred_model = (
                    prefs.preferred_tool_model
                )  # Default to tool model preference

    except Exception as db_err:
        logger.error(f"Failed to query UserPreferences for {user_id}: {db_err}")

    # Determine default model based on type
    default_model_map = {
        "tool": settings.DEFAULT_TOOL_MODEL,
        "planner": settings.DEFAULT_PLANNER_MODEL,
        "aggregator": settings.DEFAULT_AGGREGATOR_MODEL,
        "creative": settings.DEFAULT_CREATIVE_MODEL,
    }
    default_model_for_type = default_model_map.get(
        model_type, settings.DEFAULT_TOOL_MODEL
    )

    target_model_id = preferred_model or default_model_for_type

    logger.info(
        f"Using LLM model: {target_model_id} for type '{model_type}' (User: {user_id})"
    )

    try:
        provider, model_name = target_model_id.split(":", 1)
    except ValueError:
        logger.error(
            f"Invalid LLM model format: {target_model_id}. Falling back to default."
        )
        provider, model_name = settings.DEFAULT_TOOL_MODEL.split(":", 1)

    # Instantiate client based on provider using OpenRouter keys from settings
    if provider == "openai":
        return ChatOpenAI(
            model=model_name,
            openai_api_key=settings.OPENROUTER_API_KEY,
            openai_api_base=settings.OPENROUTER_BASE_URL,
            temperature=0.1,  # Example temperature
        )
    elif provider == "anthropic":
        return ChatAnthropic(
            model=model_name,
            anthropic_api_key=settings.OPENROUTER_API_KEY,
            anthropic_api_url=f"{settings.OPENROUTER_BASE_URL.strip('/')}/anthropic",  # Ensure no double slash
            temperature=0.1,
        )
    elif provider == "google":
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.OPENROUTER_API_KEY,
            # Ensure the base URL is correctly formatted for Google models via OpenRouter if needed
            # This might require specific handling or might just work via headers
            temperature=0.1,
        )
    else:
        logger.warning(
            f"Unsupported LLM provider: {provider}. Falling back to default OpenAI."
        )
        provider, model_name = settings.DEFAULT_TOOL_MODEL.split(":", 1)
        return ChatOpenAI(
            model=model_name,
            openai_api_key=settings.OPENROUTER_API_KEY,
            openai_api_base=settings.OPENROUTER_BASE_URL,
            temperature=0.1,
        )


# --- Other utility functions can be added below ---
