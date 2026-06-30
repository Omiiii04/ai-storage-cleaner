from loguru import logger
from agent.state import AgentState
from config import get_config
from core.duplicate_detector import detect_duplicates


def detect_duplicates_node(state: AgentState) -> AgentState:
    """Node 3 — run perceptual duplicate detection across all scanned photos."""
    logger.info("━━━ NODE: detect ━━━")
    threshold = state.get("hamming_threshold") or get_config().hamming_threshold
    groups = detect_duplicates(state.get("scan_results", {}), threshold=threshold)
    return {**state, "duplicate_groups": groups}
