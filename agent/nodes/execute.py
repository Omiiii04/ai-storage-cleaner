from loguru import logger
from agent.state import AgentState
from core.executor import execute_actions


def execute_actions_node(state: AgentState) -> AgentState:
    """Node 6 — execute the confirmed action plan."""
    logger.info("━━━ NODE: execute ━━━")
    results = execute_actions(
        state.get("action_plan", []),
        dry_run=state.get("dry_run", True),
        max_deletes=state.get("max_deletes"),
    )
    return {**state, "execution_results": results}
