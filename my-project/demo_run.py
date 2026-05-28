"""
demo_run.py
-----------
One-shot demo script. Does this sequence WITHOUT re-clustering:

  1. Verify clusters exist (otherwise tell the user to run run_once.py first)
  2. Seed 35 days of synthetic history for each existing cluster
  3. Run forecasting on the seeded history
  4. Run prediction generation from the forecasts
  5. Print a summary

This is the demo-friendly alternative to run_once.py. The normal pipeline
re-clusters every run (wiping cluster IDs), which orphans seeded history.
This script skips re-clustering so the IDs you seed for are the IDs that
get forecasted.

Usage:
    python demo_run.py
"""

from __future__ import annotations

import logging
import math
import random
import sys
from datetime import datetime, timedelta, timezone

from app import db
from app.forecasting import forecast_cluster, ForecastUnavailable
from app.predictions import generate_all_predictions


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(message)s",
)


HISTORY_DAYS = 35
PATTERNS = ["growth", "decline", "stable", "volatile"]


def main() -> int:
    db.init_db()

    clusters = db.top_clusters(limit=10_000, sort_by="size")
    if not clusters:
        print("No clusters found.")
        print("Run `python run_once.py` first to collect signals and build clusters,")
        print("then run this script.")
        return 1

    print(f"Demo run for {len(clusters)} clusters")
    print(f"(synthetic history will be generated for demo purposes)\n")

    # Step 1: seed history
    _seed_history(clusters)

    # Step 2: run forecasting (top-20 by composite)
    print("\n--- Forecasting ---")
    forecast_summary = _run_forecasting(clusters)
    print(
        f"  forecasts_written={forecast_summary['written']}, "
        f"clusters_attempted={forecast_summary['attempted']}, "
        f"insufficient={forecast_summary['insufficient']}"
    )

    # Step 3: generate predictions
    print("\n--- Predictions ---")
    pred_summary = generate_all_predictions()
    print(
        f"  predictions_written={pred_summary['written']}, "
        f"clusters_attempted={pred_summary['clusters_attempted']}"
    )

    # Step 4: show a sample
    print("\n--- Sample predictions ---")
    samples = db.predictions_filtered(limit=4)
    for p in samples:
        print(f"\n  [{p['horizon_days']:3d}d] {p['cluster_label']}")
        print(f"        {p['text']}")
        print(f"        probability={p['probability']}, confidence={p['confidence']}, direction={p['direction']}")
        action = p.get('recommended_action') or 'None'
        print(f"        action: {action[:90]}")

    print("\n" + "=" * 60)
    print("DONE. View results:")
    print("  http://127.0.0.1:8000/predictions/top")
    print("  http://127.0.0.1:8000/predictions?horizon=30")
    print("  http://127.0.0.1:8000/predictions?min_confidence=0.7")
    print("=" * 60)

    return 0


# ============================================================================
# Steps
# ============================================================================

def _seed_history(clusters: list[dict]) -> None:
    """Write 35 days of synthetic history for each cluster."""
    print("Seeding history:")
    today = datetime.now(timezone.utc).date()
    rng = random.Random(42)

    for i, cluster in enumerate(clusters):
        cluster_id = cluster["cluster_id"]
        current_size = cluster["size"]
        label = cluster["label"]
        pattern = PATTERNS[i % len(PATTERNS)]

        series = _build_series(
            current_size=current_size,
            days=HISTORY_DAYS,
            pattern=pattern,
            rng=rng,
        )

        for day_offset, size in enumerate(series):
            snapshot_day = today - timedelta(days=HISTORY_DAYS - 1 - day_offset)
            db.record_cluster_history(
                cluster_id,
                size,
                snapshot_day=snapshot_day.strftime("%Y-%m-%d"),
            )

        print(
            f"  Cluster {cluster_id:3d} ({label[:35]:35})  "
            f"pattern={pattern:8}  start={series[0]:3d} -> end={series[-1]:3d}"
        )


def _run_forecasting(clusters: list[dict]) -> dict:
    """Forecast all clusters using the freshly-seeded history."""
    db.delete_all_forecasts()

    written = 0
    attempted = 0
    insufficient = 0

    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        attempted += 1

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

    return {
        "written": written,
        "attempted": attempted,
        "insufficient": insufficient,
    }


# ============================================================================
# Synthetic data generators
# ============================================================================

def _build_series(*, current_size, days, pattern, rng):
    if pattern == "growth":
        start = max(2, int(current_size * 0.4))
        slope = (current_size - start) / max(days - 1, 1)
        base = [int(start + slope * t) for t in range(days)]
    elif pattern == "decline":
        start = max(current_size + 5, int(current_size * 1.7))
        slope = (current_size - start) / max(days - 1, 1)
        base = [int(start + slope * t) for t in range(days)]
    elif pattern == "stable":
        base = [current_size] * days
    elif pattern == "volatile":
        amplitude = max(2, int(current_size * 0.3))
        base = [
            int(current_size + amplitude * math.sin(2 * math.pi * t / 14))
            for t in range(days)
        ]
    else:
        base = [current_size] * days

    noise = [rng.randint(-1, 1) for _ in range(days)]
    return [max(1, b + n) for b, n in zip(base, noise)]


if __name__ == "__main__":
    sys.exit(main())
