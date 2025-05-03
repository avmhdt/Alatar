# Plan to Address Implementation Gaps

This plan outlines the steps to systematically address the identified gaps between the system design (`docs/system_design.md`) and the current implementation. It prioritizes security and core functionality.

**Phase 1: Core Functionality & Security Foundations**

1.  **Implement RLS Application Context Setting:** (Critical Security Gap)
    *   **Goal:** Ensure Row-Level Security policies are effective by setting the `app.current_user_id` session variable.
    *   **Actions:**
        *   **API Layer:** Modify the GraphQL context setup (`app/graphql/schema.py::Context.get_context` or a FastAPI dependency) to retrieve the authenticated `user_id` and execute `SET LOCAL app.current_user_id = '...'` on the database session (`Context.db`) at the beginning of each request.
        *   **Worker Layer:** Implement the `set_db_session_context` function in `worker.py` to execute `SET LOCAL app.current_user_id = '...'` within the `get_db_session_with_context` context manager using the `user_id` from the incoming message.
    *   **Verification:**
        *   Write specific integration tests (`tests/integration/`) that attempt to access/modify data belonging to *different* users within the same test function (simulating concurrent requests or incorrect logic). These tests should fail due to RLS policy violations if context setting is correct, or pass inappropriately if it's missing/incorrect.
        *   Manually verify database logs (if possible) to confirm the `SET LOCAL` command is executed.

2.  **Integrate C1 Orchestrator Invocation in Worker:** (Core Functionality Gap)
    *   **Goal:** Make the worker process actual analysis requests using the LangGraph orchestrator.
    *   **Actions:**
        *   Modify `worker.py`: Remove the placeholder `asyncio.sleep(5)` and simulated success logic within `process_message`.
        *   Inside `process_message` (after fetching the request and setting status to `PROCESSING`), instantiate and invoke the compiled C1 LangGraph orchestrator (`app/agents/orchestrator.py`).
        *   Pass the necessary initial state (`analysis_request_id`, `user_id`, `prompt`, `shop_domain`, etc.) and configuration (`thread_id`) to the graph's `ainvoke` method.
        *   Implement the DB checkpointer logic commented out in `orchestrator.py` (`SqlAlchemyCheckpoint`), ensuring it correctly uses `SessionLocal` for `_load_state_from_db` and `_save_state_to_db`. Compile the graph with this checkpointer.
        *   Handle the final state returned by the graph to update the `AnalysisRequest` status (`COMPLETED` or `FAILED`) and store the `final_result` or `error` in the database.
    *   **Verification:**
        *   Integration tests (`tests/integration/test_workflow.py` or similar) submitting an analysis request via GraphQL, verifying the worker picks it up, the `AnalysisRequest.agent_state` is populated/updated by the checkpointer, and the final status/result is set correctly.
        *   Check logs for evidence of orchestrator execution.

3.  **Implement C1-C2 Communication (Queue & DB):** (Core Functionality Gap)
    *   **Goal:** Enable the C1 orchestrator to dispatch tasks to C2 agents via RabbitMQ and track their status via the `AgentTask` table.
    *   **Actions:**
        *   Modify `app/agents/orchestrator.py`:
            *   Implement `_publish_to_department_queue`: Use the `QueueClient` (needs to be accessible, perhaps passed via state or context) to publish task messages to the correct department queue (`DEPARTMENT_QUEUES`). Ensure message format matches C2 worker expectations.
            *   Implement `_create_agent_task_record`: Ensure this correctly saves the initial `AgentTask` record with `status=PENDING`.
            *   Implement `_check_c2_task_status`: Query the `AgentTask` table for the status, `result`, and `error_message` of the specified task IDs.
            *   Refine `dispatch_tasks` and `check_task_status` nodes to use these implemented functions correctly. Ensure results/errors from `_check_c2_task_status` are properly stored in the C1 state (`aggregated_results`).
    *   **Verification:**
        *   Modify integration tests to check:
            *   `AgentTask` records are created with `status=PENDING`.
            *   Messages appear in the correct RabbitMQ department queues (requires queue inspection tooling or test consumers).
            *   C1 `check_task_status` node correctly reads status updates made by (simulated or actual) C2 agents to the `AgentTask` table.
            *   `aggregated_results` in C1 state are populated correctly.

