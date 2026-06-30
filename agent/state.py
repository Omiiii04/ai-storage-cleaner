from typing import Optional, TypedDict

from utils.models import Action, ActionResult, DuplicateGroup, PhotoRecord


class AgentState(TypedDict, total=False):
    """
    Complete state object passed between all LangGraph nodes.
    Fields are populated incrementally as the pipeline progresses.
    """

    # ── Set at invoke time ────────────────────────────────────
    dry_run: bool
    skip_mobile: bool
    skip_google: bool
    hamming_threshold: int
    max_deletes: Optional[int]

    # ── scan_node → extract_node ──────────────────────────────
    scan_results: dict[str, list[PhotoRecord]]   # {source: [PhotoRecord]}

    # ── extract_node → detect_node ────────────────────────────
    # scan_results is enriched in-place with phash values

    # ── detect_node → plan_node ───────────────────────────────
    duplicate_groups: list[DuplicateGroup]

    # ── plan_node → confirm_node ──────────────────────────────
    action_plan: list[Action]

    # ── confirm_node → execute_node (conditional) ────────────
    user_confirmed: bool

    # ── execute_node → report_node ────────────────────────────
    execution_results: list[ActionResult]

    # ── report_node ───────────────────────────────────────────
    report: dict   # {stats, report_path}
