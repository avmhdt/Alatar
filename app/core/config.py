import os

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file if it exists
load_dotenv()


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")

    # JWT
    JWT_SECRET: str = Field(..., env="JWT_SECRET")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # Application Secret (for encryption etc.)
    APP_SECRET_KEY: str = Field(
        ..., env="APP_SECRET_KEY"
    )  # Must be 32 url-safe base64-encoded bytes

    # Frontend URL (for redirects)
    FRONTEND_URL: str = Field(..., env="FRONTEND_URL")

    # Shopify OAuth
    SHOPIFY_API_KEY: str | None = Field(None, env="SHOPIFY_API_KEY")
    SHOPIFY_API_SECRET: str | None = Field(None, env="SHOPIFY_API_SECRET")
    SHOPIFY_APP_URL: str | None = Field(
        None, env="SHOPIFY_APP_URL"
    )  # Base URL of your app
    # Define required scopes (adjust as needed based on system_design.md Section 4)
    SHOPIFY_SCOPES: list[str] = Field(
        default=[
            "read_products",
            "read_orders",
            "read_customers",
            "read_inventory",
            "read_locations",
            # Add write scopes later if/when needed by HITL actions
            # "write_products",
            # "write_orders",
        ],
        env="SHOPIFY_SCOPES",
    )

    # LangSmith / OpenTelemetry (Optional for now)
    LANGSMITH_API_KEY: str | None = Field(None, env="LANGSMITH_API_KEY")
    LANGSMITH_PROJECT: str | None = Field("Alatar", env="LANGSMITH_PROJECT")
    # OPENTELEMETRY_ENABLED flag to control setup
    OPENTELEMETRY_ENABLED: bool = Field(False, env="OPENTELEMETRY_ENABLED")
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = Field(
        None, env="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    # LLM Provider (OpenRouter)
    LLM_PROVIDER: str = Field(
        "openrouter", env="LLM_PROVIDER"
    )  # Could allow 'openai' in future
    OPENROUTER_API_KEY: str | None = Field(None, env="OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL: str = Field(
        "https://openrouter.ai/api/v1", env="OPENROUTER_BASE_URL"
    )
    # Default models for different tasks (can be overridden by tenant preferences later)
    DEFAULT_PLANNER_MODEL: str = Field(
        "openai/gpt-4-turbo-preview", env="DEFAULT_PLANNER_MODEL"
    )
    DEFAULT_AGGREGATOR_MODEL: str = Field(
        "openai/gpt-4-turbo-preview", env="DEFAULT_AGGREGATOR_MODEL"
    )
    DEFAULT_TOOL_MODEL: str = Field(
        "openai/gpt-4o",
        env="DEFAULT_TOOL_MODEL",  # For tool usage, analysis
    )
    DEFAULT_CREATIVE_MODEL: str = Field(
        "openai/gpt-4o",
        env="DEFAULT_CREATIVE_MODEL",  # For tasks like recommendations
    )

    # Cache Settings
    SHOPIFY_CACHE_TTL_SECONDS: int = Field(
        default=3600,
        env="SHOPIFY_CACHE_TTL_SECONDS",  # Default 1 hour
    )

    # Allow CORS for frontend development
    CORS_ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:3000"], env="CORS_ALLOWED_ORIGINS"
    )  # Adjust as needed

    # pgcrypto Symmetric Key (Load from environment)
    PGCRYPTO_SYM_KEY: str = Field(..., env="PGCRYPTO_SYM_KEY") # Mandatory key for pgcrypto functions

    # Redis configuration
    REDIS_HOST: str = Field(..., env="REDIS_HOST")
    REDIS_PORT: int = Field(..., env="REDIS_PORT")
    REDIS_DB: int = Field(..., env="REDIS_DB")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow reading scopes as comma-separated string from env var
        fields = {
            "SHOPIFY_SCOPES": {"env_separator": ","},
            "CORS_ALLOWED_ORIGINS": {"env_separator": ","},
        }


settings = Settings()

# Example usage: print(settings.DATABASE_URL)

# Basic validation
# REMOVED: No longer needed as Field(...) enforces presence
# if not settings.PGCRYPTO_SYM_KEY:
#     print("Warning: PGCRYPTO_SYM_KEY is missing. pgcrypto functions will likely fail.")
