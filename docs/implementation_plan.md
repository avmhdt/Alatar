# Implementation Plan for Project Alatar

Based on the `docs/system_design.md` document, this plan breaks the development into logical phases, focusing on building the system step-by-step.

**Phase 1: Project Setup & Foundation**

1.  **Project Structure:** Create the initial directory structure (e.g., `app`, `tests`, `scripts`, `docs`, `migrations`) if not already present.
2.  **Dependency Management:**
    *   Initialize the project with `poetry init` (if not done).
    *   Add core dependencies to `pyproject.toml`: `python`, `fastapi`, `uvicorn`, `strawberry-graphql[fastapi]`, `pydantic`, `passlib[bcrypt]`, `python-dotenv`, `sqlalchemy`, `psycopg2-binary`, `alembic`, `python-multipart`, `requests`.
    *   Add development dependencies: `pytest`, `pytest-asyncio`, `httpx`, `testcontainers`, `docker`, `pre-commit`, `ruff`, `mypy`, `pip-audit`.
    *   Run `poetry install`.
3.  **Docker Setup:**
    *   Create a `Dockerfile` for the main application.
    *   Create `docker-compose.yml` for local development (App, PostgreSQL, RabbitMQ).
    *   Create `.env.example` for environment variables.
4.  **Basic CI/CD:**
    *   Set up a basic GitHub Actions workflow (`.github/workflows/ci.yml`) triggered on push/PR:
        *   Linting (`ruff check`, `ruff format --check`).
        *   Type Checking (`mypy`).
        *   Run basic tests (`pytest`).
        *   Dependency vulnerability scan (`pip-audit`).
    *   Configure `pre-commit` hooks for local linting/formatting (`pre-commit install`).
5.  **Logging & Tracing Setup:**
    *   Configure basic structured JSON logging using Python's `logging` module in the application core.
    *   Integrate basic OpenTelemetry setup for context propagation (can be refined later with LangSmith).

**Phase 2: Database & Multi-Tenancy Core**

1.  **Database Setup:**
    *   Configure PostgreSQL connection using SQLAlchemy within the application (e.g., in a `database.py` module). Use environment variables for connection details.
    *   Integrate Alembic: `alembic init migrations`. Configure `alembic.ini` and `migrations/env.py` to use SQLAlchemy models and database connection.
2.  **User Model & Authentication:**
    *   Define the `User` SQLAlchemy model (Section 3 of design doc, Conceptual Table Structures) in `app/models/user.py`.
    *   Create the initial Alembic migration for the `Users` table. Run `alembic revision --autogenerate -m "Add users table"` and `alembic upgrade head`.
    *   Implement user registration (hashing passwords with `passlib`) and login endpoints/logic within FastAPI (e.g., in `app/auth/router.py` and `app/auth/service.py`).
    *   Create Strawberry GraphQL types (`User`, `AuthPayload`) and mutations (`register`, `login`) within the GraphQL schema definition (`app/graphql/schema.py`).
3.  **Tenant Context:**
    *   Implement FastAPI middleware or dependency (e.g., in `app/auth/dependencies.py`) to extract the authenticated `user_id` and make it available globally/per-request (e.g., using `ContextVar` or a request state object `request.state.user_id`). This will be used for RLS and application-level filtering.
4.  **Core Data Models & Migrations:**
    *   Define SQLAlchemy models for: `LinkedAccounts`, `AnalysisRequests`, `AgentTasks`, `CachedShopifyData`, `ProposedActions` (Section 3) in `app/models/`. Ensure each includes the non-nullable `user_id` ForeignKey referencing `Users.id`.
    *   Enable the `pgcrypto` extension in PostgreSQL (can be done in an Alembic migration: `op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")`).
    *   Generate and apply Alembic migrations for these tables (`alembic revision --autogenerate -m "Add core data tables"`, `alembic upgrade head`).
