from loguru import logger
from rich.console import Console
from rich.prompt import Confirm

from agent.state import AgentState
from core.executor import print_action_table

console = Console()


def confirm_with_user_node(state: AgentState) -> AgentState:
    """
    Node 5 — show the action plan and ask for confirmation.
    In dry-run mode, always returns user_confirmed=False (no prompt shown).
    """
    logger.info("━━━ NODE: confirm ━━━")
    action_plan = state.get("action_plan", [])
    dry_run     = state.get("dry_run", True)

    print_action_table(action_plan)

    if dry_run:
        console.print(
            "\n[yellow bold]DRY RUN[/yellow bold] — "
            "pass [bold]--execute[/bold] to apply these changes.\n"
        )
        return {**state, "user_confirmed": False}

    executable = [a for a in action_plan if a.type != "SKIP"]
    if not executable:
        console.print("\n[green]Nothing to execute — everything looks clean.[/green]")
        return {**state, "user_confirmed": False}

    console.print()
    confirmed = Confirm.ask(
        f"Execute [bold]{len(executable)}[/bold] action(s)?",
        default=False,
    )
    return {**state, "user_confirmed": confirmed}