4.  **Implement Shopify Client Caching:** (Performance/Cost Gap)
    *   **Goal:** Utilize the database cache for Shopify API calls to reduce redundant requests.
    *   **Actions:**
        *   Refactor `_fetch_with_cache` (from `shopify_tools.py`) into the `ShopifyAdminAPIClient` class in `app/services/shopify_client.py`.
        *   Modify methods like `get_products`, `get_orders` within `shopify_client.py` to call the internal `_fetch_with_cache` method instead of directly calling `_make_request`. Pass appropriate cache key prefixes and arguments.
    *   **Verification:**
        *   Add/modify unit tests for `ShopifyAdminAPIClient` (`tests/unit/test_shopify_client.py`) mocking the DB (`CachedShopifyData`) and `_make_request`. Verify that:
            *   Cache misses trigger `_make_request` and create a cache entry.
            *   Cache hits return cached data *without* calling `_make_request`.
            *   Expired cache entries trigger `_make_request`.
        *   Check logs for "Cache hit" / "Cache miss" messages during integration tests.

**Phase 2: Enhancing Agent Logic & Reliability**

5.  **Refine C2/C3 Agent Logic:** (Core Functionality Gap)
    *   **Goal:** Move beyond placeholder C2/C3 logic towards the intended design using LCEL and appropriate tools/LLMs.
    *   **Actions:**
        *   Refine `DataRetrievalDepartmentRunnable` (`data_retrieval.py`): Implement more sophisticated tool routing (e.g., using an LLM with function calling or a router chain) based on the `task_details` from C1, instead of simple dict lookup.
        *   Refine `QuantitativeAnalysisDepartmentRunnable` (`quantitative_analysis.py`): Enhance the prompt (`format_quantitative_analysis_prompt`) and potentially use models better suited for analysis. Consider structured output parsing if needed.
        *   Implement other C2 Departments (Qualitative Analysis, Recommendation Generation) as `RunnableSequence` or similar LCEL structures, defining their specific prompts and LLM interactions/tool usage.
        *   Ensure all C2 agents robustly update their corresponding `AgentTask` record in the database with `status`, `result` (on success), or `error_message` (on failure) using a shared helper function.
        *   Enhance C3 Tools (`shopify_tools.py`) as needed for new departments.
    *   **Verification:**
        *   Unit tests for individual C2 runnable logic and C3 tools.
        *   Integration tests covering workflows involving different departments, checking the quality/content of `AgentTask.result` and the final `AnalysisRequest.result`.

6.  **Implement HITL Agent Proposal Logic:** (Key Feature Gap)
    *   **Goal:** Enable agents (likely within C1 or specific C2s like Recommendation Generation) to propose actions for user approval.
    *   **Actions:**
        *   Identify points in the agent logic (`orchestrator.py` or C2 Runnables) where actions should be proposed.
        *   Add LLM prompts/logic for the agent to generate action details (`action_type`, `description`, `parameters`).
        *   Call a service function (e.g., within `action_service.py`) to create the `ProposedAction` record in the database with `status='proposed'`, linking it to the `AnalysisRequest` and `user_id`.
    *   **Verification:**
        *   Integration tests (`tests/integration/test_graphql_hitl.py` or similar) verifying that specific analysis prompts result in `ProposedAction` records being created with the expected details and `status='proposed'`.

