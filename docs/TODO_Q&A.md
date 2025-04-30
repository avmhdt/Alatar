# Alatar System Design - TODO & Q&A

This document tracks the open questions and decisions needed to flesh out the initial system overview into a full system design document.

**Identified Gaps/Areas to Address:**

1.  **Technology Stack:** 
    *   **Backend Language:** Python
    *   **Web Framework/API:** FastAPI
    *   **GraphQL Library:** Strawberry
    *   **Database:** PostgreSQL
    *   **Agent/LLM Framework:** LangChain
    *   **LLM Provider:** OpenRouter (Default: Latest free Gemini, user-configurable)
    *   **Middleware (Queueing):** RabbitMQ (potentially with Celery)
    *   **Containerization:** Docker
    *   **Frontend:** TBD (To be built after backend)
    *   **Cloud/Infrastructure:** TBD (Initial focus on Docker deployment)
2.  **Data Management:**
    *   **Specific Data Sources:**
        *   **Internal:** Shopify Admin API (GraphQL). Initial focus on accessing all available objects.
        *   **External (Web Search, Competitor Data, Market Trends):** TBD/Future Enhancement.
        *   **Marketing Platforms (Ads):** TBD/Future Enhancement.
        *   **Website Analytics (e.g., Google Analytics):** TBD/Future Enhancement.
    *   **Data Storage (PostgreSQL):**
        *   **User Info:** Account details, encrypted credentials (Shopify API keys/OAuth tokens), user preferences (LLM choice).
        *   **Shopify Data:** Cache raw data pulled from Shopify API locally for a limited time (specific TTL TBD). Store derived KPIs and analysis summaries.
        *   **Analysis & Agent Data:** Store analysis requests, generated recommendations, agent tasks (including status, assignments, error counts), potentially intermediate agent reasoning/results.
        *   **Logs:** System logs, agent traces, API call logs (details in item 9).
        *   **Schema:** Requires definition (Tables: `Users`, `LinkedAccounts`, `AnalysisRequests`, `AgentTasks`, `CachedShopifyData`, etc.).
    *   **Data Flow:**
        *   High-level flow approved (User Request -> API -> Queue -> Worker -> Class 1 -> Class 2 -> Class 3 -> External APIs/DB -> Class 2 -> Class 1 -> Response -> User).
        *   Detailed sequence diagrams and error handling paths needed.
3.  **Authentication & Authorization:** 
    *   **User Authentication (Alatar Service):**
        *   Primary: Email/Password (securely hashed via `passlib`/bcrypt).
        *   Secondary: "Log in with Shopify" (Shopify OAuth, links to Alatar account).
        *   Mobile App: Email/Password or Platform logins (Apple/Google) linked to account.
        *   Siri: Relies on authenticated session within the Alatar mobile app.
    *   **Service Authorization (Accessing Shopify Data):**
        *   Method: Shopify OAuth 2.0 flow (assuming Public App).
        *   Process: User approves requested API scopes upon app install/linking.
        *   Scopes: Define minimum necessary scopes (e.g., `read_orders`, `read_products`, etc. - specific list TBD).
        *   Token Storage: Use Offline access tokens, store encrypted in DB.
        *   Security: Emphasize secure storage for credentials and tokens.
4.  **API Design (GraphQL):**
    *   **Goal:** Define the contract between clients (App, Shopify, Siri) and the backend (FastAPI/Strawberry).
    *   **Agreed Schema Outline:**
        *   **Types:** `User`, `ShopifyStore`, `UserPreferences`, `AnalysisRequest` (central object for agent tasks, includes status enum), `AnalysisResult` (includes `Visualization` type), `Visualization` (structured data/charts), `AuthPayload`, `ShopifyOAuthStartPayload`.
        *   **Queries:** `me`, `analysisRequest(id)`, `listAnalysisRequests` (paginated).
        *   **Mutations:** `register`, `login`, `startShopifyOAuth`, `completeShopifyOAuth`, `updatePreferences`, `submitAnalysisRequest(prompt)`.
        *   **Subscriptions:** `analysisRequestUpdates(requestId)` for real-time status/result updates (requires WebSocket support).
    *   **Next Steps:** Refine fields, define input types, specify error handling approach, finalize pagination.
