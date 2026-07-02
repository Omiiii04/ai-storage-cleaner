"""
AgentState — the single state object threaded through every LangGraph node.

pc_dirs and mobile_dirs carry the resolved folder lists from CLI / interactive
input into the scan node, overriding .env defaults when provided.
"""
from typing import Optional, TypedDict

from utils.models import Action, ActionResult, DuplicateGroup, PhotoRecord


class AgentState(TypedDict, total=False):

    # ── Set at invoke time ────────────────────────────────────
    dry_run: bool
    skip_mobile: bool
    skip_google: bool
    hamming_threshold: int
    max_deletes: Optional[int]

    # ── Dynamic folder selection (CLI / interactive) ──────────
    # Empty list → fall back to .env defaults in StorageManager
    pc_dirs: list[str]        # resolved local folder paths (string form for serialisation)
    mobile_dirs: list[str]    # resolved on-device folder paths

    # ── scan_node → extract_node ──────────────────────────────
    scan_results: dict[str, list[PhotoRecord]]

    # ── detect_node → plan_node ───────────────────────────────
    duplicate_groups: list[DuplicateGroup]

    # ── plan_node → confirm_node ──────────────────────────────
    action_plan: list[Action]

    # ── confirm_node → execute_node (conditional) ────────────
    user_confirmed: bool

    # ── execute_node → report_node ────────────────────────────
    execution_results: list[ActionResult]

    # ── report_node ───────────────────────────────────────────
    report: dict
