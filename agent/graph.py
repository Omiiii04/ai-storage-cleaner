"""
LangGraph pipeline: scan → extract → detect → plan → confirm → execute → report
The conditional edge at 'confirm' aborts cleanly if user says no (or dry-run).
"""
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes.confirm import confirm_with_user_node
from agent.nodes.detect import detect_duplicates_node
from agent.nodes.execute import execute_actions_node
from agent.nodes.extract import extract_metadata_node
from agent.nodes.plan import apply_rules_node
from agent.nodes.report import generate_report_node
from agent.nodes.scan import scan_node
from agent.state import AgentState


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # ── Register nodes ────────────────────────────────────────
    builder.add_node("scan",    scan_node)
    builder.add_node("extract", extract_metadata_node)
    builder.add_node("detect",  detect_duplicates_node)
    builder.add_node("plan",    apply_rules_node)
    builder.add_node("confirm", confirm_with_user_node)
    builder.add_node("execute", execute_actions_node)
    builder.add_node("report",  generate_report_node)

    # ── Linear edges ──────────────────────────────────────────
    builder.set_entry_point("scan")
    for src, dst in [
        ("scan",    "extract"),
        ("extract", "detect"),
        ("detect",  "plan"),
        ("plan",    "confirm"),
    ]:
        builder.add_edge(src, dst)

    # ── Conditional: only execute if user confirmed ───────────
    builder.add_conditional_edges(
        "confirm",
        lambda s: "execute" if s.get("user_confirmed") else END,
    )
    builder.add_edge("execute", "report")
    builder.add_edge("report", END)

    return builder.compile(checkpointer=MemorySaver())


# Singleton — import this in main.py
graph = build_graph()
