from __future__ import annotations

import logging
from typing import Any

from app import db
from app.db import _connect

logger = logging.getLogger(__name__)


DEFINITIONS = {
    "weak_signal": (
        "Clusters with 3-6 signals but at least 3 distinct sources, indicating "
        "early but cross-confirmed interest. These are topics that haven't broken "
        "out yet but multiple newsletters are independently noticing."
    ),
    "contrarian": (
        "Clusters where the forecasted direction (growth/decline) contradicts "
        "the average sentiment of member signals. For example: signals mostly "
        "negative but forecast shows growth. Contrarian opportunities or hidden risks."
    ),
    "threat": (
        "Clusters that are either (a) in the policy/safety industry AND forecast "
        "growth (regulatory risk), or (b) any cluster with rapid decline (forecast "
        "size < 60% of current) AND average sentiment negative."
    ),
}


def weak_signals(*, min_sources: int = 3, max_size: int = 6) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                COUNT(DISTINCT s.source) AS distinct_sources,
                cs.composite_score
            FROM clusters c
            JOIN signal_clusters sc ON sc.cluster_id = c.id
            JOIN signals s ON s.id = sc.signal_id
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            WHERE c.size BETWEEN 3 AND ?
            GROUP BY c.id
            HAVING COUNT(DISTINCT s.source) >= ?
            ORDER BY distinct_sources DESC, c.size ASC
            LIMIT 10
            """,
            (max_size, min_sources),
        ).fetchall()

    return [dict(r) for r in rows]


def contrarian_signals() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                p.text, p.direction, p.probability, p.confidence,
                p.horizon_days,
                AVG(t.sentiment_score) AS avg_sentiment
            FROM predictions p
            JOIN clusters c ON c.id = p.cluster_id
            JOIN signal_clusters sc ON sc.cluster_id = c.id
            JOIN topics t ON t.signal_id = sc.signal_id
            WHERE p.horizon_days = 30
            GROUP BY c.id, p.id
            """
        ).fetchall()

    for r in rows:
        direction = r["direction"]
        avg_sentiment = r["avg_sentiment"] or 0.0

        is_contrarian = False
        contrarian_type = ""

        if direction == "growth" and avg_sentiment < -0.1:
            is_contrarian = True
            contrarian_type = "growth_amid_negative_sentiment"
        elif direction == "decline" and avg_sentiment > 0.1:
            is_contrarian = True
            contrarian_type = "decline_amid_positive_sentiment"

        if is_contrarian:
            candidates.append({
                "cluster_id":     r["cluster_id"],
                "label":          r["label"],
                "industry":       r["industry"],
                "size":           r["size"],
                "direction":      direction,
                "text":           r["text"],
                "probability":    r["probability"],
                "confidence":     r["confidence"],
                "avg_sentiment":  round(avg_sentiment, 3),
                "contrarian_type": contrarian_type,
            })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates[:10]


def threats() -> list[dict[str, Any]]:
    threats_list: list[dict[str, Any]] = []

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                p.direction, p.text, p.probability, p.confidence,
                p.forecast_predicted, p.horizon_days,
                AVG(t.sentiment_score) AS avg_sentiment
            FROM predictions p
            JOIN clusters c ON c.id = p.cluster_id
            JOIN signal_clusters sc ON sc.cluster_id = c.id
            JOIN topics t ON t.signal_id = sc.signal_id
            WHERE p.horizon_days = 30
            GROUP BY c.id, p.id
            """
        ).fetchall()

    for r in rows:
        industry = r["industry"] or "other"
        direction = r["direction"]
        size = r["size"]
        predicted = r["forecast_predicted"] or size
        avg_sent = r["avg_sentiment"] or 0.0

        threat_type = None

        if industry == "policy_safety" and direction == "growth":
            threat_type = "regulatory_risk"
        elif direction == "decline" and predicted < size * 0.6 and avg_sent < -0.1:
            threat_type = "market_deterioration"

        if threat_type:
            threats_list.append({
                "cluster_id":    r["cluster_id"],
                "label":         r["label"],
                "industry":      industry,
                "size":          size,
                "direction":     direction,
                "text":          r["text"],
                "probability":   r["probability"],
                "confidence":    r["confidence"],
                "avg_sentiment": round(avg_sent, 3),
                "threat_type":   threat_type,
            })

    threats_list.sort(key=lambda x: x["confidence"], reverse=True)
    return threats_list[:10]


def industry_heatmap() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.industry,
                COUNT(c.id)      AS cluster_count,
                SUM(c.size)      AS total_signals,
                AVG(cs.composite_score) AS avg_composite
            FROM clusters c
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            GROUP BY c.industry
            ORDER BY total_signals DESC
            """
        ).fetchall()

    return {
        "industries": [
            {
                "industry":       r["industry"] or "other",
                "cluster_count":  int(r["cluster_count"] or 0),
                "total_signals":  int(r["total_signals"] or 0),
                "avg_composite":  round(r["avg_composite"] or 0.0, 3),
            }
            for r in rows
        ],
    }


def market_analysis() -> dict[str, Any]:
    with _connect() as conn:
        signal_per_source = conn.execute(
            """
            SELECT source, COUNT(*) AS n
            FROM signals
            GROUP BY source
            ORDER BY n DESC
            """
        ).fetchall()

        avg_diversity_row = conn.execute(
            """
            SELECT AVG(distinct_sources) AS avg_diversity
            FROM (
                SELECT COUNT(DISTINCT s.source) AS distinct_sources
                FROM signal_clusters sc
                JOIN signals s ON s.id = sc.signal_id
                GROUP BY sc.cluster_id
            )
            """
        ).fetchone()
        avg_diversity = avg_diversity_row["avg_diversity"] if avg_diversity_row else 0

    return {
        "sources_distribution": [
            {"source": r["source"], "signal_count": int(r["n"])}
            for r in signal_per_source
        ],
        "avg_sources_per_cluster": round(avg_diversity or 0.0, 2),
    }
