# Integration tests for the GraphQL API endpoint

import pytest
from httpx import AsyncClient
from typing import Optional

# Assuming a fixture `test_client` provides an AsyncClient instance configured for the app
# This might be defined in tests/conftest.py
# from ..conftest import test_client # Example import

# --- Test Setup (Placeholders) ---

# TODO: Define test users, potentially created via fixtures or setup functions
TEST_USER_EMAIL = "test_gql_user@example.com"
TEST_USER_PASSWORD = "TestPassword123!"


async def get_auth_token(
    client: AsyncClient,
    email: str = TEST_USER_EMAIL,
    password: str = TEST_USER_PASSWORD,
) -> Optional[str]:
    """Helper to register (if needed) and login a user to get an auth token."""
    # Simplified: Assumes login mutation exists and works.
    # Real implementation might need registration first or pre-populated test users.
    login_mutation = """
        mutation Login($email: String!, $password: String!) {
            login(input: {email: $email, password: $password}) {
                token
                userErrors { field message }
            }
        }
    """
    variables = {"email": email, "password": password}
    response = await client.post(
        "/graphql", json={"query": login_mutation, "variables": variables}
    )
    if response.status_code == 200:
        data = response.json().get("data", {}).get("login", {})
        if data.get("token"):
            return data["token"]
        else:
            print(f"Login failed for token retrieval: {data.get('userErrors')}")
    else:
        print(f"Login request failed: {response.status_code}")
    return None


# --- Test Cases ---


@pytest.mark.asyncio
async def test_graphql_me_unauthenticated(test_client: AsyncClient):
    """Test fetching 'me' query without authentication."""
    query = "{ me { id email } }"
    response = await test_client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json().get("data", {})
    # Expect 'me' to be null when not authenticated
    assert data.get("me") is None


@pytest.mark.asyncio
async def test_graphql_me_authenticated(test_client: AsyncClient):
    """Test fetching 'me' query with authentication."""
    token = await get_auth_token(test_client)
    assert token is not None, "Failed to get auth token for test"

    headers = {"Authorization": f"Bearer {token}"}
    query = "{ me { id email } }"
    response = await test_client.post(
        "/graphql", json={"query": query}, headers=headers
    )
    assert response.status_code == 200
    data = response.json().get("data", {}).get("me")
    assert data is not None
    assert data.get("email") == TEST_USER_EMAIL
    assert "id" in data


@pytest.mark.asyncio
async def test_graphql_list_requests_unauthenticated(test_client: AsyncClient):
    """Test listing analysis requests without authentication (should return empty or error)."""
    query = """
        query {
            listAnalysisRequests {
                edges { node { id status } }
                pageInfo { hasNextPage }
            }
        }
    """
    response = await test_client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    data = response.json().get("data", {}).get("listAnalysisRequests", {})
    # Expect empty edges or potentially an auth error depending on resolver implementation
    assert data.get("edges", []) == []


