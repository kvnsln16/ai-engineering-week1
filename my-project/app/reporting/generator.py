from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import db
from app.reporting import analyses

logger = logging.getLogger(__name__)


TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_REPORTS_DIR = Path("reports")


def generate_report(*, reports_dir: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    target_dir = reports_dir or DEFAULT_REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    context = _build_context()

    markdown_text = _render_markdown(context)
    html_text = _markdown_to_html(markdown_text, title=f"Report {context['timestamp']}")

    md_path = target_dir / f"report-{context['filename_timestamp']}.md"
    html_path = target_dir / f"report-{context['filename_timestamp']}.html"

    md_path.write_text(markdown_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    latest_md = target_dir / "latest.md"
    latest_html = target_dir / "latest.html"
    shutil.copyfile(md_path, latest_md)
    shutil.copyfile(html_path, latest_html)

    elapsed = time.monotonic() - started
    logger.info(
        "reporting: wrote %s and %s (%.2fs)",
        md_path.name, html_path.name, elapsed,
    )

    return {
        "timestamp":        context["timestamp"],
        "md_path":          str(md_path),
        "html_path":        str(html_path),
        "latest_md":        str(latest_md),
        "latest_html":      str(latest_html),
        "duration_seconds": round(elapsed, 2),
        "size_kb":          round(md_path.stat().st_size / 1024, 1),
    }


def _build_context() -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    top_by_composite = db.top_clusters(limit=10, sort_by="composite")
    top_by_opportunity = db.top_clusters(limit=10, sort_by="opportunity")
    top_by_trend = db.top_clusters(limit=10, sort_by="trend")

    top_forecasts_30 = db.all_forecasts(horizon_days=30, limit=10)

    weak = analyses.weak_signals()
    contrarian = analyses.contrarian_signals()
    threat_list = analyses.threats()

    heatmap = analyses.industry_heatmap()
    market = analyses.market_analysis()

    top_recommendations = db.predictions_filtered(limit=10)

    return {
        "timestamp":             now.isoformat(),
        "filename_timestamp":    now.strftime("%Y-%m-%dT%H-%M-%SZ"),
        "generated_at_readable": now.strftime("%Y-%m-%d %H:%M UTC"),

        "total_signals":     db.count_signals(),
        "total_clusters":    db.count_clusters(),
        "total_predictions": db.count_predictions(),

        "top_clusters":        top_by_composite,
        "top_forecasts_30":    top_forecasts_30,
        "top_opportunities":   top_by_opportunity,
        "top_trend_velocity":  top_by_trend,
        "heatmap":             heatmap,
        "market":              market,
        "weak_signals":        weak,
        "contrarian_signals":  contrarian,
        "threats":             threat_list,
        "top_recommendations": top_recommendations,

        "definitions": analyses.DEFINITIONS,
    }


def _render_markdown(context: dict[str, Any]) -> str:
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.md.j2")
    return template.render(**context)


def _markdown_to_html(markdown_text: str, *, title: str) -> str:
    import markdown as md_lib

    body = md_lib.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
    )

    css_path = TEMPLATES_DIR / "styles.css"
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def list_reports(*, reports_dir: Path | None = None) -> list[dict[str, Any]]:
    target_dir = reports_dir or DEFAULT_REPORTS_DIR
    if not target_dir.exists():
        return []

    reports = []
    for md_path in target_dir.glob("report-*.md"):
        timestamp = md_path.stem.replace("report-", "")
        html_path = target_dir / (md_path.stem + ".html")
        reports.append({
            "timestamp":   timestamp,
            "md_path":     str(md_path),
            "html_path":   str(html_path) if html_path.exists() else None,
            "size_kb":     round(md_path.stat().st_size / 1024, 1),
            "modified_at": datetime.fromtimestamp(
                md_path.stat().st_mtime, tz=timezone.utc,
            ).isoformat(),
        })

    reports.sort(key=lambda r: r["modified_at"], reverse=True)
    return reports