5.  **Agent Implementation Details:**
    *   **Technical Implementation:** Use LangChain.
        *   Class 1 (Core Orchestration): LangChain Agent/Chain/LangGraph. Handles intent, planning, routing, final review.
        *   Class 2 (Departments): LangChain Agents/Chains per department. Handle task breakdown, Class 3 invocation, monitoring, aggregation.
        *   Class 3 (Service Workers): LangChain Tools. Perform specific, atomic actions (API calls, calculations).
    *   **State Management:**
        *   Persistent State: PostgreSQL (`AnalysisRequest`, `AgentTasks` tables).
        *   In-Flight Context/Memory: LangChain Memory objects, potentially loaded/saved from DB for long tasks.
    *   **Inter-Agent Communication:** RabbitMQ for asynchronous task passing (API->Worker, C1->C2 Queues, C2->C3 Queues). Results potentially returned via response queues or RPC pattern.
    *   **Department Management:**
        *   Definition: Functional, platform-agnostic departments (e.g., `Data Retrieval`, `Quantitative Analysis`, `Qualitative Analysis`, `Recommendation Generation`, `Comparative Analysis` [Future], `Predictive Analysis` [Future], `Task Execution` [Future]).
        *   Routing: Class 1 routes tasks to specific department queues in RabbitMQ.
        *   Tooling: Class 3 Tools associated with Class 2 departments.
6.  **Task Execution Specifics (Phase 1):**
    *   **Initial Scope:** Primarily analysis and recommendation. "Execution" means the agent proposes concrete actions with parameters/content (e.g., draft marketing text, discount settings, product descriptions).
    *   **Mechanism: Human-in-the-Loop (HITL) Execution**
        *   Agent proposes action details.
        *   Backend presents proposal clearly in UI (Shopify/App).
        *   User MUST explicitly approve/reject via UI.
        *   On approval, a standard backend API endpoint (FastAPI) is called.
        *   Backend endpoint validates parameters and executes the action via Shopify Admin API (GraphQL mutations).
    *   **Safeguards:**
        *   Mandatory user confirmation (no direct agent execution).
        *   Clear UI preview of changes.
        *   Backend check for required Shopify API *write* permissions (scopes).
        *   Backend parameter validation before API call.
        *   Robust error handling for Shopify API calls.
        *   Audit logging of proposals, approvals, execution attempts, and outcomes in DB.
    *   **Success/Failure Reporting:** Outcome (success or failure, with Shopify details) reported back to user via UI and logged in DB.
7.  **UI/UX Design:** TBD (Post-backend development). Focus initially on Shopify integration (Dashboard + Extensions).
8.  **Non-Functional Requirements (Quantified - Phase 1 Targets):**
    *   **Performance:**
        *   API (User-facing mutations/queries): p95 latency < 500ms.
        *   Agent Processing: Highly variable. Target common queries: tens of seconds to minutes. Implement timeouts for external calls/agent steps.
        *   Transparency: Clear UI indication of ongoing processing.
    *   **Scalability:**
        *   Users: Support low hundreds (100-500) concurrent shops.
        *   Throughput: Handle tens of analysis requests per minute.
        *   Foundation: Architecture supports future scaling.
    *   **Availability:**
        *   Target: 99.5% uptime for core services.
        *   Dependencies: Acknowledge reliance on Shopify, OpenRouter, Cloud Provider uptime.
    *   **Reliability:**
        *   Agent: Accept potential for errors; Class 2 retry logic helps. Focus on graceful failure.
        *   System: Aim for low rate of unhandled exceptions (MTBF: Days/Weeks).
        *   Data: Use transactions for data integrity.