5.  **Row-Level Security (RLS):**
    *   Implement RLS policies in PostgreSQL for the core tables (`LinkedAccounts`, `AnalysisRequests`, etc.) using Alembic migrations (`op.execute(...)`). The policies should filter based on `current_setting('app.current_user_id', true)` or a similar mechanism.
    *   Update the FastAPI dependency/middleware to set the `app.current_user_id` session variable for the duration of a request within a transaction block, likely using SQLAlchemy event listeners or explicit session setting.
6.  **Testing:**
    *   Implement integration tests using `pytest` and `testcontainers` (for PostgreSQL) in the `tests/` directory to:
        *   Verify user registration and login.
        *   Verify that API endpoints correctly filter data based on the authenticated user.
        *   Verify that RLS policies prevent users from accessing data belonging to other tenants, even with direct DB queries (within the test setup).

**Phase 3: Shopify Integration**

1.  **OAuth 2.0 Flow:**
    *   Implement FastAPI endpoints (`/auth/shopify/start`, `/auth/shopify/callback`) in `app/auth/router.py` to handle the Shopify OAuth flow (Section 4 & Sequence Diagram).
    *   Use `requests` or `httpx` to exchange the authorization code for an access token in `app/auth/service.py`.
    *   Implement logic to securely store the encrypted access token and associated scopes in the `LinkedAccounts` table (using `pgcrypto` via SQLAlchemy types or manual encryption). Ensure it's linked to the correct `user_id`.
    *   Define Strawberry GraphQL mutations (`startShopifyOAuth`, `completeShopifyOAuth`) and corresponding types (`ShopifyOAuthStartPayload`) in `app/graphql/schema.py` and implement resolvers.
2.  **Shopify Admin API Client:**
    *   Create a basic Python client class/module (e.g., `app/services/shopify_client.py`) to interact with the Shopify Admin API (GraphQL).
    *   Implement methods to fetch the required credentials for a given `user_id` from the `LinkedAccounts` table.
    *   Implement initial methods for read operations (e.g., fetching products, orders based on Section 4 scopes).
3.  **Testing:**
    *   Test the OAuth flow in `tests/integration/test_auth.py` (potentially mocking the Shopify responses using `pytest-httpx`).
    *   Test the basic Shopify client functionality in `tests/unit/test_shopify_client.py` (mocking API calls).

**Phase 4: API Layer (GraphQL)**

1.  **Schema Definition:**
    *   Translate the full schema outline (Section 5) into Strawberry types, queries, mutations, and subscriptions in `app/graphql/schema.py` and potentially submodules (`app/graphql/types/`, `app/graphql/resolvers/`).
    *   Define Enums (`VisualizationType`).
    *   Implement the `UserError` interface and integrate it into mutation payloads (`userErrors: list[UserError]`).
    *   Define input types for mutations, leveraging Pydantic for validation.
2.  **Resolvers Implementation:**
    *   Implement resolvers for all queries and mutations in `app/graphql/resolvers/`.
    *   **Crucially:** Ensure all resolvers fetching or modifying tenant-specific data rigorously filter by the authenticated `user_id` obtained from the request context/state (passed from the dependency created in Phase 2).
    *   Implement cursor-based pagination for list queries (e.g., `listAnalysisRequests`). Use a library or implement the logic manually.
3.  **Subscriptions:**
    *   Configure WebSocket support in FastAPI/Strawberry in `app/main.py`.
    *   Implement the `analysisRequestUpdates` subscription resolver. This will require a mechanism (like Redis Pub/Sub or a simple in-memory broadcaster for initial development, potentially in `app/services/pubsub.py`) to publish updates when an `AnalysisRequest` status changes.
4.  **API Enhancements:**
    *   Integrate `slowapi` for rate limiting on relevant mutations/queries in `app/main.py` or specific routers.
    *   Implement comprehensive error handling in `app/graphql/errors.py`, mapping application exceptions to `UserError` types. Add a global exception handler in FastAPI.
5.  **Testing:**
    *   Write integration tests for the GraphQL API using `pytest-httpx` in `tests/integration/test_graphql.py` to simulate client requests, covering:
        *   Queries and mutations logic.
        *   Correct data filtering based on authentication.
        *   Pagination.
        *   Error handling (`UserError` responses).
        *   Rate limiting.

