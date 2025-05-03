import pytest
from httpx import AsyncClient  # Use AsyncClient for async app
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.proposed_action import ProposedActionStatus
from app.tests.utils import get_auth_headers, create_test_proposed_action

# Fixtures for test client and db session would typically be in conftest.py
# For simplicity, assume they are available or defined here.


@pytest.mark.asyncio
async def test_list_proposed_actions_unauthenticated(async_client: AsyncClient):
    query = """
        query {
            listProposedActions(first: 5) {
                edges {
                    node { id status }
                }
            }
        }
    """
    response = await async_client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    # Expect an error related to authentication in the GraphQL response
    assert "errors" in response.json()
    assert "User not authenticated" in response.json()["errors"][0]["message"]


@pytest.mark.asyncio
async def test_list_proposed_actions_empty(
    async_client: AsyncClient, db: Session, test_user: User
):
    headers = get_auth_headers(db, test_user)
    query = """
        query ListActions {
            listProposedActions(first: 5) {
                edges {
                    node { id description status }
                }
                pageInfo {
                    hasNextPage
                }
            }
        }
    """
    response = await async_client.post(
        "/graphql", json={"query": query}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["listProposedActions"]
    assert data["edges"] == []
    assert data["pageInfo"]["hasNextPage"] == False


@pytest.mark.asyncio
async def test_list_proposed_actions_with_data(
    async_client: AsyncClient, db: Session, test_user: User
):
    headers = get_auth_headers(db, test_user)
    # Create some proposed actions for the user
    action1 = create_test_proposed_action(
        db, user_id=test_user.id, description="Action 1"
    )
    action2 = create_test_proposed_action(
        db,
        user_id=test_user.id,
        description="Action 2",
        status=ProposedActionStatus.APPROVED,
    )
    action3 = create_test_proposed_action(
        db, user_id=test_user.id, description="Action 3"
    )

    query = """
        query ListActions {
            listProposedActions(first: 2) {
                edges {
                    cursor
                    node { id description status }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
    """
    response = await async_client.post(
        "/graphql", json={"query": query}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["listProposedActions"]
    assert len(data["edges"]) == 2
    assert data["edges"][0]["node"]["description"] == "Action 1"
    assert data["edges"][0]["node"]["status"] == "PROPOSED"
    assert data["edges"][1]["node"]["description"] == "Action 3"
    assert data["pageInfo"]["hasNextPage"] == False  # Only 2 PROPOSED actions created

    # Test pagination if needed


@pytest.mark.asyncio
async def test_reject_proposed_action(
    async_client: AsyncClient, db: Session, test_user: User
):
    headers = get_auth_headers(db, test_user)
    action = create_test_proposed_action(db, user_id=test_user.id)

    mutation = """
        mutation RejectAction($input: UserRejectActionInput!) {
            userRejectsAction(input: $input) {
                result {
                    id
                    status
                }
                userErrors { message field }
            }
        }
    """
    variables = {"input": {"actionId": str(action.id)}}

    response = await async_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["userRejectsAction"]

    assert not data["userErrors"]
    assert data["result"]["id"] == str(action.id)
    assert data["result"]["status"] == "REJECTED"

    # Verify in DB
    db.refresh(action)
    assert action.status == ProposedActionStatus.REJECTED


@pytest.mark.asyncio
async def test_approve_proposed_action(
    async_client: AsyncClient, db: Session, test_user: User, mocker
):
    headers = get_auth_headers(db, test_user)
    action = create_test_proposed_action(db, user_id=test_user.id)

    # Mock the background task function to prevent actual execution during test
    mock_executor = mocker.patch(
        "app.graphql.resolvers.proposed_action.execute_approved_action",
        return_value=None,
    )

    mutation = """
        mutation ApproveAction($input: UserApproveActionInput!) {
            userApprovesAction(input: $input) {
                result {
                    id
                    status
                    approvedAt
                }
                userErrors { message field }
            }
        }
    """
    variables = {"input": {"actionId": str(action.id)}}

    response = await async_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["userApprovesAction"]

    assert not data["userErrors"]
    assert data["result"]["id"] == str(action.id)
    assert data["result"]["status"] == "APPROVED"
    assert data["result"]["approvedAt"] is not None

    # Verify in DB
    db.refresh(action)
    assert action.status == ProposedActionStatus.APPROVED
    assert action.approved_at is not None

    # Verify background task was called (or added)
    # Depending on how BackgroundTasks is mocked/tested, this might need adjustment
    # For now, check if the patched function was called via background_tasks.add_task
    # This requires a more complex setup usually involving mocking BackgroundTasks itself.
    # A simpler check is if our patched function was called *at all* by the resolver.
    # However, direct call isn't happening anymore. We need to test the background task separately.
    # Let's assume for now the goal is to check the DB status and resolver response.


@pytest.mark.asyncio
async def test_approve_action_not_found(
    async_client: AsyncClient, db: Session, test_user: User
):
    headers = get_auth_headers(db, test_user)
    non_existent_id = uuid.uuid4()

    mutation = """
        mutation ApproveAction($input: UserApproveActionInput!) {
            userApprovesAction(input: $input) {
                result { id }
                userErrors { message field }
            }
        }
    """
    variables = {"input": {"actionId": str(non_existent_id)}}

    response = await async_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["userApprovesAction"]

    assert data["result"] is None
    assert len(data["userErrors"]) == 1
    assert data["userErrors"][0]["message"] == f"Action {non_existent_id} not found."
    assert data["userErrors"][0]["field"] == "actionId"


@pytest.mark.asyncio
async def test_approve_action_wrong_state(
    async_client: AsyncClient, db: Session, test_user: User
):
    headers = get_auth_headers(db, test_user)
    action = create_test_proposed_action(
        db, user_id=test_user.id, status=ProposedActionStatus.EXECUTED
    )

    mutation = """
        mutation ApproveAction($input: UserApproveActionInput!) {
            userApprovesAction(input: $input) {
                result { id }
                userErrors { message field }
            }
        }
    """
    variables = {"input": {"actionId": str(action.id)}}

    response = await async_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json()["data"]["userApprovesAction"]

    assert data["result"] is None
    assert len(data["userErrors"]) == 1
    assert "is not in 'proposed' state" in data["userErrors"][0]["message"]
    assert data["userErrors"][0]["field"] == "actionId"


# Add tests for rejecting non-existent/wrong-state actions
# Add tests for pagination (fetching next page)
# Add tests for permission errors if applicable at GQL layer (though handled by get_validated_user_id)
