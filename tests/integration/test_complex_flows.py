import pytest
from httpx import AsyncClient

# Assume test fixtures like `client` (an AsyncClient instance) and
# `auth_headers` (dict with Authorization header for a test user) are available via pytest-asyncio/conftest.py


@pytest.mark.asyncio
async def test_end_to_end_analysis_submission(client: AsyncClient, auth_headers: dict):
    """
    Tests submitting an analysis request and checking its initial status.
    Assumes 'submitAnalysisRequest' mutation and 'analysisRequest' query exist.
    """
    # 1. Submit Analysis Request
    submit_mutation = """
        mutation Submit($prompt: String!) {
            submitAnalysisRequest(input: { prompt: $prompt }) {
                analysisRequest {
                    id
                    status
                }
                userErrors { message field }
            }
        }
    """
    variables = {"prompt": "Test analysis prompt for e2e flow"}
    response = await client.post(
        "/graphql",
        json={"query": submit_mutation, "variables": variables},
        headers=auth_headers,
    )
    response.raise_for_status()  # Raise exception for 4xx/5xx errors

    data = response.json()
    assert not data.get("errors"), f"GraphQL errors: {data.get('errors')}"
    submit_data = data["data"]["submitAnalysisRequest"]
    assert not submit_data["userErrors"], f"User errors: {submit_data['userErrors']}"
    assert submit_data["analysisRequest"]["id"] is not None
    # Assuming it starts in 'pending' or similar state after queuing
    assert submit_data["analysisRequest"]["status"] in ["PENDING", "QUEUED"]
    request_id = submit_data["analysisRequest"]["id"]

    # 2. (Optional) Briefly check if status updates via query (might need delay/polling in real test)
    # This basic check assumes status might still be pending immediately after submission.
    # A more robust test would involve polling or checking after worker processing.
    get_request_query = """
        query GetRequest($id: ID!) {
            analysisRequest(id: $id) {
                id
                status
                prompt
            }
        }
    """
    variables = {"id": request_id}
    response = await client.post(
        "/graphql",
        json={"query": get_request_query, "variables": variables},
        headers=auth_headers,
    )
    response.raise_for_status()

    data = response.json()
    assert not data.get("errors"), f"GraphQL errors: {data.get('errors')}"
    request_data = data["data"]["analysisRequest"]
    assert request_data["id"] == request_id
    assert request_data["status"] in [
        "PENDING",
        "QUEUED",
        "PROCESSING",
    ]  # Allow for quick processing
    assert request_data["prompt"] == "Test analysis prompt for e2e flow"


@pytest.mark.asyncio
async def test_hitl_action_approval_flow(client: AsyncClient, auth_headers: dict):
    """
    Tests listing pending actions and approving one.
    Assumes 'listProposedActions' query and 'userApprovesAction' mutation exist.
    Requires a pending action to be present in the DB for the test user (setup via fixture needed).
    """
    # TODO: Add a pytest fixture to ensure a ProposedAction record exists for the test user
    # Example fixture setup (in conftest.py or similar):
    # @pytest.fixture
    # async def pending_action(db_session, test_user):
    #     action = ProposedAction(
    #         user_id=test_user.id,
    #         analysis_request_id=SOME_ANALYSIS_ID, # Link to a relevant analysis request
    #         status='PROPOSED',
    #         action_type='SHOPIFY_CREATE_DISCOUNT',
    #         description='Propose 10% discount',
    #         parameters={'code': 'TEST10', 'value': 10.0}
    #     )
    #     db_session.add(action)
    #     await db_session.commit()
    #     await db_session.refresh(action)
    #     yield action
    #     # Cleanup if needed
    #     await db_session.delete(action)
    #     await db_session.commit()

    # Assume `pending_action` fixture is used and provides the action ID

    # 1. List Proposed Actions (Assuming one exists via fixture)
    list_query = """
        query ListActions {
            listProposedActions { # Assuming pagination might exist, adjust if needed
                id
                status
                description
                actionType
            }
        }
    """
    response = await client.post(
        "/graphql", json={"query": list_query}, headers=auth_headers
    )
    response.raise_for_status()
    data = response.json()
    assert not data.get("errors"), f"GraphQL errors: {data.get('errors')}"
    actions = data["data"]["listProposedActions"]
    assert isinstance(actions, list)

    # Find the proposed action (replace with ID from fixture if available)
    proposed_action = next((a for a in actions if a["status"] == "PROPOSED"), None)
    assert (
        proposed_action is not None
    ), "No proposed action found for test user (ensure fixture runs)"
    action_id_to_approve = proposed_action["id"]

    # 2. Approve the Action
    approve_mutation = """
        mutation Approve($actionId: ID!) {
            userApprovesAction(input: { actionId: $actionId }) {
                proposedAction {
                    id
                    status # Should change from PROPOSED
                }
                userErrors { message field }
            }
        }
    """
    variables = {"actionId": action_id_to_approve}
    response = await client.post(
        "/graphql",
        json={"query": approve_mutation, "variables": variables},
        headers=auth_headers,
    )
    response.raise_for_status()

    data = response.json()
    assert not data.get("errors"), f"GraphQL errors: {data.get('errors')}"
    approve_data = data["data"]["userApprovesAction"]
    assert not approve_data["userErrors"], f"User errors: {approve_data['userErrors']}"
    assert approve_data["proposedAction"]["id"] == action_id_to_approve
    # Assuming approval triggers background task, status might become APPROVED or EXECUTING quickly
    assert approve_data["proposedAction"]["status"] in ["APPROVED", "EXECUTING"]

    # 3. (Optional) Verify action status update (might need delay/polling)
    # Query the specific action again to confirm status change persists.
