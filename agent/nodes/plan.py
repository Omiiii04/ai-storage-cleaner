from loguru import logger
from agent.state import AgentState
from core.rule_engine import apply_rules


def apply_rules_node(state: AgentState) -> AgentState:
    """Node 4 — apply rule engine to duplicate groups, produce action plan."""
    logger.info("━━━ NODE: plan ━━━")
    action_plan = apply_rules(state.get("duplicate_groups", []))
    return {**state, "action_plan": action_plan}
