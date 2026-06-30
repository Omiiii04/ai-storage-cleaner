from loguru import logger
from agent.state import AgentState
from storage.manager import StorageManager


def scan_node(state: AgentState) -> AgentState:
    """Node 1 — scan all storage sources and populate scan_results."""
    logger.info("━━━ NODE: scan ━━━")
    manager = StorageManager(
        skip_google=state.get("skip_google", False),
        skip_mobile=state.get("skip_mobile", False),
    )
    scan_results = manager.scan_all()
    return {**state, "scan_results": scan_results}
