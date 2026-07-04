from datetime import datetime
from pathlib import Path

from jinja2 import Template
from loguru import logger

from agent.state import AgentState
from utils.models import ActionResult

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Photo Agent — Run Report</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;background:#fafafa;padding:40px 24px}
  .wrap{max-width:960px;margin:0 auto}
  h1{font-size:22px;font-weight:500;margin-bottom:4px}
  .meta{color:#888;font-size:13px;margin-bottom:32px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:32px}
  .stat{background:#fff;border:1px solid #e5e5e5;border-radius:10px;padding:16px}
  .stat .n{font-size:32px;font-weight:500;color:#111}
  .stat .l{font-size:11px;color:#999;text-transform:uppercase;letter-spacing:.06em;margin-top:6px}
  table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e5e5;border-radius:10px;overflow:hidden;font-size:13px}
  th{text-align:left;padding:10px 14px;background:#f5f5f5;font-weight:500;color:#555;font-size:11px;text-transform:uppercase;letter-spacing:.05em}
  td{padding:9px 14px;border-top:1px solid #f0f0f0;color:#333}
  .DELETE{color:#dc2626;font-weight:500}
  .MOVE_TO_HRP{color:#16a34a;font-weight:500}
  .SKIP{color:#9ca3af}
  .SUCCESS{color:#16a34a}
  .FAILED{color:#dc2626;font-weight:500}
  .DRY_RUN{color:#f59e0b}
  .SKIPPED{color:#9ca3af}
</style>
</head>
<body>
<div class="wrap">
  <h1>Photo management agent — run report</h1>
  <p class="meta">{{ timestamp }}</p>
  <div class="stats">
    <div class="stat"><div class="n">{{ s.deleted }}</div><div class="l">Deleted (→ trash)</div></div>
    <div class="stat"><div class="n">{{ s.hrp }}</div><div class="l">Moved to HRP</div></div>
    <div class="stat"><div class="n">{{ s.failed }}</div><div class="l">Failed</div></div>
    <div class="stat"><div class="n">{{ s.space }}</div><div class="l">Space freed</div></div>
  </div>
  <table>
    <thead>
      <tr><th>Action</th><th>File</th><th>Source</th><th>Outcome</th><th>Reason</th></tr>
    </thead>
    <tbody>
    {% for r in rows %}
      <tr>
        <td class="{{ r.action }}">{{ r.action }}</td>
        <td>{{ r.file }}</td>
        <td>{{ r.source }}</td>
        <td class="{{ r.outcome }}">{{ r.outcome }}</td>
        <td style="color:#777">{{ r.reason }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
</body>
</html>"""


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def generate_report_node(state: AgentState) -> AgentState:
    """Node 7 — generate HTML report and write to reports/."""
    logger.info("━━━ NODE: report ━━━")
    results: list[ActionResult] = state.get("execution_results", [])

    deleted  = [r for r in results if r.action.type == "DELETE"       and r.outcome == "SUCCESS"]
    hrp      = [r for r in results if r.action.type == "MOVE_TO_HRP"  and r.outcome == "SUCCESS"]
    failed   = [r for r in results if r.outcome == "FAILED"]
    freed    = sum(r.action.photo.size_bytes for r in deleted)

    stats = {"deleted": len(deleted), "hrp": len(hrp), "failed": len(failed), "space": _fmt_bytes(freed)}

    rows = [
        {
            "action":  r.action.type,
            "file":    r.action.photo.filename,
            "source":  r.action.photo.source,
            "outcome": r.outcome,
            "reason":  r.action.reason,
        }
        for r in results
    ]

    html = Template(_HTML).render(
        timestamp=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"),
        s=stats,
        rows=rows,
    )

    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    fname = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_path = report_dir / fname
    report_path.write_text(html, encoding="utf-8")

    logger.info(f"Report saved → {report_path}")
    logger.info(
        f"Run summary: {stats['deleted']} deleted · "
        f"{stats['hrp']} → HRP · {stats['failed']} failed · {stats['space']} freed"
    )

    return {**state, "report": {"stats": stats, "report_path": str(report_path)}}
