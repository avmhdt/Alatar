import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

# OpenTelemetry Imports (Basic Setup)
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# Import exporters and processor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter # Use if sending via HTTP
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter # Import Console exporter

# Add SlowAPI imports
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware
from strawberry.fastapi import GraphQLRouter
# Import CORSMiddleware
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router  # Import the auth router
from app.core.config import settings  # Added

# Import Redis client functions
from app.core.redis_client import close_redis_pool, create_redis_pool
from app.graphql.schema import Context, schema  # Import the combined schema and Context
from app.logging_config import setup_logging

# Call setup_logging early, before creating app or loggers
setup_logging()
logger = logging.getLogger(__name__)

# --- Rate Limiting Setup ---
# Initialize Limiter - key_func identifies the client (e.g., by IP)
limiter = Limiter(key_func=get_remote_address)


def setup_opentelemetry(app: FastAPI):
    # Check if tracing is enabled using the dedicated flag from settings
    if settings.OPENTELEMETRY_ENABLED:
        logger.info("Setting up OpenTelemetry")
        # Set service name for OTel
        resource = Resource(attributes={SERVICE_NAME: "AlatarService"})

        # Set trace provider
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        # Configure exporter based on endpoint setting
        if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
            endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
            logger.info(f"Configuring OTLP Exporter to: {endpoint}/v1/traces")
            try:
                exporter = OTLPSpanExporter(endpoint=f"{endpoint.strip('/')}/v1/traces")
                processor = BatchSpanProcessor(exporter)
                provider.add_span_processor(processor)
            except Exception as e:
                logger.error(f"Failed to initialize OTLP Exporter: {e}. Falling back to Console Exporter.")
                processor = BatchSpanProcessor(ConsoleSpanExporter())
                provider.add_span_processor(processor)
        else:
            logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set. Defaulting to ConsoleSpanExporter.")
            processor = BatchSpanProcessor(ConsoleSpanExporter())
            provider.add_span_processor(processor)

        # Instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry setup complete.")
    else:
        logger.info("OpenTelemetry tracing is disabled via OPENTELEMETRY_ENABLED setting.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup happens before yielding
    setup_opentelemetry(app)
    # Create Redis connection pool on startup
    await create_redis_pool()

    logger.info("Application startup complete.")
    # Example: Create DB tables if they don't exist (useful for simple setups without Alembic)
    # try:
    #     Base.metadata.create_all(bind=engine)
    #     logger.info("Database tables checked/created.")
    # except Exception as e:
    #     logger.error(f"Error creating database tables: {e}")

    # Add any other startup logic here (e.g., initialize ML models, connect to external services)
    yield
    # Cleanup happens after yielding (if needed)
    # Close Redis connection pool on shutdown
    await close_redis_pool()
    logger.info("Application shutdown.")


app = FastAPI(lifespan=lifespan)

# --- Add Middleware ---
# Add CORS Middleware early on
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS, # From settings
    allow_credentials=True, # Allow cookies
    allow_methods=["*"], # Allow all methods
    allow_headers=["*"], # Allow all headers
)

# Add Rate Limiter State and Middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# IMPORTANT: Add SlowAPIMiddleware *before* SessionMiddleware if limits depend on session state,
# otherwise, the order might not strictly matter. Placing it early is generally safe.
app.add_middleware(SlowAPIMiddleware)

# Add SessionMiddleware (ensure APP_SECRET_KEY is set)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.APP_SECRET_KEY,  # Use the key from settings
    https_only=True, # Recommended for production if served over HTTPS
    same_site="lax", # Helps prevent CSRF
    # max_age=14 * 24 * 60 * 60 # Optional: Session cookie lifetime (e.g., 14 days)
)

# --- GraphQL Setup ---
# Apply rate limit to the GraphQL router instance directly
# Note: This applies the limit based on IP per connection (HTTP or WS)
graphql_app: GraphQLRouter = limiter.limit("100/minute")(
    GraphQLRouter(
        schema,
        context_getter=Context.get_context,  # Use the context getter
    )
)


# --- Mount Routers ---
# Remove the wrapper function and include the rate-limited router directly
# This ensures both HTTP and WebSocket connections are handled by the router.
app.include_router(graphql_app, prefix="/graphql")
# @limiter.limit("100/minute") # Removed decorator from here
# async def graphql_endpoint(request: Request): # Removed wrapper function
#     # This function is needed to apply the decorator to the router include
#     # The actual handling is done by the GraphQLRouter itself
#     # We need to await the router's handling method
#     return await graphql_app.handle(request=request)


app.include_router(auth_router)  # Prefix is already defined in the router itself


@app.get("/")
async def read_root():
    logger.info("Root endpoint called")
    return {"message": "Welcome to Project Alatar"}


@app.get("/health")
@limiter.limit("10/minute")  # Example: Limit health checks too
async def health_check(request: Request):  # Add request for limiter
    # Basic health check, can be expanded later (e.g., check DB connection)
    logger.debug("Health check endpoint called")
    return {"status": "ok"}


# Add middleware or request logging if needed beyond OTel
# @app.middleware("http")
# async def log_requests(request: Request, call_next):
#     logger.info(f"Request path: {request.url.path}")
#     response = await call_next(request)
#     logger.info(f"Response status: {response.status_code}")
#     return response

# Example: How to get tracer and create spans manually
# tracer = trace.get_tracer(__name__)
# @app.get("/manual_trace")
# async def manual_trace():
#     with tracer.start_as_current_span("manual_span") as span:
#         span.set_attribute("custom.attribute", "value")
#         logger.info("Inside manual span")
#         return {"trace_id": span.get_span_context().trace_id}

if __name__ == "__main__":
    # This is typically not run directly for production,
    # uvicorn command is used instead (as in Dockerfile/docker-compose)
    import uvicorn

    logger.info("Starting Uvicorn directly for local testing")
    uvicorn.run(app, host="0.0.0.0", port=8000)
