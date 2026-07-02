from pathlib import Path

from loguru import logger

from agent.state import AgentState
from storage.manager import StorageManager


def scan_node(state: AgentState) -> AgentState:
    """
    Node 1 — scan all storage sources and populate scan_results.

    Reads pc_dirs / mobile_dirs from state (set by CLI or interactive mode)
    and passes them to StorageManager, which falls back to .env defaults
    when the lists are empty.
    """
    logger.info("━━━ NODE: scan ━━━")

    # Convert string paths back to Path objects for LocalScanner
    raw_pc    = state.get("pc_dirs", [])
    raw_mob   = state.get("mobile_dirs", [])
    pc_dirs    = [Path(d) for d in raw_pc]   if raw_pc   else None
    mobile_dirs = raw_mob if raw_mob else None

    manager = StorageManager(
        skip_google=state.get("skip_google", False),
        skip_mobile=state.get("skip_mobile", False),
        pc_dirs=pc_dirs,
        mobile_dirs=mobile_dirs,
    )
    scan_results = manager.scan_all()
    return {**state, "scan_results": scan_results}
