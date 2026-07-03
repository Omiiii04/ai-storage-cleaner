"""
Node 5 — Show the action plan and ask for confirmation.

KEY FIX: adds a clear, actionable warning when:
    - All photos are SKIP
    - Google Photos was not scanned (--skip-google)

This is the most common first-run confusion: the agent scans PC + mobile,
finds no cloud backups to compare against, and skips everything. The user
sees thousands of SKIP rows (now collapsed to a summary) and wonders if
the agent is broken. It's not — it needs Google Photos.
"""
from loguru import logger
from rich.console import Console
from rich.prompt import Confirm

from agent.state import AgentState
from core.executor import print_action_table

console = Console()


def confirm_with_user_node(state: AgentState) -> AgentState:
    logger.info("━━━ NODE: confirm ━━━")
    action_plan = state.get("action_plan", [])
    dry_run     = state.get("dry_run", True)
    skip_google = state.get("skip_google", False)
    scan_results = state.get("scan_results", {})

    print_action_table(action_plan)

    # ── Explain all-skip when Google Photos was skipped ────────
    all_skip    = all(a.type == "SKIP" for a in action_plan) if action_plan else True
    has_mobile  = "mobile" in scan_results
    has_pc      = "pc" in scan_results

    if all_skip and skip_google and (has_mobile or has_pc):
        sources = []
        if has_pc:
            sources.append(f"{len(scan_results.get('pc', []))} PC photos")
        if has_mobile:
            sources.append(f"{len(scan_results.get('mobile', []))} mobile photos")
        found = " and ".join(sources)

        console.print(
            f"\n[yellow bold]⚠  Everything skipped — this is expected.[/yellow bold]\n"
            f"\n"
            f"  Found {found} — but [bold]Google Photos was not scanned[/bold].\n"
            f"  The agent only deletes a local photo when it has a [bold]hash-confirmed\n"
            f"  backup on Google Photos[/bold]. Without that confirmation it skips\n"
            f"  everything rather than risk deleting an unbacked-up photo.\n"
            f"\n"
            f"  [bold]To enable duplicate detection:[/bold]\n"
            f"  1. Complete Google Photos setup (README → Setup step 3)\n"
            f"     google.cloud.console → enable Photos Library API → OAuth creds\n"
            f"     → save as client_secret.json\n"
            f"  2. Run without [bold cyan]--skip-google[/bold cyan]:\n"
            f"     [cyan]python main.py run --dry-run[/cyan]\n"
            f"  3. A browser tab opens for sign-in on first run — token is\n"
            f"     cached at [dim]~/.photo_agent_token.json[/dim] afterward\n"
            f"\n"
            f"  [dim]Until then, scan + index runs are still useful for building\n"
            f"  the hash cache so the first real run is faster.[/dim]"
        )

    # ── Dry-run gate ───────────────────────────────────────────
    if dry_run:
        console.print(
            "\n[yellow bold]DRY RUN[/yellow bold] — "
            "pass [bold]--execute[/bold] to apply changes.\n"
        )
        return {**state, "user_confirmed": False}

    executable = [a for a in action_plan if a.type != "SKIP"]
    if not executable:
        console.print("\n[green]Nothing to execute — no actionable items.[/green]")
        return {**state, "user_confirmed": False}

    console.print()
    confirmed = Confirm.ask(
        f"Execute [bold]{len(executable)}[/bold] action(s)?",
        default=False,
    )
    return {**state, "user_confirmed": confirmed}
