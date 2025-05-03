import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Assuming you have fixtures for creating users and getting authenticated clients
# like `create_user`, `get_authenticated_client` defined in conftest.py or similar.
# Also assuming fixtures for db session (`db_session`) and async client (`client`) exist.

# Import models needed for creating test data
from app.models import AnalysisRequest


@pytest.mark.asyncio
async def test_rls_prevents_cross_user_read_graphql(
    client: AsyncClient,  # Unauthenticated client
    db_session: AsyncSession,
    create_user,  # Fixture to create a user
    get_authenticated_client,  # Fixture to get client authenticated as a user
):
    """Verify RLS prevents User B reading User A's data via GraphQL."""
    # 1. Create User A and User B
    user_a_data = {"email": "user_a@testrls.com", "password": "passworda"}
    user_b_data = {"email": "user_b@testrls.com", "password": "passwordb"}
    user_a = await create_user(db_session, **user_a_data)
    user_b = await create_user(db_session, **user_b_data)

    # 2. Create data for User A (e.g., AnalysisRequest)
    # Note: RLS applies during INSERT too. We need to bypass RLS or set context correctly.
    # For testing setup, directly creating via model might bypass application-level checks
    # but might hit RLS if not careful about session context.
    # A safer approach is to use User A's authenticated client if an API endpoint exists.
    # Let's assume direct creation for simplicity, acknowledging this caveat.
    # If direct creation fails due to RLS, we'll need a helper that sets context.
    request_a = AnalysisRequest(
        user_id=user_a.id,
        prompt="Analyze User A's data",
        status="PENDING",
        shop_domain="store-a.myshopify.com",
    )
    db_session.add(request_a)
    await db_session.commit()
    await db_session.refresh(request_a)
    request_a_gql_id = f"AnalysisRequest:{request_a.id}"  # Example Relay ID

    # 3. Get authenticated client for User B
    client_b = await get_authenticated_client(
        client, user_b_data["email"], user_b_data["password"]
    )

    # 4. User B attempts to query User A's AnalysisRequest via GraphQL node query
    # (Assuming a standard Relay node query exists)
    node_query = f"""
        query GetNode {{
            node(id: "{request_a_gql_id}") {{
                id
                ... on AnalysisRequest {{
                    prompt
                    status
                    userId # Exposing user_id in GQL might be a leak itself
                }}
            }}
        }}
    """
    response = await client_b.post("/graphql", json={"query": node_query})

    # 5. Assert User B cannot retrieve User A's data
    assert response.status_code == 200
    response_data = response.json()

    # Check for errors, although RLS might just return null for the node
    if "errors" in response_data:
        print("GraphQL Errors:", response_data["errors"])
        # Depending on error handling, RLS might cause a specific error or just null data
        # assert any("permission denied" in err.get("message", "").lower() for err in response_data["errors"])

    # The primary check: node should be null because RLS prevents access
    assert response_data["data"] is not None, "Data field should exist"
    assert response_data["data"]["node"] is None, "User B should not see User A's node"

    # Optional: Verify User A *can* see their own data
    client_a = await get_authenticated_client(
        client, user_a_data["email"], user_a_data["password"]
    )
    response_a = await client_a.post("/graphql", json={"query": node_query})
    assert response_a.status_code == 200
    response_a_data = response_a.json()
    assert "errors" not in response_a_data
    assert response_a_data["data"]["node"] is not None
    assert response_a_data["data"]["node"]["id"] == request_a_gql_id
    assert response_a_data["data"]["node"]["prompt"] == "Analyze User A's data"

    # Add similar tests for other RLS-protected tables (LinkedAccount, AgentTask, etc.)
    # Add tests for mutations (UPDATE, DELETE) if applicable GQL mutations exist.