9.  **Error Handling & Logging:**
    *   **Error Handling Strategy:**
        *   API Layer (FastAPI/Strawberry): Standard GraphQL errors, global handler for unexpected -> generic 500 + log.
        *   External Dependencies (Shopify, OpenRouter): Retry logic (`tenacity`) for transient errors; fail fast on 4xx; timeouts.
        *   Class 3 Tool Errors: Caught by Class 2. Increment error count (DB). Retry/alternative/abandon if < 5; Fail task if >= 5.
        *   Class 2/1 Agent Errors: Fail overseeing task/request and report up.
        *   Queueing (RabbitMQ): Use Dead-Letter Queues (DLQs) for persistently failing messages.
        *   Database (PostgreSQL): Handle specific psycopg2 errors, constraint violations; use transactions.
    *   **Logging Strategy:**
        *   Levels: Standard Python `logging` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Minimize `DEBUG` in production.
        *   Format: Structured JSON (timestamp, level, logger_name, message, context map with IDs, tracebacks etc.).
        *   Destination: `stdout`/`stderr` in Docker; Centralized platform (CloudWatch, ELK, Loki, etc.) via logging driver.
        *   Agent Tracing: **Integrate LangSmith** (or similar like OpenTelemetry) for detailed agent run visibility (CoT, tool use, tokens, latency).
        *   Management: Centralized platform for search, filtering, dashboards, alerting. Define retention policies.
10. **Security Architecture:**
    *   **Input Validation:** API (FastAPI/Strawberry validation); Agent/Tool layers (sanitize before external calls/DB/LLM prompts, mitigate prompt injection).
    *   **API Security:** Enforce AuthN/AuthZ; Rate Limiting (`slowapi`); HTTPS; Security Headers.
    *   **Dependency Management:** Use `poetry`; `poetry.lock`; Regular vulnerability scanning (`pip-audit`, Dependabot).
    *   **Encryption:** TLS In-Transit (API, external calls, internal if needed); Encrypt sensitive data At-Rest in DB (`pgcrypto`/app-level for tokens/PII); Encrypt backups.
    *   **Secrets Management:** No hardcoding; Use Env Vars injected securely (Docker/Orchestrator secrets) or dedicated service (Vault, etc.).
    *   **Agent/LLM Security:** Sanitize/delimit prompts; Prevent cross-user data leaks; Mask PII in logs; Least privilege for tools.
    *   **Infrastructure (Docker):** Run as non-root; Network policies; Update base images.
    *   **Threat Modeling:** Conduct STRIDE/similar analysis; Address key risks (Auth bypass, token compromise, prompt injection, DoS).
11. **Deployment & Operations:**
    *   **Deployment Strategy (CI/CD):**
        *   Source Control/Branching: Git (GitHub Flow recommended).
        *   CI (GitHub Actions): Lint, Test, Vuln Scan, Build Docker images, Push to Registry.
        *   CD: Trigger on `main` merge. Staging (auto-deploy), Production (manual trigger). Mechanism TBD (Docker/Orchestrator). DB migrations (Alembic) run separately before app deploy.
    *   **Monitoring:**
        *   Logs: Centralized platform (Item 9).
        *   Metrics (Prometheus/Grafana or Cloud equivalent): System (Host/Container), App (API, Queue, DB), Agent (LangSmith, token usage).
        *   Tracing: OpenTelemetry (potentially via LangSmith).
        *   Availability: External uptime checks.
    *   **Alerting:**
        *   Tool: Alertmanager/Cloud equivalent.
        *   Key Alerts: High API errors/latency, Service down, High resource use, Large DLQ, High error log rate, External API failures.
        *   Notifications: Slack/PagerDuty.
    *   **Maintenance:**
        *   Updates: Regularly update dependencies, base images, OS. Plan for major upgrades.
        *   Database: Automated backups, restore testing, routine maintenance.
        *   Capacity/Cost: Regular review for scaling and optimization.
12. **Testing Strategy:**
    *   **Unit Testing (`pytest`, mocking):** Isolate and test individual functions/classes/tools.
    *   **Integration Testing (`pytest`, `testcontainers`, `pytest-httpx`):** Test component interactions within service boundaries (API->DB, Worker->Agent->Tool). Use test DB/Queue, mock external APIs.
    *   **E2E Testing (`pytest`):** Test full user workflows on deployed Staging env. Focus on critical paths.
    *   **Agent/LLM Evaluation (`LangSmith` Eval, custom scripts):** Assess response quality/correctness using benchmark datasets, LLM-as-Judge, A/B testing.
    *   **Performance Testing (Locust/k6):** Validate NFRs under load on Staging.
    *   **Security Testing:** CI (Dep Scan, SAST), DAST scans (Staging), Manual review/pentesting.
    *   **CI/CD Integration:** Automate unit, integration, SAST, dep scans in CI. Run E2E, perf, DAST periodically/manually on Staging. 