7.  **Implement DLQs and Enhance Error Handling:** (Reliability Gap)
    *   **Goal:** Improve system robustness by handling poison messages and providing clearer GraphQL errors.
    *   **Actions:**
        *   Configure RabbitMQ DLQs for worker queues (C1 input, C2 department queues). This might involve updates to `docker-compose.yml` service definitions or queue declaration parameters in `QueueClient`.
        *   Modify message consumer logic (`worker.py`, C2 agent consumers) to NACK and *not* requeue messages that fail persistently or are malformed, allowing them to be routed to the DLQ.
        *   Refine GraphQL error mapping (`app/graphql/errors.py`, resolvers) to use the specific `UserError` codes defined in `system_design.md`. Provide more context-specific error messages.
    *   **Verification:**
        *   Integration tests simulating error conditions (e.g., sending malformed messages, tasks failing repeatedly) and verifying messages land in the DLQ. Monitor DLQ size.
        *   Test GraphQL mutations known to cause specific errors and assert the correct `UserError` code and message are returned.

8.  **Implement PII Masking in Logging:** (Security/Compliance Gap)
    *   **Goal:** Prevent sensitive data leakage in logs.
    *   **Actions:**
        *   Modify `app/logging_config.py`. Add custom `logging.Filter` classes or use appropriate library features.
        *   Implement filtering logic based on field names (e.g., `password`, `token`, `email`) or regex patterns for common PII.
        *   Apply filters to relevant handlers in the logging configuration. Decide on masking strategy (replace with `*****`, hash, etc.).
    *   **Verification:**
        *   Run tests that handle sensitive data (e.g., login, analysis with potentially sensitive prompts/results) and manually inspect the generated logs (or write assertions against log output if feasible) to confirm PII is masked correctly.

**Phase 3: Evaluation, Testing & Ops**

9.  **Integrate Agent/LLM Evaluation:** (Quality Gap)
    *   **Goal:** Systematically evaluate the quality and safety of agent outputs.
    *   **Actions:**
        *   Integrate LangSmith SDK for tracing and evaluation. Ensure traces are correctly associated with `user_id` / `analysis_request_id`.
        *   Curate benchmark datasets (prompts, expected outputs/criteria) covering different analysis types and edge cases (as outlined in the design).
        *   Develop evaluation scripts using LangSmith Eval or custom logic (e.g., LLM-as-judge, regex checks, semantic similarity) targeting the benchmark data.
        *   Integrate evaluation runs into CI/CD or run periodically.
    *   **Verification:** Review LangSmith traces and evaluation results. Track quality metrics over time.

10. **Expand Testing Coverage:** (Robustness Gap)
    *   **Goal:** Increase confidence through comprehensive testing.
    *   **Actions:**
        *   Develop E2E tests (`pytest` + `httpx` or dedicated framework like Playwright/Selenium if a UI exists later) covering critical user flows (register, link Shopify, submit analysis, view results, approve/reject HITL).
        *   Implement performance tests (`locust` or `k6` scripts in `performance_tests/`) targeting key API endpoints and analysis workflows. Run against a staging environment.
        *   Enhance security testing: Ensure SAST (`bandit`) and dependency scans (`pip-audit`) run in CI. Set up DAST scans (e.g., OWASP ZAP) against staging. Plan for periodic manual penetration testing.
    *   **Verification:** Review test reports, performance metrics (latency, RPS under load), security scan results.

11. **Verify and Refine CI/CD Pipelines:** (Ops Gap)
    *   **Goal:** Ensure automated pipelines align with the operational strategy in the design.
    *   **Actions:**
        *   Review `.github/workflows/ci.yml` and `deploy.yml`.
        *   Confirm all specified CI steps (lint, test types, scan, build) are present.
        *   Verify the CD strategy (trigger, staging deployment, production trigger, Alembic migration execution order) matches the design. Make necessary adjustments.
    *   **Verification:** Successful and predictable pipeline runs, review deployment artifacts and processes.

This plan provides a structured approach. Remember to commit changes frequently, write tests for new code, and potentially break down larger steps into smaller tasks or user stories.