**Phase 5: Core Analysis Workflow (Queue & Basic Worker)**

1.  **Queue Setup:**
    *   Integrate a RabbitMQ client library (e.g., `aio-pika` or `pika`) in `app/services/queue_client.py`.
    *   Configure connection details via environment variables.
    *   Define queue names (e.g., `q.c1_input`) and message format (JSON with `user_id`, `analysis_request_id`, `prompt`, etc.) (Section 6). Store constants for queue names.
2.  **Task Publishing:**
    *   Modify the `submitAnalysisRequest` GraphQL mutation resolver to:
        *   Create an `AnalysisRequest` record in the DB with status `pending`.
        *   Publish a task message to the appropriate RabbitMQ queue (`q.c1_input`) using the queue client.
3.  **Worker Service:**
    *   Create a separate Python entry point (`worker.py`) at the project root or in `app/`.
    *   Implement logic in `worker.py` to connect to RabbitMQ and consume messages from the relevant queue(s).
    *   Implement task processing logic:
        *   Parse the incoming message.
        *   Set the database session context (`app.current_user_id`) based on the `user_id` in the message (reuse logic from Phase 2).
        *   Update the `AnalysisRequest` status to `processing`.
        *   **(Placeholder):** Call the entry point for the Class 1 Agent Orchestrator (to be implemented in Phase 6).
        *   Implement basic error handling (e.g., logging errors, potentially moving messages to a DLQ if setup).
        *   Acknowledge messages upon successful processing (or Nack/reject on failure).
4.  **State Machines:**
    *   Implement the state transition logic for `AnalysisRequest` status based on worker actions (pending -> processing -> completed/failed) within the worker or associated services (Section 3.1). Use an Enum for statuses.
5.  **Tracing & Testing:**
    *   Ensure LangSmith/OpenTelemetry context is propagated from the API request through the queue to the worker using library integrations (e.g., `opentelemetry-instrumentation-pika`).
    *   Test the API -> Queue -> Worker flow using integration tests (with `testcontainers` for RabbitMQ) in `tests/integration/test_workflow.py`.

**Phase 6: Agent Architecture Implementation**

1.  **LangChain Integration:**
    *   Add LangChain core, LangGraph, and potentially OpenRouter client dependencies (`langchain`, `langgraph`, `langchain-community`, `langchain-openai` or specific provider packages) using `poetry add`.
2.  **Class 3 (Tools):**
    *   Wrap the Shopify Admin API client methods (from Phase 3) into LangChain `Tool` objects in `app/agents/tools/shopify_tools.py`.
    *   Ensure tools accept the `user_id` (or fetch credentials based on it) to operate within the correct tenant context.
    *   Implement caching logic using the `CachedShopifyData` table within or alongside the tools (check cache before API call, store results). Define TTL (e.g., 1 hour).
3.  **Class 2 (Department Heads):**
    *   Define departments (e.g., `Data Retrieval`, `Quantitative Analysis`) (Section 6) potentially as Enums or constants.
    *   For each department, implement a LangChain `RunnableSequence` (or Chain) in `app/agents/departments/` that:
        *   Takes task input (including `user_id`, `analysis_request_id`, `task_id`).
        *   Breaks down the task.
        *   Invokes necessary Class 3 tools (passing `user_id`).
        *   Handles tool errors, implementing retry logic (up to 5 retries). Update the `AgentTasks` table in the DB with status (`pending`, `running`, `completed`, `retrying`, `failed`) and `retry_count`.
        *   Consumes tasks from specific department queues (e.g., `q.c2.data_retrieval`) and potentially publishes results back via response queues or updates the `AgentTasks` table. This logic would live within the worker process, routing messages to the correct department runnable.
