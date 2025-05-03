import pytest
import uuid
from unittest.mock import patch, AsyncMock, MagicMock

# Import components to test
from app.agents.orchestrator import (
    create_orchestrator_graph,
    OrchestratorState,
    # Import nodes/functions if testing them directly
    # _publish_to_department_queue,
    # _create_agent_task_record
)
from app.agents.constants import AgentDepartment, AgentTaskStatus

# Test containers or fixtures for DB/Queue would be defined in conftest.py typically
# from ..conftest import test_db_session, rabbitmq_container


@pytest.mark.asyncio  # Mark test as async if using async components
async def test_orchestrator_full_flow_success(test_db_session, monkeypatch):
    """Integration test for a successful orchestrator flow (placeholder)."""
    analysis_request_id = uuid.uuid4()
    user_id = uuid.uuid4()
    shop_domain = "integ-test.myshopify.com"
    prompt = "Analyze my product performance for the last week."

    initial_state = OrchestratorState(
        analysis_request_id=analysis_request_id,
        user_id=user_id,
        shop_domain=shop_domain,
        original_prompt=prompt,
        plan=None,
        dispatched_tasks=[],
        aggregated_results={},
        final_result=None,
        error=None,
    )
    config = {"configurable": {"thread_id": str(analysis_request_id)}}

    # --- Mocking Dependencies ---
    # Mock LLM calls within nodes
    mock_plan = [
        {
            "step": 1,
            "department": AgentDepartment.DATA_RETRIEVAL,
            "task_details": {"tool_name": "get_shopify_products"},
            "description": "Get products",
        },
        {
            "step": 2,
            "department": AgentDepartment.QUANTITATIVE_ANALYSIS,
            "task_details": {"analysis_prompt": "Summarize"},
            "description": "Summarize products",
        },
    ]
    mock_final_summary = "Products analyzed successfully."

    # Patch the LLM clients used in the nodes
    # Note: Patch targets need to be correct based on where ChatOpenAI is instantiated
    with patch(
        "app.agents.orchestrator.ChatOpenAI", new_callable=MagicMock
    ) as MockPlannerLLM:
        # Configure separate mocks if planner and aggregator use different instances/chains
        planner_instance = MockPlannerLLM.return_value
        aggregator_instance = (
            MockPlannerLLM.return_value
        )  # Assuming same mock for simplicity

        # Mock the output parser behavior if needed, or mock the chain's invoke directly
        # Simplest: Mock the chain's invoke result
        with patch.object(
            planner_instance.__or__(MagicMock()), "invoke", return_value=mock_plan
        ) as mock_plan_invoke, patch.object(
            aggregator_instance.__or__(MagicMock()),
            "invoke",
            return_value=mock_final_summary,
        ) as mock_agg_invoke:
            # Mock DB interactions (_create_agent_task_record, _check_c2_task_status, _save_state_to_db, _load_state_from_db)
            # Use monkeypatch for simplicity or dedicated mock fixtures
            # Mock _create_agent_task_record to return a predictable UUID
            mock_task_id_1 = uuid.uuid4()
            mock_task_id_2 = uuid.uuid4()
            create_task_mock = MagicMock(side_effect=[mock_task_id_1, mock_task_id_2])
            monkeypatch.setattr(
                "app.agents.orchestrator._create_agent_task_record", create_task_mock
            )

            # Mock _check_c2_task_status to simulate task completion
            def mock_check_status(db, task_ids):
                status_map = {}
                # Simulate Data Retrieval completing first
                if mock_task_id_1 in task_ids:
                    status_map[mock_task_id_1] = (
                        AgentTaskStatus.COMPLETED,
                        {"data": "retrieved"},
                        None,
                    )
                # Simulate Quant Analysis completing after Data Retrieval result is available
                if mock_task_id_2 in task_ids:
                    # Assume it needs result from task 1, check if available in state (implicitly)
                    # For simplicity, just mark as completed in the second check
                    status_map[mock_task_id_2] = (
                        AgentTaskStatus.COMPLETED,
                        {"summary": "analyzed"},
                        None,
                    )
                # Simulate pending/running states if needed for more complex tests
                return status_map

            check_status_mock = MagicMock(side_effect=mock_check_status)
            monkeypatch.setattr(
                "app.agents.orchestrator._check_c2_task_status", check_status_mock
            )

            # Mock queue publishing
            publish_mock = AsyncMock()  # Use AsyncMock if publish is async
            monkeypatch.setattr(
                "app.agents.orchestrator._publish_to_department_queue", publish_mock
            )

            # Mock state saving/loading (Checkpointer)
            # If using SqlAlchemyCheckpoint, mock its get/put methods or _load/_save directly
            save_state_mock = MagicMock()
            load_state_mock = MagicMock(return_value=None)  # Simulate starting fresh
            monkeypatch.setattr(
                "app.agents.orchestrator._save_state_to_db", save_state_mock
            )
            monkeypatch.setattr(
                "app.agents.orchestrator._load_state_from_db", load_state_mock
            )

            # --- Execute Graph ---
            # Need to handle DB session injection properly for the graph nodes
            # For this test, we can patch the node_wrapper or pass the test_db_session if wrapper is modified

            # Assuming node_wrapper uses the placeholder DB=None for now
            graph = (
                create_orchestrator_graph().compile()
            )  # Compile without checkpointer for direct invoke test

            final_state = await graph.ainvoke(initial_state, config=config)

            # --- Assertions ---
            assert final_state["error"] is None
            assert (
                final_state["plan"] == mock_plan
            )  # Plan should match mocked LLM output
            assert len(final_state["dispatched_tasks"]) == 2
            assert (
                final_state["dispatched_tasks"][0]["status"]
                == AgentTaskStatus.COMPLETED
            )
            assert (
                final_state["dispatched_tasks"][1]["status"]
                == AgentTaskStatus.COMPLETED
            )
            assert str(mock_task_id_1) in final_state["aggregated_results"]
            assert str(mock_task_id_2) in final_state["aggregated_results"]
            assert final_state["final_result"] == mock_final_summary

            # Check mocks were called
            assert mock_plan_invoke.call_count == 1
            assert publish_mock.call_count == 2
            assert create_task_mock.call_count == 2
            # Check status calls might be multiple depending on graph loops
            assert check_status_mock.call_count > 0
            assert mock_agg_invoke.call_count == 1
            # Assert save_state was called (implicitly via checkpointer if used, or manually if not)
            # save_state_mock.assert_called() # This needs checkpointer integration


# Add more integration tests:
# - Test failure in planning node
# - Test failure in C2 task (check handle_error node)
# - Test failure during aggregation
# - Test graph resumability (using checkpointer mocks)
# - Test dependency handling between C2 tasks

# If you want to add more tests, you can define additional test functions here
