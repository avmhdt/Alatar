"""Placeholder script for evaluating agent performance using LangSmith.

This script should:
1. Load a benchmark dataset (e.g., from benchmarks/sample_eval_dataset.jsonl).
2. Define evaluation criteria (correctness, robustness, efficiency, etc.).
3. Instantiate the agent/chain to be evaluated.
4. Run the agent against the dataset using LangSmith's evaluation utilities.
5. Log results to LangSmith.

Refer to LangSmith documentation for details:
https://docs.smith.langchain.com/evaluation
"""

import json
from pathlib import Path

from langsmith import Client
from langsmith.evaluation import evaluate
from langsmith.utils import LangSmithError

# Ensure LangSmith environment variables are set:
# os.environ["LANGCHAIN_TRACING_V2"] = "true"
# os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
# os.environ["LANGCHAIN_API_KEY"] = "YOUR_LANGSMITH_API_KEY"
# os.environ["LANGCHAIN_PROJECT"] = "YOUR_LANGSMITH_PROJECT_NAME" # Optional: Project name

import logging

logger = logging.getLogger(__name__)


def load_agent():
    """Load the agent runnable to be evaluated."""
    try:
        # Adjust the import path based on your actual agent orchestrator structure
        from app.agents.orchestrator import get_graph_runnable

        logger.info("Loading agent from app.agents.orchestrator...")
        # Assuming get_graph_runnable requires no arguments or uses env vars for config
        agent_runnable = get_graph_runnable()
        return agent_runnable
    except ImportError as e:
        logger.error(f"Warning: Could not import agent orchestrator: {e}")
        logger.info("Using placeholder agent for evaluation.")
        return lambda inputs: {"output": f"Processed: {inputs.get('input', '')}"}
    except Exception as e:
        logger.error(f"Error loading agent: {e}")
        logger.info("Using placeholder agent for evaluation.")
        return lambda inputs: {"output": f"Processed: {inputs.get('input', '')}"}


def load_dataset_from_langsmith(client: Client, dataset_name: str) -> list | None:
    """Attempts to load the dataset from LangSmith."""
    try:
        logger.info(f"Attempting to load dataset '{dataset_name}' from LangSmith...")
        examples = list(client.list_examples(dataset_name=dataset_name))
        if not examples:
            logger.debug(f"Dataset '{dataset_name}' is empty or not found in LangSmith.")
            return None
        logger.info(
            f"Successfully loaded {len(examples)} examples from LangSmith dataset '{dataset_name}'."
        )
        return examples
    except LangSmithError as e:
        logger.error(f"LangSmith API error loading dataset '{dataset_name}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading dataset '{dataset_name}' from LangSmith: {e}")
        return None


def load_dataset_from_local_file(
    file_path: Path = Path("benchmarks/sample_eval_dataset.jsonl"),
) -> list | None:
    """Loads the dataset from a local JSON Lines file."""
    if not file_path.is_file():
        logger.error(f"Error: Local benchmark file not found at {file_path}")
        return None

    logger.info(f"Loading dataset from local file: {file_path}")
    examples = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if line.strip() and not line.strip().startswith("#"):
                    try:
                        examples.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(
                            f"Warning: Skipping invalid JSON on line {i+1} in {file_path}: {e}"
                        )
        logger.info(f"Successfully loaded {len(examples)} examples from {file_path}.")
        return examples
    except Exception as e:
        logger.error(f"Error reading local benchmark file {file_path}: {e}")
        return None


def evaluate_agent():
    """Runs the evaluation using LangSmith."""
    try:
        client = Client()
    except LangSmithError as e:
        logger.error(f"Error initializing LangSmith client: {e}")
        logger.info(
            "Please ensure LANGCHAIN_API_KEY and other environment variables are set."
        )
        return

    agent_runnable = load_agent()
    dataset_name = "alatar-benchmark-v1"  # Choose a descriptive name

    # Attempt to load dataset first from LangSmith, then fallback to local file
    dataset = load_dataset_from_langsmith(client, dataset_name)
    if dataset is None:
        dataset = load_dataset_from_local_file()

    if dataset is None or not dataset:
        logger.error("Error: No dataset loaded. Cannot run evaluation.")
        return

    # Define evaluation metrics/functions (customize as needed)
    # See: https://docs.smith.langchain.com/evaluation/evaluator-implementations
    def check_output_length(run, example):
        """Simple example evaluator: Checks if output length is greater than 5."""
        if run.outputs and "output" in run.outputs:
            return {
                "key": "output_length_gt_5",
                "score": len(run.outputs["output"]) > 5,
            }
        return {"key": "output_length_gt_5", "score": False}

    try:
        logger.info(f"Starting evaluation with {len(dataset)} examples...")
        results = evaluate(
            agent_runnable,
            data=dataset,  # Use the loaded dataset
            evaluators=[check_output_length],
            experiment_prefix=f"agent-evaluation-{dataset_name}",
            metadata={
                "agent_version": "0.1.0",
                "description": "Initial evaluation run for Alatar agent.",
            },
            # Ensure these keys match your dataset structure and agent output
            # input_key="input", # Default: LangSmith uses the 'inputs' key from the dataset examples
            # prediction_key="output", # Default: LangSmith uses the 'output' key from the run outputs
            # reference_key="output", # Default: LangSmith uses the 'outputs' key from the dataset examples
        )
        logger.info("Evaluation completed. Results:")
        # Results object contains detailed information, often best viewed in LangSmith UI
        logger.info(results)

    except LangSmithError as e:
        logger.error(f"An error occurred during LangSmith evaluation: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during evaluation: {e}")


if __name__ == "__main__":
    evaluate_agent()
