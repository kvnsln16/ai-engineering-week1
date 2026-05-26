"""
scorer.py
---------
Compute four scores per cluster:

  * trend_score        — growth velocity (today vs recent average)
  * opportunity_score  — demand × monetization potential
  * market_score       — cross-source consensus
  * composite_score    — weighted combination, the headline rank

All scores normalize to [0.0, 1.0] where 1.0 is "best." This lets us
sort and compare across clusters and across runs.

Full formulas are documented in docs/scoring.md. Brief versions appear
above each function below.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from app import db

logger = logging.getLogger(__name__)


# ============================================================================
# Weights for the composite score. Edit these to change emphasis.
# All weights should sum to ~1.0 but the code handles any sum.
# ============================================================================

COMPOSITE_WEIGHTS = {
    "trend":       0.40,   # what's hot right now
    "opportunity": 0.35,   # commercial value
    "market":      0.25,   # is this consensus?
}


# ============================================================================
# Industry-level monetization potential.
# Reflects how directly each industry tends to translate into revenue.
# Edit these as you learn more about your specific use case.
# ============================================================================

MONETIZATION_WEIGHTS: dict[str, float] = {
    "funding":          1.00,   # explicit money flows
    "product_launch":   0.90,   # new products = new revenue
    "llm":              0.75,   # LLM products are heavily monetized
    "computer_vision":  0.70,
    "audio_speech":     0.65,
    "robotics":         0.60,
    "policy_safety":    0.30,   # rarely directly monetizable
    "research":         0.25,   # research takes years to monetize
    "other":            0.40,
}


# ============================================================================
# Public entry point
# ============================================================================

def score_all_clusters() -> list[dict[str, Any]]:
    """
    Compute and persist scores for every cluster in the DB.

    Returns the list of score dicts (also written to cluster_scores).
    Safe to call multiple times — uses INSERT OR REPLACE.
    """
    clusters = db.top_clusters(limit=10_000, sort_by="size")

    if not clusters:
        logger.info("scorer: no clusters to score")
        return []

    total_signals = sum(c["size"] for c in clusters)
    scores: list[dict[str, Any]] = []

    for cluster in clusters:
        cluster_id = cluster["cluster_id"]

        # Update history BEFORE computing trend — the new size is part
        # of today's snapshot, and trend looks at history.
        db.record_cluster_history(cluster_id, cluster["size"])

        trend = _trend_score(cluster_id, cluster["size"])
        opportunity = _opportunity_score(cluster, total_signals)
        market = _market_score(cluster_id)
        composite = _composite(trend, opportunity, market)

        scores.append({
            "cluster_id":        cluster_id,
            "trend_score":       round(trend, 4),
            "opportunity_score": round(opportunity, 4),
            "market_score":      round(market, 4),
            "composite_score":   round(composite, 4),
        })

    db.save_cluster_scores(scores)

    logger.info(
        "scorer: computed scores for %d clusters (avg composite=%.3f)",
        len(scores),
        statistics.mean(s["composite_score"] for s in scores) if scores else 0.0,
    )
    return scores


# ============================================================================
# 1. Trend score — growth velocity
# ============================================================================
#
# Formula:
#     velocity = today_size / max(avg_of_previous_days, 1.0)
#     trend_score = sigmoid(velocity - 1.0)
#
# Notes:
#   * velocity = 1.0  -> trend_score ~ 0.50  (steady)
#   * velocity = 2.0  -> trend_score ~ 0.73  (doubling)
#   * velocity = 0.5  -> trend_score ~ 0.38  (halving)
#   * On day 1 (no history), velocity defaults to 1.0
#
# Why sigmoid: it squashes extreme spikes (a 10x growth gets ~0.99,
# preventing a single outlier cluster from dominating composite scores).
# ============================================================================

def _trend_score(cluster_id: int, today_size: int) -> float:
    history = db.recent_cluster_sizes(cluster_id, days=7)

    # Last entry is today (just recorded). Compare against the rest.
    previous = history[:-1] if len(history) > 1 else []

    if not previous:
        return 0.5   # neutral until we have history

    prev_avg = statistics.mean(previous)
    velocity = today_size / max(prev_avg, 1.0)
    return _sigmoid(velocity - 1.0)


# ============================================================================
# 2. Opportunity score — demand × monetization
# ============================================================================
#
# Formula:
#     demand        = cluster_size / total_signals      (share of attention)
#     sentiment_lift = (avg_sentiment + 1) / 2          (-1..+1 -> 0..1)
#     monetization  = MONETIZATION_WEIGHTS[industry]
#
#     opportunity_score = demand_normalized * sentiment_lift * monetization
#
# Notes:
#   * demand_normalized = min(1.0, demand * 10) so that a single cluster
#     holding 10%+ of all signals gets full credit
#   * sentiment_lift rewards positive-buzz clusters over negative-buzz ones
#   * Industry is the strongest lever; weights are editable above
# ============================================================================

def _opportunity_score(cluster: dict[str, Any], total_signals: int) -> float:
    # Demand: what share of total attention does this cluster command?
    demand_share = cluster["size"] / max(total_signals, 1)
    demand_normalized = min(1.0, demand_share * 10.0)

    # Sentiment lift: positive sentiment = better opportunity
    avg_sentiment = _avg_member_sentiment(cluster["cluster_id"])
    sentiment_lift = (avg_sentiment + 1.0) / 2.0   # map -1..+1 to 0..1

    # Monetization: industry-based
    industry = cluster.get("industry") or "other"
    monetization = MONETIZATION_WEIGHTS.get(industry, MONETIZATION_WEIGHTS["other"])

    return demand_normalized * sentiment_lift * monetization


# ============================================================================
# 3. Market score — cross-source consensus
# ============================================================================
#
# Formula:
#     distinct_sources = COUNT(DISTINCT source) among cluster members
#     avg_quality      = AVG(source_quality) among cluster members
#
#     diversity = min(1.0, distinct_sources / 5)
#     market_score = 0.6 * diversity + 0.4 * avg_quality
#
# Notes:
#   * 5 distinct sources = full diversity credit; encourages cross-source signal
#   * source_quality is the per-source weight from quality.py (0.5-0.9)
#   * Trusted single source still scores moderately well via the quality term
# ============================================================================

def _market_score(cluster_id: int) -> float:
    distinct_sources, avg_quality = _source_stats_for(cluster_id)
    diversity = min(1.0, distinct_sources / 5.0)
    quality = avg_quality if avg_quality is not None else 0.5
    return 0.6 * diversity + 0.4 * quality


# ============================================================================
# Composite score
# ============================================================================

def _composite(trend: float, opportunity: float, market: float) -> float:
    """Weighted sum of the three scores, renormalized to [0, 1]."""
    total = (
        COMPOSITE_WEIGHTS["trend"]       * trend       +
        COMPOSITE_WEIGHTS["opportunity"] * opportunity +
        COMPOSITE_WEIGHTS["market"]      * market
    )
    weight_sum = sum(COMPOSITE_WEIGHTS.values())
    return total / weight_sum if weight_sum > 0 else 0.0


# ============================================================================
# Small DB helpers (kept here, not in db.py, since they're scoring-specific)
# ============================================================================

def _avg_member_sentiment(cluster_id: int) -> float:
    """Average sentiment_score across all signals in this cluster."""
    import sqlite3
    from app.db import _connect

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT AVG(t.sentiment_score) AS avg_sentiment
            FROM signal_clusters sc
            JOIN topics t ON t.signal_id = sc.signal_id
            WHERE sc.cluster_id = ?
            """,
            (cluster_id,),
        ).fetchone()
    return float(row["avg_sentiment"] or 0.0)


def _source_stats_for(cluster_id: int) -> tuple[int, float | None]:
    """Return (distinct_source_count, average_source_quality) for a cluster."""
    from app.db import _connect

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT s.source) AS n_sources,
                AVG(t.source_quality)    AS avg_quality
            FROM signal_clusters sc
            JOIN signals s ON s.id = sc.signal_id
            JOIN topics  t ON t.signal_id = sc.signal_id
            WHERE sc.cluster_id = ?
            """,
            (cluster_id,),
        ).fetchone()
    n = int(row["n_sources"] or 0)
    q = float(row["avg_quality"]) if row["avg_quality"] is not None else None
    return n, q


# ============================================================================
# Sigmoid (no numpy dep at this layer)
# ============================================================================

def _sigmoid(x: float) -> float:
    """Standard sigmoid. Maps real numbers to [0, 1]."""
    import math
    # Guard against overflow on extreme inputs.
    if x > 30:
        return 1.0
    if x < -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))
