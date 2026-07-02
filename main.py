"""
photo-agent CLI
───────────────
Commands:
    scan                Scan all storages (read-only)
    run                 Full pipeline: scan → detect → plan → confirm → execute
    info                Show index location, size, and what is stored
    report              Open the most recent HTML report in your browser
    mobile-status       Diagnose ADB connection to an Android phone
    purge-trash         Permanently delete files in ~/.photo_agent_trash/
    purge-mobile-trash  Permanently delete the on-device mobile trash folder
    clear-cache         Wipe the SQLite index (forces full re-scan next run)

DYNAMIC FOLDER SELECTION
────────────────────────
  --pc-dir / --mobile-dir   explicit folder paths (repeat for multiple)
  --interactive / -i        picker UI — prompts for PC folders, shows phone folder list
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box

# Windows UTF-8 stdout fix — prevents UnicodeEncodeError on → ✓ ✗ ━ etc.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

app = typer.Typer(
    name="photo-agent",
    help="Deduplicate photos across Google Photos, PC, and mobile.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# ── Formatting helpers ──────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    if n == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_num(n: int) -> str:
    return f"{n:,}"


# ── Storage footprint panel ─────────────────────────────────────

def _print_footprint(skip_mobile: bool = False) -> None:
    """
    Print a panel showing exactly where hashes are stored, how much space
    the index uses, what is stored vs what is NOT — so the user can verify
    the agent is not consuming extra storage.
    """
    from db.store import PhotoStore

    store = PhotoStore()

    # Handle first-run case (DB may not exist yet)
    try:
        s = store.stats()
    except Exception:
        console.print("[dim]Index not yet created — run scan first.[/dim]")
        return

    if s["total"] == 0:
        console.print("[dim]No photos indexed yet.[/dim]")
        return

    db_path      = s["db_path"]
    db_bytes     = s["db_size_bytes"]
    lib_bytes    = s["total_photo_bytes"]
    ratio_pct    = (db_bytes / lib_bytes * 100) if lib_bytes > 0 else 0
    last_indexed = s.get("last_indexed", "—") or "—"

    # Temp cache path (always cleared after each run)
    tmp_cache = Path(tempfile.gettempdir()) / "photo_agent_adb_cache"
    cache_exists = tmp_cache.exists() and any(tmp_cache.iterdir())
    cache_status = (
        f"[red]{tmp_cache}[/red]  ⚠  not cleared yet"
        if cache_exists
        else f"[dim]{tmp_cache}[/dim]  [green]cleared ✓[/green]"
    )

    # ── Source breakdown table ─────────────────────────────────
    src_table = Table(box=None, show_header=True, padding=(0, 3), show_edge=False)
    src_table.add_column("Source",  style="green",  min_width=16)
    src_table.add_column("Indexed", justify="right", min_width=10)
    src_table.add_column("Hashed",  justify="right", min_width=10)
    src_table.add_column("",        style="dim",     min_width=30)

    for source, data in s["by_source"].items():
        unhashed = data["total"] - data["hashed"]
        note = f"{unhashed} skipped — unsupported format" if unhashed > 0 else ""
        src_table.add_row(
            source,
            _fmt_num(data["total"]),
            _fmt_num(data["hashed"]),
            note,
        )

    # ── Compose panel lines ────────────────────────────────────
    lines: list[str] = []

    lines.append(f"[bold]Hash index[/bold]")
    lines.append(f"  Path    [cyan]{db_path}[/cyan]")
    lines.append(
        f"  Size    [bold]{_fmt_bytes(db_bytes)}[/bold]"
        + (
            f"  [dim](your library ~{_fmt_bytes(lib_bytes)} — "
            f"index is {ratio_pct:.4f}% of that)[/dim]"
            if lib_bytes > 0 else ""
        )
    )
    if last_indexed and last_indexed != "—":
        lines.append(f"  Updated [dim]{last_indexed[:19]}[/dim]")

    lines.append("")
    lines.append("[bold]Temp cache (mobile only — adb pull)[/bold]")
    lines.append(f"  {cache_status}")
    lines.append("  [dim]Pulled per-run to compute hashes, wiped after every run.[/dim]")

    lines.append("")
    lines.append("[bold]What is indexed per photo[/bold]")
    lines.append("  [green]✓[/green]  filename · width × height · 8-byte hash · file size · date")
    lines.append("  [red]✗[/red]  pixel data · thumbnails · copies of your photos")
    lines.append("  [dim]Hashes are one-way — original photos cannot be reconstructed from them.[/dim]")

    lines.append("")
    lines.append("[bold]Photos per source[/bold]")

    panel_body = "\n".join(lines)

    console.print()
    console.print(Panel(
        panel_body,
        title="[bold]Storage footprint[/bold]",
        title_align="left",
        border_style="dim",
        padding=(1, 2),
    ))
    console.print(src_table)
    console.print()


# ── Logging setup ──────────────────────────────────────────────

def _setup_logging() -> None:
    from config import get_config
    cfg = get_config()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level=cfg.log_level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )
    logger.add(
        cfg.log_dir / "agent.log",
        rotation="1 day",
        retention="14 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )


# ── ADB cache cleanup ──────────────────────────────────────────

def _cleanup_mobile_cache() -> None:
    from storage.mobile import MobileScanner
    MobileScanner().cleanup_cache()


# ── Interactive folder pickers ─────────────────────────────────

def _pick_pc_dirs() -> list[str]:
    console.print("\n[bold cyan]PC Folders[/bold cyan]")
    console.print("Enter each folder path to scan. [dim]Press Enter with no input when done.[/dim]\n")
    dirs: list[str] = []
    i = 1
    while True:
        raw = Prompt.ask(f"  [cyan]Folder {i}[/cyan]", default="").strip()
        if not raw:
            if not dirs:
                console.print("  [yellow]No folders entered — will use PC_PHOTOS_DIR from .env[/yellow]")
            break
        p = Path(raw)
        if not p.exists() or not p.is_dir():
            console.print(f"  [red]✗  Not found: {raw}[/red]")
            continue
        dirs.append(str(p))
        console.print(f"  [green]✓  Added: {p.name}[/green]")
        i += 1
    return dirs


def _pick_mobile_dirs(skip_mobile: bool) -> list[str]:
    if skip_mobile:
        return []

    from storage.mobile import MobileScanner

    console.print("\n[bold cyan]Mobile Folders[/bold cyan]")
    scanner = MobileScanner()

    if not scanner.is_available():
        console.print(
            "  [yellow]No ADB device found — skipping mobile selection.[/yellow]\n"
            "  Run [bold]python main.py mobile-status[/bold] to diagnose."
        )
        return []

    console.print("  Fetching photo folders from device… [dim](may take a few seconds)[/dim]")
    raw_dirs = scanner.list_scannable_dirs()

    if not raw_dirs:
        console.print("  [yellow]No photo-containing folders found on device.[/yellow]")
        return []

    table = Table(show_header=True, header_style="bold", box=box.SIMPLE, padding=(0, 2))
    table.add_column("#",    style="dim cyan", min_width=4)
    table.add_column("Folder on phone", min_width=44)
    table.add_column("Alias", style="dim")

    for i, d in enumerate(raw_dirs):
        table.add_row(str(i), d, d.split("/")[-1])

    console.print()
    console.print(table)

    selection = Prompt.ask(
        "  Select [dim](comma-separated e.g. 0,1,3  ·  'all'  ·  Enter = use .env default)[/dim]",
        default="",
    ).strip()

    if not selection:
        console.print("  [yellow]No selection — will use ANDROID_REMOTE_DIR from .env[/yellow]")
        return []

    if selection.lower() == "all":
        console.print(f"  [green]✓  All {len(raw_dirs)} folders selected[/green]")
        return raw_dirs

    selected: list[str] = []
    for part in selection.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) >= len(raw_dirs):
            console.print(f"  [yellow]Skipping invalid selection: '{part}'[/yellow]")
            continue
        folder = raw_dirs[int(part)]
        selected.append(folder)
        console.print(f"  [green]✓  {folder}[/green]")

    return selected


# ── Base state builder ─────────────────────────────────────────

def _base_state(
    dry_run: bool,
    skip_mobile: bool,
    skip_google: bool,
    threshold: Optional[int],
    max_deletes: Optional[int],
    pc_dirs: Optional[list[str]] = None,
    mobile_dirs: Optional[list[str]] = None,
) -> dict:
    from config import get_config
    cfg = get_config()
    return {
        "dry_run":           dry_run,
        "skip_mobile":       skip_mobile,
        "skip_google":       skip_google,
        "user_confirmed":    False,
        "hamming_threshold": threshold or cfg.hamming_threshold,
        "max_deletes":       max_deletes,
        "pc_dirs":           pc_dirs or [],
        "mobile_dirs":       mobile_dirs or [],
        "scan_results":      {},
        "duplicate_groups":  [],
        "action_plan":       [],
        "execution_results": [],
        "report":            {},
    }


# ── Commands ───────────────────────────────────────────────────

@app.command()
def scan(
    pc_dir:      Optional[list[str]] = typer.Option(None,  "--pc-dir",      help="PC folder to scan (repeat for multiple)"),
    mobile_dir:  Optional[list[str]] = typer.Option(None,  "--mobile-dir",  help="Phone folder to scan (repeat for multiple)"),
    interactive: bool                = typer.Option(False, "--interactive",  "-i", help="Pick folders interactively"),
    skip_mobile: bool                = typer.Option(False, "--skip-mobile"),
    skip_google: bool                = typer.Option(False, "--skip-google"),
) -> None:
    """
    Scan all storages and index photos. Completely read-only — no files changed.

    Examples:

    \b
    # Use .env defaults
    python main.py scan --skip-google

    \b
    # Explicit folders (repeat --pc-dir for each)
    python main.py scan --pc-dir "C:\\Photos\\Family" --pc-dir "C:\\Photos\\Work" --skip-google

    \b
    # Interactive folder picker
    python main.py scan --interactive --skip-google
    """
    _setup_logging()
    from agent.graph import graph

    resolved_pc     = list(pc_dir)     if pc_dir     else []
    resolved_mobile = list(mobile_dir) if mobile_dir else []

    if interactive:
        resolved_pc     = _pick_pc_dirs()               or resolved_pc
        resolved_mobile = _pick_mobile_dirs(skip_mobile) or resolved_mobile

    console.print("\n[bold]Scanning storage sources…[/bold]")
    if resolved_pc:
        console.print("[dim]PC folders:[/dim]")
        for d in resolved_pc:
            console.print(f"  {d}")
    if resolved_mobile:
        console.print("[dim]Mobile folders:[/dim]")
        for d in resolved_mobile:
            console.print(f"  {d}")
    console.print()

    state = _base_state(True, skip_mobile, skip_google, None, None, resolved_pc, resolved_mobile)
    try:
        result = graph.invoke(state)
    finally:
        if not skip_mobile:
            _cleanup_mobile_cache()

    scan_results = result.get("scan_results", {})
    total = sum(len(v) for v in scan_results.values())
    for source, records in scan_results.items():
        console.print(f"  [green]{source:<16}[/green] {_fmt_num(len(records))} photos")
    console.print(f"\n[bold green]Done.[/bold green] {_fmt_num(total)} photos indexed.\n")

    # Always show the footprint panel after a scan
    _print_footprint(skip_mobile=skip_mobile)


@app.command()
def run(
    execute:     bool                = typer.Option(False, "--execute",     help="Apply changes (default: dry-run)"),
    pc_dir:      Optional[list[str]] = typer.Option(None,  "--pc-dir",     help="PC folder to scan (repeat for multiple)"),
    mobile_dir:  Optional[list[str]] = typer.Option(None,  "--mobile-dir", help="Phone folder to scan (repeat for multiple)"),
    interactive: bool                = typer.Option(False, "--interactive", "-i", help="Pick folders interactively"),
    skip_mobile: bool                = typer.Option(False, "--skip-mobile"),
    skip_google: bool                = typer.Option(False, "--skip-google"),
    threshold:   Optional[int]       = typer.Option(None,  "--threshold",   "-t", help="Hamming threshold (default from .env)"),
    max_deletes: Optional[int]       = typer.Option(None,  "--max-deletes", help="Cap number of delete actions"),
) -> None:
    """
    Full pipeline: scan → detect duplicates → plan → (confirm) → execute.

    Default is DRY RUN — use --execute to apply changes.

    Examples:

    \b
    # Dry-run two PC folders, no phone, no Google Photos
    python main.py run --pc-dir "C:\\Photos\\Family" --pc-dir "C:\\Photos\\Work" --skip-mobile --skip-google

    \b
    # Interactive picker then execute
    python main.py run --interactive --execute --skip-google

    \b
    # Stricter matching with a delete cap
    python main.py run --threshold 5 --max-deletes 20 --execute
    """
    _setup_logging()
    from agent.graph import graph

    resolved_pc     = list(pc_dir)     if pc_dir     else []
    resolved_mobile = list(mobile_dir) if mobile_dir else []

    if interactive:
        resolved_pc     = _pick_pc_dirs()               or resolved_pc
        resolved_mobile = _pick_mobile_dirs(skip_mobile) or resolved_mobile

    if execute:
        console.print("[bold red]EXECUTE MODE[/bold red] — files will be moved to trash\n")
    else:
        console.print("[bold yellow]DRY RUN[/bold yellow] — no files will be changed\n")

    if resolved_pc:
        console.print("[dim]PC folders:[/dim]")
        for d in resolved_pc:
            console.print(f"  {d}")
    if resolved_mobile:
        console.print("[dim]Mobile folders:[/dim]")
        for d in resolved_mobile:
            console.print(f"  {d}")
    if resolved_pc or resolved_mobile:
        console.print()

    state = _base_state(
        not execute, skip_mobile, skip_google, threshold, max_deletes,
        resolved_pc, resolved_mobile,
    )
    try:
        result = graph.invoke(state)
    finally:
        if not skip_mobile:
            _cleanup_mobile_cache()

    report_data = result.get("report", {})
    if path := report_data.get("report_path"):
        console.print(f"\n[bold]Report saved:[/bold] {path}")
        console.print("Run [bold]python main.py report[/bold] to open it.")

    # Show footprint after every run too
    _print_footprint(skip_mobile=skip_mobile)


@app.command()
def info() -> None:
    """
    Show index location, size, record counts, and a full breakdown
    of what is stored vs what is not — to confirm the agent is not
    consuming extra disk space.
    """
    from db.store import PhotoStore

    store = PhotoStore()

    try:
        s = store.stats()
    except Exception as e:
        console.print(f"[red]Could not read index: {e}[/red]")
        raise typer.Exit(1)

    if s["total"] == 0:
        console.print(
            "[yellow]Index is empty.[/yellow] "
            "Run [bold]python main.py scan[/bold] first."
        )
        return

    # ── Index location & size ──────────────────────────────────
    console.print()
    console.print(Panel(
        f"[cyan]{s['db_path']}[/cyan]",
        title="[bold]Hash index location[/bold]",
        title_align="left",
        border_style="cyan",
        padding=(0, 2),
    ))

    # ── Size comparison ────────────────────────────────────────
    db_bytes  = s["db_size_bytes"]
    lib_bytes = s["total_photo_bytes"]
    ratio_pct = (db_bytes / lib_bytes * 100) if lib_bytes > 0 else 0

    size_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    size_table.add_column("Label", style="dim", min_width=24)
    size_table.add_column("Value", min_width=16)
    size_table.add_column("", style="dim")

    size_table.add_row(
        "photo_index.db  (index)",
        f"[bold]{_fmt_bytes(db_bytes)}[/bold]",
        "← what this agent uses on disk",
    )
    if lib_bytes > 0:
        size_table.add_row(
            "Your total library",
            _fmt_bytes(lib_bytes),
            f"index is {ratio_pct:.4f}% of your library",
        )

    console.print(size_table)

    # ── Per-source breakdown ───────────────────────────────────
    console.print("[bold]Photos per source[/bold]")
    src_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 3))
    src_table.add_column("Source",   style="green", min_width=16)
    src_table.add_column("Indexed",  justify="right", min_width=10)
    src_table.add_column("Hashed",   justify="right", min_width=10)
    src_table.add_column("Library size", justify="right", min_width=14)
    src_table.add_column("Notes", style="dim")

    for source, data in s["by_source"].items():
        unhashed = data["total"] - data["hashed"]
        note = f"{unhashed} unhashed (unsupported format)" if unhashed > 0 else "all hashed ✓"
        src_table.add_row(
            source,
            _fmt_num(data["total"]),
            _fmt_num(data["hashed"]),
            _fmt_bytes(data["size_bytes"]),
            note,
        )
    console.print(src_table)

    # ── What is / isn't stored ────────────────────────────────
    console.print("[bold]What the index stores per photo[/bold]")
    what_table = Table(box=None, show_header=False, padding=(0, 3))
    what_table.add_column("", min_width=4)
    what_table.add_column("Field")
    what_table.add_column("Detail", style="dim")

    stored = [
        ("filename",              "original filename only, not the file itself"),
        ("width × height",        "resolution in pixels — from EXIF or API metadata"),
        ("8-byte perceptual hash","one-way fingerprint — cannot reconstruct the photo"),
        ("file size",             "in bytes — used for the 'space freed' estimate"),
        ("creation timestamp",    "from EXIF DateTimeOriginal or file mtime"),
    ]
    not_stored = [
        ("pixel data",    "no image content is ever read into the database"),
        ("thumbnails",    "mobile uses a temp pull that is wiped after each run"),
        ("file copies",   "original photos are never duplicated anywhere"),
        ("Google tokens", "OAuth token lives at ~/.photo_agent_token.json, not here"),
    ]

    for field, detail in stored:
        what_table.add_row("[green]✓[/green]", field, detail)
    for field, detail in not_stored:
        what_table.add_row("[red]✗[/red]", field, detail)

    console.print(what_table)

    # ── Temp cache ─────────────────────────────────────────────
    tmp_cache = Path(tempfile.gettempdir()) / "photo_agent_adb_cache"
    cache_size = sum(f.stat().st_size for f in tmp_cache.rglob("*") if f.is_file()) if tmp_cache.exists() else 0
    console.print(f"[bold]Mobile temp cache[/bold]  [dim]{tmp_cache}[/dim]")
    if cache_size > 0:
        console.print(
            f"  [yellow]⚠  {_fmt_bytes(cache_size)} still on disk[/yellow] "
            "— run a scan to trigger cleanup, or delete manually."
        )
    else:
        console.print("  [green]cleared ✓[/green]  0 bytes on disk right now")

    if s.get("last_indexed"):
        console.print(f"\n[dim]Index last updated: {s['last_indexed'][:19]}[/dim]")

    console.print()


@app.command()
def report() -> None:
    """Open the most recent HTML report in your browser."""
    report_dir = Path("reports")
    files = sorted(report_dir.glob("report_*.html"), reverse=True)
    if not files:
        console.print("[red]No reports found. Run [bold]python main.py run[/bold] first.[/red]")
        raise typer.Exit(1)
    latest = files[0]
    console.print(f"Opening [bold]{latest}[/bold]")
    opener = "open" if sys.platform == "darwin" else ("start" if sys.platform == "win32" else "xdg-open")
    subprocess.run([opener, str(latest)])


@app.command("mobile-status")
def mobile_status() -> None:
    """Diagnose the ADB connection to an Android phone."""
    from storage.mobile import MobileScanner, adb_available, run_adb

    if not adb_available():
        console.print("[red bold]adb is not installed or not on PATH.[/red bold]")
        console.print(
            "  macOS:    brew install android-platform-tools\n"
            "  Windows:  https://developer.android.com/tools/releases/platform-tools\n"
            "  Linux:    sudo apt install android-tools-adb"
        )
        raise typer.Exit(1)

    console.print("[green]✓[/green] adb binary found\n")
    result = run_adb(["devices", "-l"])
    console.print("[bold]adb devices -l:[/bold]")
    console.print(result.stdout.strip() or "(no output)")
    console.print()

    scanner = MobileScanner()
    if scanner.is_available():
        console.print("[green bold]✓ Mobile device ready for scanning.[/green bold]")
    else:
        console.print(
            "[yellow bold]✗ No usable device.[/yellow bold]\n"
            "  • 'unauthorized' → check phone screen for 'Allow USB debugging?'\n"
            "  • No devices → enable Developer Options → USB Debugging\n"
            "  • Multiple devices → set ANDROID_DEVICE_SERIAL in .env"
        )


@app.command("purge-trash")
def purge_trash() -> None:
    """Permanently delete all files in the PC trash folder."""
    from config import get_config
    trash = get_config().trash_dir
    if not trash.exists() or not any(trash.iterdir()):
        console.print("[green]Trash folder is empty.[/green]")
        return
    files = list(trash.rglob("*"))
    console.print(f"[red bold]{len(files)} file(s) in {trash} will be permanently deleted.[/red bold]")
    confirm = typer.prompt("Type  yes I reviewed the trash  to confirm", default="")
    if confirm.strip() == "yes I reviewed the trash":
        import shutil
        shutil.rmtree(trash)
        trash.mkdir(parents=True)
        console.print("[green]Trash purged.[/green]")
    else:
        console.print("[yellow]Aborted.[/yellow]")


@app.command("purge-mobile-trash")
def purge_mobile_trash() -> None:
    """Permanently delete the on-device mobile trash folder."""
    from config import get_config
    from storage.mobile import MobileScanner, run_adb
    cfg = get_config()
    scanner = MobileScanner()
    if not scanner.is_available():
        console.print("[red]No ADB device connected.[/red]")
        raise typer.Exit(1)
    result = run_adb(scanner._device_args() + ["shell", "find", cfg.android_trash_dir, "-type", "f"])
    files = [f for f in result.stdout.splitlines() if f.strip()]
    if not files:
        console.print("[green]Mobile trash is empty.[/green]")
        return
    console.print(f"[red bold]{len(files)} file(s) on device will be permanently deleted.[/red bold]")
    confirm = typer.prompt("Type  yes I reviewed the trash  to confirm", default="")
    if confirm.strip() == "yes I reviewed the trash":
        run_adb(scanner._device_args() + ["shell", "rm", "-rf", cfg.android_trash_dir])
        console.print("[green]Mobile trash purged.[/green]")
    else:
        console.print("[yellow]Aborted.[/yellow]")


@app.command("clear-cache")
def clear_cache() -> None:
    """Clear the SQLite photo index. Next run re-scans everything from scratch."""
    from db.store import PhotoStore
    PhotoStore().clear()
    console.print("[green]Photo index cleared.[/green]")


if __name__ == "__main__":
    app()