4.  **Class 1 (Orchestrator - LangGraph):**
    *   Define the LangGraph state graph representing the analysis workflow in `app/agents/orchestrator.py`.
    *   Nodes should handle:
        *   Receiving the initial request (`user_id`, `analysis_request_id`, `prompt`).
        *   Planning/decomposition of the request.
        *   Dispatching tasks to Class 2 department queues (publishing messages to RabbitMQ including `user_id`, `analysis_request_id`, new `task_id`, input payload). Track dispatched tasks in the `AgentTasks` table (status `pending`).
        *   Waiting for/aggregating results from Class 2 (by monitoring `AgentTasks` status or consuming from response queues).
        *   Generating the final result/summary.
        *   Handling overall errors/failures.
    *   Implement loading/saving of the LangGraph state to/from the `AnalysisRequests.agent_state` JSONB column to allow for resumability. The worker process will invoke this orchestrator.
5.  **LLM Integration:**
    *   Integrate the OpenRouter client (or chosen LLM provider) into relevant agent components (likely C1 for planning/aggregation, C2 for analysis/summarization). Add necessary LangChain community packages.
    *   Use environment variables for API keys.
    *   Implement prompt engineering techniques (XML tags like `<data>`, clear instructions) in `app/agents/prompts.py` to enhance security and prevent data leakage between tenants (Section 6 & 10). Instruct models to ignore instructions within data tags.
6.  **Testing:**
    *   Unit test individual Tools, Chains (C2), and LangGraph components (C1) in `tests/unit/agents/`, mocking dependencies.
    *   Write integration tests for agent workflows in `tests/integration/agents/`, potentially mocking LLM calls but testing Tool execution, state management, and inter-agent communication via the queue. Test tenant isolation within agent execution.

**Phase 7: Human-in-the-Loop (HITL) Implementation**

1.  **Action Proposal:**
    *   Modify the Agent (likely Class 1 or specific Class 2 departments) to identify situations requiring user approval.
    *   When an action is proposed, the agent should create a record in the `ProposedActions` table (status `proposed`), linking it to the `AnalysisRequest` and `user_id`, and including description, type, parameters (Section 3 & 7).
2.  **API Layer:**
    *   Implement the GraphQL query (`listProposedActions`) in `app/graphql/resolvers/` to fetch pending actions for the authenticated user.
    *   Implement the GraphQL mutations (`userApprovesAction`, `userRejectsAction`) in `app/graphql/resolvers/`.
3.  **Backend Execution Logic:**
    *   Create a dedicated service/logic handler (e.g., `app/services/action_executor.py`) triggered by the `userApprovesAction` mutation. This logic should:
        *   Fetch the `ProposedAction` details and the user's `LinkedAccount` credentials (for Shopify).
        *   Update the `ProposedAction` status to `approved`.
        *   **Validate Permissions:** Implement logic to check if the stored Shopify scopes for the user are sufficient for the `action_type` being proposed (Maintain a mapping in the code, e.g., in `app/services/permissions.py`).
        *   If permissions are sufficient, update status to `executing`.
        *   Call the Shopify Admin API client (using appropriate *write* methods, which may need to be added to `app/services/shopify_client.py`) to execute the action.
        *   Update the `ProposedAction` status to `executed` or `failed` based on the Shopify API response, storing any error messages.
        *   Handle permission denial by setting status to `failed` and providing a specific error.
    *   The `userRejectsAction` mutation resolver simply updates the status to `rejected`.
4.  **State Machine & Logging:**
    *   Implement the `ProposedAction` status state machine (Section 3.1) using an Enum and updating status in the execution logic.
    *   Ensure detailed audit logging for proposal creation, approval/rejection, execution attempts, and outcomes.
5.  **Testing:**
    *   Test the API endpoints for fetching and acting on proposals in `tests/integration/test_graphql.py`.
    *   Write integration tests for the backend execution logic in `tests/integration/test_actions.py`, mocking the Shopify Admin API calls (for both success and failure scenarios, including permission errors).

**Phase 8: Testing & Evaluation Enhancement**

