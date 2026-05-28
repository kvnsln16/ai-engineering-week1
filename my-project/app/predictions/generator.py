from __future__ import annotations

import logging
import math
import statistics
import time
from typing import Any

from app import db
from app.predictions.templates import (
    magnitude_bucket,
    render_text,
    render_action,
)
from app.predictions.signal_picker import pick_signals

logger = logging.getLogger(__name__)


STABLE_THRESHOLD = 0.10


def generate_all_predictions() -> dict[str, Any]:
    started = time.monotonic()

    db.delete_all_predictions()

    forecasts = db.all_forecasts(limit=10_000)
    if not forecasts:
        return {
            "written": 0,
            "clusters_attempted": 0,
            "skipped": 0,
            "duration_seconds": 0,
        }

    by_cluster: dict[int, list[dict[str, Any]]] = {}
    for f in forecasts:
        by_cluster.setdefault(f["cluster_id"], []).append(f)

    written = 0
    skipped = 0
    attempted = len(by_cluster)

    for cluster_id, cluster_forecasts in by_cluster.items():
        try:
            count = _generate_for_cluster(cluster_id, cluster_forecasts)
            written += count
        except Exception as exc:
            logger.exception(
                "generator: cluster %d failed: %s", cluster_id, exc,
            )
            skipped += 1

    elapsed = time.monotonic() - started
    logger.info(
        "generator: wrote %d predictions across %d clusters (%d skipped, %.2fs)",
        written, attempted, skipped, elapsed,
    )
    return {
        "written": written,
        "clusters_attempted": attempted,
        "skipped": skipped,
        "duration_seconds": round(elapsed, 2),
    }


def _generate_for_cluster(
    cluster_id: int,
    forecasts: list[dict[str, Any]],
) -> int:
    cluster = db.cluster_with_signals(cluster_id)
    if cluster is None:
        return 0

    keywords = cluster.get("keywords") or []
    label = cluster.get("label") or ""
    industry = cluster.get("industry")

    history = db.cluster_history_series(cluster_id, days=7)
    current_size = float(history[-1][1]) if history else float(cluster["size"])

    cluster_signals = db.cluster_signals_full(cluster_id)

    count = 0
    for forecast in forecasts:
        prediction = _build_prediction(
            cluster_id=cluster_id,
            cluster_keywords=keywords,
            cluster_label=label,
            industry=industry,
            current_size=current_size,
            cluster_signals=cluster_signals,
            forecast=forecast,
        )
        if prediction is None:
            continue

        db.save_prediction(**prediction)
        count += 1

    return count


def _build_prediction(
    *,
    cluster_id: int,
    cluster_keywords: list[str],
    cluster_label: str,
    industry: str | None,
    current_size: float,
    cluster_signals: list[dict[str, Any]],
    forecast: dict[str, Any],
) -> dict[str, Any] | None:
    horizon = int(forecast["horizon_days"])
    predicted = float(forecast["predicted_size"])
    confidence = float(forecast.get("confidence_score") or 0.0)

    relative_change = (predicted - current_size) / max(current_size, 1.0)
    direction = _direction_from_change(relative_change)
    magnitude = magnitude_bucket(relative_change) if direction != "stable" else "stable"

    probability = _probability_from_change(relative_change, direction)

    seed_key = f"{cluster_id}:{horizon}:{direction}"
    text = render_text(
        direction=direction,
        magnitude=magnitude,
        cluster_keywords=cluster_keywords,
        cluster_label=cluster_label,
        horizon_days=horizon,
        seed_key=seed_key,
    )

    action = render_action(industry, direction)

    supporting_ids, counter_ids = pick_signals(cluster_signals, direction)

    return {
        "cluster_id":            cluster_id,
        "horizon_days":          horizon,
        "text":                  text,
        "probability":           round(probability, 4),
        "confidence":            round(confidence, 4),
        "direction":             direction,
        "recommended_action":    action,
        "supporting_signal_ids": supporting_ids,
        "counter_signal_ids":    counter_ids,
        "forecast_predicted":    predicted,
        "forecast_lower":        forecast.get("confidence_lower"),
        "forecast_upper":        forecast.get("confidence_upper"),
    }


def _direction_from_change(relative_change: float) -> str:
    if relative_change > STABLE_THRESHOLD:
        return "growth"
    if relative_change < -STABLE_THRESHOLD:
        return "decline"
    return "stable"


def _probability_from_change(relative_change: float, direction: str) -> float:
    if direction == "stable":
        return 0.5

    abs_change = abs(relative_change)
    sigmoid_val = 1.0 / (1.0 + math.exp(-abs_change * 2))
    return min(1.0, max(0.5, sigmoid_val))
