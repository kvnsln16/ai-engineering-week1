"""
jobs.py  (extended for clustering & scoring)
--------------------------------------------
The daily flow is now:

  Phase 1 — Collect raw signals from every connector
  Phase 2 — Dedupe and persist
  Phase 3 — Enrich (topics, sentiment, quality, industry)
  Phase 4 — Cluster + score (NEW)
  Phase 5 — Notify OpenClaw with combined summary

Phases 3 and 4 are isolated in their own try/except. If clustering fails
(missing model, OOM, etc.) the raw collection + enrichment data is still
persisted. You can rerun clustering separately via the API endpoint.
"""

from __future__ import annotations

import logging
import time

from app import db
from app.clustering import cluster_signals, score_all_clusters
from app.connectors.base import BaseConnector
from app.connectors.tier2 import TIER2_CONNECTORS
from app.dedup import Deduper
from app.enrichment import enrich_new_signals
from app.health.tracker import shared_tracker
from app.integrations.openclaw import openclaw_client

logger = logging.getLogger(__name__)


# from app.connectors.hackernews import HackerNewsConnector
# from app.connectors.reddit     import RedditConnector
# from app.connectors.github     import GitHubConnector
# from app.connectors.producthunt import ProductHuntConnector
# from app.connectors.ai_news    import AiNewsConnector

TIER1_CONNECTORS: list[BaseConnector] = [
    # HackerNewsConnector(),
    # RedditConnector(),
    # GitHubConnector(),
    # ProductHuntConnector(),
    # AiNewsConnector(),
]


def all_connectors() -> list[BaseConnector]:
    return [*TIER1_CONNECTORS, *TIER2_CONNECTORS]


def run_all_collectors() -> dict:
    """
    Full pipeline: collect -> dedup -> persist -> enrich -> cluster -> notify.

    Never raises. Returns a summary dict.
    """
    deduper = Deduper()
    started = time.monotonic()

    per_collector_results: list[dict] = []
    total_fetched = 0
    total_new = 0
    total_failures = 0

    # Phase 1+2: collect, dedup, persist
    for connector in all_connectors():
        result = _run_one(connector, deduper)
        per_collector_results.append(result)
        total_fetched += result["fetched"]
        total_new += result["new"]
        if result["error"]:
            total_failures += 1

    collect_elapsed = time.monotonic() - started

    # Phase 3: enrichment
    enrichment_summary = _run_enrichment()

    # Phase 4: clustering + scoring
    clustering_summary = _run_clustering()

    elapsed = time.monotonic() - started

    summary = {
        "duration_seconds": round(elapsed, 2),
        "collection_seconds": round(collect_elapsed, 2),
        "collector_count": len(per_collector_results),
        "total_fetched": total_fetched,
        "total_new": total_new,
        "total_failures": total_failures,
        "per_collector": per_collector_results,
        "enrichment": enrichment_summary,
        "clustering": clustering_summary,
    }

    logger.info(
        "scheduler: run complete — %d new / %d fetched, %d enriched, %d clusters, %.2fs total",
        total_new, total_fetched,
        enrichment_summary["processed"],
        clustering_summary.get("clusters", 0),
        elapsed,
    )

    _notify_openclaw(summary)
    return summary


def _run_one(connector: BaseConnector, deduper: Deduper) -> dict:
    name = connector.name
    try:
        records = connector.collect()
        new_records, _duplicates = deduper.filter_new(records)
        inserted, _dupes_from_db = db.insert_records(new_records)

        shared_tracker.record_success(
            name=name,
            record_count=len(records),
            new_count=inserted,
        )
        return {
            "name": name,
            "fetched": len(records),
            "new": inserted,
            "error": None,
        }

    except Exception as exc:
        logger.exception("scheduler: %s failed: %s", name, exc)
        shared_tracker.record_failure(name=name, error=str(exc))
        return {
            "name": name,
            "fetched": 0,
            "new": 0,
            "error": str(exc),
        }


def _run_enrichment() -> dict:
    """Run the enrichment pipeline. Isolated try/except for safety."""
    try:
        return enrich_new_signals()
    except Exception as exc:
        logger.exception("scheduler: enrichment phase failed: %s", exc)
        return {
            "processed": 0,
            "errors": 0,
            "batches": 0,
            "duration_seconds": 0,
            "signals_per_second": 0,
            "fatal_error": str(exc),
        }


def _run_clustering() -> dict:
    """
    Run clustering + scoring. Returns a small summary dict.

    Isolated try/except — if hdbscan is missing or model OOMs, the
    enrichment data still persists and we report the failure.
    """
    started = time.monotonic()
    try:
        rows = db.load_enriched_for_clustering()
        if not rows:
            return {
                "signals_clustered": 0,
                "clusters": 0,
                "scored": 0,
                "duration_seconds": 0,
            }

        clusters, assignments = cluster_signals(rows)

        if clusters:
            db.save_clusters(clusters, assignments)
            scored = score_all_clusters()
            n_scored = len(scored)
        else:
            n_scored = 0

        elapsed = time.monotonic() - started
        return {
            "signals_clustered": len(assignments),
            "clusters": len(clusters),
            "scored": n_scored,
            "duration_seconds": round(elapsed, 2),
        }

    except Exception as exc:
        logger.exception("scheduler: clustering phase failed: %s", exc)
        return {
            "signals_clustered": 0,
            "clusters": 0,
            "scored": 0,
            "duration_seconds": round(time.monotonic() - started, 2),
            "fatal_error": str(exc),
        }


def _notify_openclaw(summary: dict) -> None:
    """Format and send the run summary to OpenClaw."""
    enrich = summary["enrichment"]
    clust = summary["clustering"]

    lines = [
        f"Pipeline run complete in {summary['duration_seconds']}s",
        f"{summary['total_new']} new / {summary['total_fetched']} fetched "
        f"from {summary['collector_count']} collectors",
        f"Enriched {enrich['processed']} signals "
        f"({enrich['signals_per_second']} signals/sec)",
        f"Clustered into {clust.get('clusters', 0)} topics "
        f"({clust.get('scored', 0)} scored)",
        "",
    ]
    for c in summary["per_collector"]:
        if c["error"]:
            lines.append(f"  ✗ {c['name']}: {c['error']}")
        else:
            lines.append(f"  ✓ {c['name']}: {c['new']} new / {c['fetched']} fetched")

    body = "\n".join(lines)
    level = "warning" if summary["total_failures"] > 0 else "info"

    openclaw_client.notify(
        title="Daily signal collection complete",
        body=body,
        level=level,
    )
