from __future__ import annotations

import logging
import time

from app import db
from app.clustering import cluster_signals, score_all_clusters
from app.connectors.base import BaseConnector
from app.connectors.tier2 import TIER2_CONNECTORS
from app.dedup import Deduper
from app.enrichment import enrich_new_signals
from app.forecasting import forecast_cluster, ForecastUnavailable
from app.health.tracker import shared_tracker
from app.integrations.openclaw import openclaw_client

logger = logging.getLogger(__name__)


TOP_N_TO_FORECAST = 20


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
    deduper = Deduper()
    started = time.monotonic()

    per_collector_results: list[dict] = []
    total_fetched = 0
    total_new = 0
    total_failures = 0

    for connector in all_connectors():
        result = _run_one(connector, deduper)
        per_collector_results.append(result)
        total_fetched += result["fetched"]
        total_new += result["new"]
        if result["error"]:
            total_failures += 1

    collect_elapsed = time.monotonic() - started

    enrichment_summary = _run_enrichment()

    clustering_summary = _run_clustering()

    forecasting_summary = _run_forecasting()

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
        "forecasting": forecasting_summary,
    }

    logger.info(
        "scheduler: run complete — %d new / %d fetched, %d enriched, "
        "%d clusters, %d forecasts, %.2fs total",
        total_new, total_fetched,
        enrichment_summary["processed"],
        clustering_summary.get("clusters", 0),
        forecasting_summary.get("forecasts_written", 0),
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


def _run_forecasting() -> dict:
    started = time.monotonic()

    try:
        top_clusters = db.top_clusters(limit=TOP_N_TO_FORECAST, sort_by="composite")
        if not top_clusters:
            return {
                "forecasts_written": 0,
                "clusters_attempted": 0,
                "insufficient_history": 0,
                "duration_seconds": 0,
            }

        db.delete_all_forecasts()

        written = 0
        insufficient = 0
        attempted = len(top_clusters)

        for cluster in top_clusters:
            cluster_id = cluster["cluster_id"]
            history = db.cluster_history_series(cluster_id, days=365)
            sizes = [float(size) for _day, size in history]
            sources = db.distinct_sources_in_cluster(cluster_id)

            result = forecast_cluster(sizes, distinct_sources=sources)

            if isinstance(result, ForecastUnavailable):
                insufficient += 1
                continue

            for f in result:
                db.save_forecast(
                    cluster_id=cluster_id,
                    horizon_days=f.horizon_days,
                    predicted_size=f.predicted_size,
                    confidence_lower=f.confidence_lower,
                    confidence_upper=f.confidence_upper,
                    confidence_score=f.confidence_score,
                    model=f.model,
                    history_days=f.history_days,
                )
                written += 1

        elapsed = time.monotonic() - started
        return {
            "forecasts_written": written,
            "clusters_attempted": attempted,
            "insufficient_history": insufficient,
            "duration_seconds": round(elapsed, 2),
        }

    except Exception as exc:
        logger.exception("scheduler: forecasting phase failed: %s", exc)
        return {
            "forecasts_written": 0,
            "clusters_attempted": 0,
            "insufficient_history": 0,
            "duration_seconds": round(time.monotonic() - started, 2),
            "fatal_error": str(exc),
        }


def _notify_openclaw(summary: dict) -> None:
    enrich = summary["enrichment"]
    clust = summary["clustering"]
    forecast = summary["forecasting"]

    lines = [
        f"Pipeline run complete in {summary['duration_seconds']}s",
        f"{summary['total_new']} new / {summary['total_fetched']} fetched "
        f"from {summary['collector_count']} collectors",
        f"Enriched {enrich['processed']} signals "
        f"({enrich['signals_per_second']} signals/sec)",
        f"Clustered into {clust.get('clusters', 0)} topics "
        f"({clust.get('scored', 0)} scored)",
        f"Forecasts: {forecast.get('forecasts_written', 0)} written, "
        f"{forecast.get('insufficient_history', 0)} skipped (insufficient history)",
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