@pytest.mark.asyncio
async def test_graphql_list_requests_authenticated(test_client: AsyncClient):
    """Test listing analysis requests with authentication."""
    token = await get_auth_token(test_client)
    assert token is not None
    headers = {"Authorization": f"Bearer {token}"}

    query = """
        query ListReqs($first: Int, $after: String) {
            listAnalysisRequests(first: $first, after: $after) {
                edges {
                    cursor
                    node { id prompt status createdAt }
                }
                pageInfo {
                    hasNextPage
                    hasPreviousPage
                    startCursor
                    endCursor
                }
            }
        }
    """
    variables = {"first": 5}
    response = await test_client.post(
        "/graphql", json={"query": query, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json().get("data", {}).get("listAnalysisRequests", {})
    assert "edges" in data
    assert "pageInfo" in data
    # TODO: Add more specific assertions based on expected (mocked/seeded) data
    # assert len(data["edges"]) <= 5
    # assert data["pageInfo"]["hasNextPage"] is False # Assuming few test items


@pytest.mark.asyncio
async def test_graphql_submit_request_mutation(test_client: AsyncClient):
    """Test submitting a new analysis request."""
    token = await get_auth_token(test_client)
    assert token is not None
    headers = {"Authorization": f"Bearer {token}"}

    mutation = """
        mutation SubmitReq($prompt: String!) {
            submitAnalysisRequest(prompt: $prompt) {
                analysisRequest {
                    id
                    prompt
                    status
                }
                userErrors { field message }
            }
        }
    """
    variables = {"prompt": "Analyze my latest sales data."}
    response = await test_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json().get("data", {}).get("submitAnalysisRequest", {})
    assert data.get("userErrors") == []
    assert data.get("analysisRequest") is not None
    assert data["analysisRequest"].get("prompt") == variables["prompt"]
    assert data["analysisRequest"].get("status") == "PENDING"  # Assuming initial status
    assert "id" in data["analysisRequest"]


@pytest.mark.asyncio
async def test_graphql_mutation_error_handling(test_client: AsyncClient):
    """Test a mutation that should produce a UserError (e.g., invalid input)."""
    token = await get_auth_token(test_client)
    assert token is not None
    headers = {"Authorization": f"Bearer {token}"}

    # Example: Submitting request with empty prompt (assuming validation exists)
    mutation = """
        mutation SubmitReq($prompt: String!) {
            submitAnalysisRequest(prompt: $prompt) {
                analysisRequest { id }
                userErrors { field message }
            }
        }
    """
    variables = {"prompt": ""}  # Invalid empty prompt
    response = await test_client.post(
        "/graphql", json={"query": mutation, "variables": variables}, headers=headers
    )
    assert response.status_code == 200
    data = response.json().get("data", {}).get("submitAnalysisRequest", {})
    assert data.get("analysisRequest") is None
    assert len(data.get("userErrors", [])) > 0
    # TODO: Add more specific check for expected error message/field
    # assert data["userErrors"][0]["field"] == "prompt"


@pytest.mark.asyncio
async def test_graphql_pagination(test_client: AsyncClient):
    """Test cursor-based pagination logic."""
    token = await get_auth_token(test_client)
    assert token is not None
    headers = {"Authorization": f"Bearer {token}"}

    # TODO: Seed enough data (e.g., > 3 analysis requests) for this user
    # For now, just checks structure

    query = """
        query ListReqs($first: Int, $after: String) {
            listAnalysisRequests(first: $first, after: $after) {
                edges { cursor node { id } }
                pageInfo { hasNextPage startCursor endCursor }
            }
        }
    """

    # Fetch first page
    variables1 = {"first": 2}
    response1 = await test_client.post(
        "/graphql", json={"query": query, "variables": variables1}, headers=headers
    )
    assert response1.status_code == 200
    data1 = response1.json().get("data", {}).get("listAnalysisRequests", {})
    assert "edges" in data1
    assert "pageInfo" in data1
    # assert len(data1["edges"]) <= 2

    # Fetch next page if available
    # if data1["pageInfo"]["hasNextPage"] and data1["pageInfo"]["endCursor"]:
    #     variables2 = {"first": 2, "after": data1["pageInfo"]["endCursor"]}
    #     response2 = await test_client.post("/graphql", json={"query": query, "variables": variables2}, headers=headers)
    #     assert response2.status_code == 200
    #     data2 = response2.json().get("data", {}).get("listAnalysisRequests", {})
    #     assert len(data2["edges"]) > 0 # Should get some items on next page
    #     # Add checks to ensure items are different from page 1
    pass  # Placeholder until data seeding is implemented


@pytest.mark.asyncio
async def test_graphql_rate_limit(test_client: AsyncClient):
    """Test that rate limiting returns a 429 error."""
    # Note: This requires the limiter in main.py to be active and potentially
    # configured with a low limit for testing.
    # The default "100/minute" might be too high for a quick test.
    query = "{ me { id } }"  # Use a simple query

    # Rapidly send requests (adjust range based on configured limit for testing)
    # Example: If limit is 5/second for testing
    # responses = []
    # for _ in range(7):
    #     responses.append(await test_client.post("/graphql", json={"query": query}))
    #
    # # Check that at least one request got rate limited (429)
    # assert any(r.status_code == 429 for r in responses)
    pass  # Placeholder - requires specific test setup for rate limits


# TODO: Add tests for other queries/mutations (listProposedActions, approve/reject Action)
# TODO: Add tests for subscriptions (more complex, might need specific testing tools/setup)
