from enum import Enum

# Define queue names based on Section 6 of implementation plan
# and extending for Class 2 departments and potential responses
INPUT_QUEUE = "q.c1_input"  # Queue for initial requests to Class 1 Orchestrator
C2_DATA_RETRIEVAL_QUEUE = "q.c2.data_retrieval"
C2_QUANTITATIVE_ANALYSIS_QUEUE = "q.c2.quantitative_analysis"
C2_QUALITATIVE_ANALYSIS_QUEUE = "q.c2.qualitative_analysis"
C2_RECOMMENDATION_GENERATION_QUEUE = "q.c2.recommendation_generation"
# Add other C2 queues as needed...
# Example response queue pattern (optional, depending on C1/C2 communication design)
# RESPONSE_QUEUE_PREFIX = "q.response."


class AgentDepartment(Enum):
    """Enumeration for Class 2 Agent Departments."""

    DATA_RETRIEVAL = "Data Retrieval"
    QUANTITATIVE_ANALYSIS = "Quantitative Analysis"
    QUALITATIVE_ANALYSIS = "Qualitative Analysis"
    RECOMMENDATION_GENERATION = "Recommendation Generation"
    # Add other departments as needed...


# Map departments to their input queues
DEPARTMENT_QUEUES = {
    AgentDepartment.DATA_RETRIEVAL: C2_DATA_RETRIEVAL_QUEUE,
    AgentDepartment.QUANTITATIVE_ANALYSIS: C2_QUANTITATIVE_ANALYSIS_QUEUE,
    AgentDepartment.QUALITATIVE_ANALYSIS: C2_QUALITATIVE_ANALYSIS_QUEUE,
    AgentDepartment.RECOMMENDATION_GENERATION: C2_RECOMMENDATION_GENERATION_QUEUE,
    # Add mappings for other departments...
}


# Agent/Task Statuses (aligning with Phase 5 and extending for Phase 6)
class AgentTaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"  # Added for Phase 6 retry logic
    # Add other statuses if needed (e.g., waiting_for_approval)


# Placeholder for default retry limits
DEFAULT_RETRY_LIMIT = 5

# XML Tags for Prompt Engineering (Phase 6.5)
PROMPT_DATA_TAG_START = "<data>"
PROMPT_DATA_TAG_END = "</data>"
PROMPT_INSTRUCTION_TAG_START = "<instruction>"
PROMPT_INSTRUCTION_TAG_END = "</instruction>"
