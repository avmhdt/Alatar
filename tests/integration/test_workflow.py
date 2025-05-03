import pytest
import asyncio
import uuid
import json
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# Assume common test setup/fixtures are available (e.g., for API client, DB session)
# from ..conftest import client, db_session, create_user, get_authenticated_client # Assuming these exist

# Import models and status enums
from app.models.analysis_request import AnalysisRequest, AnalysisRequestStatus
from app.models.agent_task import AgentTask, AgentTaskStatus  # Added AgentTask imports

# Remove testcontainer fixtures if they are defined in conftest.py
# @pytest.fixture(scope="session")
# def postgres_container(): ...
# @pytest.fixture(scope="session")
# def rabbitmq_container(): ...


# Async test function
@pytest.mark.asyncio
async def test_api_to_worker_orchestrator_flow(
    client: AsyncClient,  # Inject unauthenticated client fixture
    db_session: AsyncSession,  # Inject DB session fixture
    create_user,  # Inject user creation fixture
    get_authenticated_client,  # Inject authenticated client fixture
):
    """Tests the full flow from API submission to worker orchestrator processing."""
    print("\n--- Starting test_api_to_worker_orchestrator_flow --- ")

    # 1. Setup: Create user and get authenticated client
    user_email = f"workflow-user-{uuid.uuid4()}@test.com"
    user_password = "testpassword"
    user_data = {"email": user_email, "password": user_password}
    user = await create_user(db_session, **user_data)
    auth_client = await get_authenticated_client(client, user_email, user_password)

    # 2. Submit Analysis Request via GraphQL API
    prompt_text = (
        f"Test orchestrator workflow prompt {uuid.uuid4()}: Analyze sales data."
    )
    mutation = """
        mutation SubmitRequest($prompt: String!) {
            submitAnalysisRequest(prompt: $prompt) {
                analysisRequest {
                    id
                    status
                    prompt
                    userId
                }
                userErrors {
                    message
                    field
                }
            }
        }
    """
    variables = {"prompt": prompt_text}
    analysis_request_id = None
    analysis_request_gql_id = None

    print(f"Submitting analysis request with prompt: '{prompt_text}'")
    response = await auth_client.post(
        "/graphql", json={"query": mutation, "variables": variables}
    )
    response.raise_for_status()  # Check for HTTP errors
    data = response.json()
    print(f"GraphQL Response: {data}")

    # Assert successful submission and get ID
    assert not data.get("errors"), f"GraphQL query failed: {data.get('errors')}"
    submit_payload = data["data"]["submitAnalysisRequest"]
    assert not submit_payload[
        "userErrors"
    ], f"GraphQL mutation returned errors: {submit_payload['userErrors']}"
    request_data = submit_payload["analysisRequest"]
    assert request_data, "AnalysisRequest data missing in response"
    analysis_request_gql_id = request_data["id"]
    # Extract UUID from GraphQL ID (assuming format like "AnalysisRequest:uuid")
    try:
        analysis_request_id = uuid.UUID(analysis_request_gql_id.split(":")[1])
    except (IndexError, ValueError):
        pytest.fail(f"Could not parse UUID from GraphQL ID: {analysis_request_gql_id}")

    assert (
        request_data["status"] == AnalysisRequestStatus.PENDING.value
    ), f"Initial status should be PENDING, got {request_data['status']}"
    assert request_data["prompt"] == prompt_text
    # We need the user's GQL ID for comparison
    # user_gql_id = f"User:{user.id}" # Assuming user GQL ID format
    # assert request_data['userId'] == user_gql_id # Verify correct user ID
    print(f"Analysis request submitted successfully. ID: {analysis_request_id}")

    # --- Verification Step 1: Check AgentTask Creation ---
    # Wait a short moment for the initial dispatch to potentially happen
    await asyncio.sleep(2)
    agent_task_result = await db_session.execute(
        select(AgentTask).filter_by(analysis_request_id=analysis_request_id)
    )
    initial_agent_task = agent_task_result.scalars().first()

    assert initial_agent_task is not None, "AgentTask record was not created"
    assert (
        initial_agent_task.status == AgentTaskStatus.PENDING.value
    ), f"Initial AgentTask status should be PENDING, got {initial_agent_task.status}"
    # We could also check initial_agent_task.department based on the LLM plan,
    # but the plan might vary. For now, just check existence and PENDING status.
    print(f"AgentTask {initial_agent_task.id} created successfully in PENDING state.")
    # Store task ID for later update simulation
    agent_task_id_to_update = initial_agent_task.id
    # --- End Verification Step 1 ---

    # 3. Wait for Worker Processing (Poll the database)
    max_wait_time = 60  # seconds (increase wait time for orchestrator)
    poll_interval = 2  # second
    start_time = asyncio.get_event_loop().time()
    final_request_state: Optional[AnalysisRequest] = None

    print("Waiting for worker to process the request via orchestrator...")
    while asyncio.get_event_loop().time() - start_time < max_wait_time:
        # Use async session correctly
        result = await db_session.execute(
            select(AnalysisRequest).filter_by(id=analysis_request_id)
        )
        current_request = result.scalar_one_or_none()

        if current_request:
            current_status = AnalysisRequestStatus(
                current_request.status
            )  # Convert to Enum
            print(
                f"Polling... Request {analysis_request_id} status: {current_status.name}"
            )
            if current_status in [
                AnalysisRequestStatus.COMPLETED,
                AnalysisRequestStatus.FAILED,
            ]:
                final_request_state = current_request
                print(
                    f"Request {analysis_request_id} reached final status: {current_status.name}"
                )
                break
        else:
            print(f"Polling... Request {analysis_request_id} status: NOT_FOUND")

        # --- Simulation Step: Simulate C2 Worker Completing the Task ---
        # Check if the agent task still exists and is PENDING/RUNNING before updating
        if agent_task_id_to_update:
            task_result = await db_session.execute(
                select(AgentTask).filter_by(id=agent_task_id_to_update)
            )
            task_to_update = task_result.scalar_one_or_none()
            # Only update if it's still in a state C1 would be checking
            if task_to_update and task_to_update.status in [
                AgentTaskStatus.PENDING.value,
                AgentTaskStatus.RUNNING.value,
            ]:
                print(
                    f"Simulating C2 completion for AgentTask {agent_task_id_to_update}..."
                )
                task_to_update.status = AgentTaskStatus.COMPLETED.value
                task_to_update.result = json.dumps(
                    {"simulated_data": "Data from C2 worker"}
                )
                db_session.add(task_to_update)
                await db_session.commit()
                print(
                    f"AgentTask {agent_task_id_to_update} status updated to COMPLETED."
                )
                # Prevent trying to update it again
                agent_task_id_to_update = None
        # --- End Simulation Step ---

        await asyncio.sleep(poll_interval)
    else:
        pytest.fail(
            f"AnalysisRequest {analysis_request_id} did not reach final state within {max_wait_time}s."
        )

    # 4. Assert Final State
    assert final_request_state is not None
    final_status = AnalysisRequestStatus(final_request_state.status)

    # Check for FAILED status and provide error message if failed
    if final_status == AnalysisRequestStatus.FAILED:
        pytest.fail(
            f"AnalysisRequest {analysis_request_id} failed. Error: {final_request_state.error_message}"
        )

    assert (
        final_status == AnalysisRequestStatus.COMPLETED
    ), f"Expected COMPLETED status, but got {final_status.name}"
    assert final_request_state.completed_at is not None

    # Assert Agent State (Checkpointer Persistence)
    assert final_request_state.agent_state is not None, "Agent state should not be null"
    assert isinstance(
        final_request_state.agent_state, dict
    ), "Agent state should be a dictionary"
    # Example: Check for presence of expected keys from checkpointer structure
    assert (
        "checkpoint" in final_request_state.agent_state
    ), "Agent state missing 'checkpoint' key"
    checkpoint_data = final_request_state.agent_state.get("checkpoint", {})
    assert "ts" in checkpoint_data, "Agent state checkpoint missing 'ts' key"
    # Could add more specific checks if needed, e.g., presence of 'final_result' in state
    assert "final_result" in checkpoint_data.get(
        "channel_values", {}
    ), "final_result missing in agent_state channel_values"

    # Assert Aggregated Results in State
    aggregated_results = checkpoint_data.get("channel_values", {}).get(
        "aggregated_results"
    )
    assert isinstance(
        aggregated_results, dict
    ), "Aggregated results should be a dict in state"
    # The key should be the stringified UUID of the completed AgentTask
    completed_task_id_str = str(initial_agent_task.id)
    assert (
        completed_task_id_str in aggregated_results
    ), f"Result for task {completed_task_id_str} missing in aggregated_results"
    assert aggregated_results[completed_task_id_str] == {
        "simulated_data": "Data from C2 worker"
    }, "Incorrect simulated result found in aggregated_results"
    print("Aggregated results correctly found in final agent state.")

    # Assert Final Result
    assert final_request_state.result is not None, "Final result should not be null"
    try:
        result_data = json.loads(final_request_state.result)
        assert result_data is not None, "Deserialized result should not be null"
        # Add checks on result content if the plan/aggregation is deterministic enough
        # For now, just check it's valid JSON and not empty/null
        print(f"Final Result (deserialized): {result_data}")
    except json.JSONDecodeError:
        pytest.fail(f"Final result was not valid JSON: {final_request_state.result}")

    # 5. Cleanup (Handled by fixtures typically)
    print("--- Finished test_api_to_worker_orchestrator_flow ---")


# Add more tests for edge cases, failures, different prompts, graph resumption etc.