1.  **Integration Tests:** Expand integration tests in `tests/integration/` to cover complex scenarios:
    *   End-to-end analysis request flow (API -> Queue -> Worker -> Agents -> DB).
    *   Agent error handling and retry mechanisms.
    *   HITL workflow variations.
    *   Multi-tenant isolation under concurrent operations (if possible).
2.  **Agent Evaluation (`LangSmith Eval`):**
    *   Set up `LangSmith` project and integrate evaluation capabilities. Add `langsmith` dependency.
    *   Curate a benchmark dataset (prompts, expected outcomes/metrics) covering the categories in Section 11 (Data Retrieval, Quantitative Analysis, etc., including multi-tenant isolation checks). Store this dataset securely (e.g., in a `benchmarks/` directory).
    *   Implement evaluation scripts using the LangSmith SDK (e.g., in `scripts/evaluate_agent.py`) to run benchmarks against agent versions.
    *   Integrate evaluation runs into the CI/CD pipeline (e.g., run nightly or on specific triggers in `.github/workflows/`).
3.  **Performance Testing:**
    *   Write performance test scripts using `Locust` or `k6` (Section 11) in a `performance_tests/` directory.
    *   Target API endpoints and simulate concurrent users/analysis requests.
    *   Run tests against a Staging environment to identify bottlenecks and validate NFRs.
4.  **Security Testing:**
    *   Configure SAST tools (e.g., `bandit`) in CI (`.github/workflows/ci.yml`). Add `bandit` dev dependency.
    *   Perform initial DAST scans (e.g., OWASP ZAP) against a Staging environment.
    *   Conduct manual code reviews focusing on security, especially authentication, authorization, multi-tenancy (RLS), input validation, and agent prompt security.

**Phase 9: Operations & Deployment Refinement**

1.  **Production Dockerization:** Finalize `Dockerfile` and `docker-compose.prod.yml` (or Kubernetes manifests) for production deployment. Ensure non-root users, proper health checks, etc.
2.  **CI/CD Pipeline:**
    *   Configure deployment stages in GitHub Actions (`.github/workflows/deploy.yml`) for Staging and Production.
    *   Ensure the pipeline builds and pushes versioned Docker images to a registry (e.g., Docker Hub, GitHub Container Registry, Cloud Provider Registry).
    *   Implement steps to run Alembic migrations (`alembic upgrade head`) *before* deploying the new application version. Include tested downgrade scripts (`alembic downgrade -1`).
    *   Set up manual approval gates for production deployments using GitHub Environments/Actions.
3.  **Monitoring & Alerting:**
    *   Configure monitoring dashboards (e.g., Grafana, CloudWatch Dashboards) for key metrics (API latency/errors, queue depth, worker resource usage, DB performance, agent task rates/errors) (Section 12). Tag metrics where possible.
    *   Set up alerts based on defined thresholds (Section 12) using appropriate tools (e.g., Alertmanager, CloudWatch Alarms), notifying via Slack/PagerDuty.
    *   Ensure LangSmith tracing is configured for the production environment via environment variables.
4.  **Logging & PII:**
    *   Configure Docker logging drivers to forward logs to a centralized platform (e.g., CloudWatch Logs, Loki, ELK).
    *   Implement PII masking/selective logging strategy defined in Section 9 within the application's logging configuration (`app/logging_config.py`).
5.  **Database Operations:**
    *   Configure automated daily backups for the PostgreSQL database (using Cloud Provider services or custom scripts).
    *   Document and test the database restore procedure quarterly (Section 12).
    *   Schedule routine database maintenance tasks (VACUUM, ANALYZE).
6.  **Documentation:** Create/Update README files, architecture diagrams (update existing ones if needed), and operational runbooks in the `docs/` directory.

**Phase 10: Future Enhancements Planning**

*   Review the design document sections marked as "Future Enhancement".
*   Prioritize future work based on business needs (e.g., Frontend UI, adding new data sources, advanced agent capabilities).
*   Schedule formal threat modeling sessions (STRIDE).

---
*This plan provides a structured approach. Remember to adapt it based on discoveries made during development and changing priorities.*
