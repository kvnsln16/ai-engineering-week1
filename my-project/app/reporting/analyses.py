from __future__ import annotations

import logging
import statistics
from typing import Any

from app import db
from app.db import _connect

logger = logging.getLogger(__name__)


WEAK_STRICT_MIN_SOURCES = 3
WEAK_STRICT_MAX_SIZE = 6

WEAK_FALLBACK_MIN_SOURCES = 2
WEAK_FALLBACK_MAX_SIZE = 10

EVIDENCE_LIMIT = 5

WEAK_TARGET_MIN = 3

CONTRARIAN_DELTA = 0.15


DEFINITIONS = {
    "weak_signal": (
        "Clusters with small size but high source diversity, indicating early "
        "cross-confirmed interest. When historical data is available, we also "
        "require the cluster to be growing or stable (not fading)."
    ),
    "weak_signal_strict": (
        "Strict: cluster size 3-6 AND at least 3 distinct sources AND not "
        "fading (where history is available)."
    ),
    "weak_signal_candidate": (
        "Candidate (fallback): cluster size up to 10 AND at least 2 distinct "
        "sources. Used to keep the section populated when strict matches are scarce."
    ),
    "contrarian": (
        "Clusters whose forecasted direction OR sentiment diverges from the "
        "average for their industry. For example: a robotics cluster declining "
        "while the broader robotics conversation is growing."
    ),
    "threat": (
        "Clusters that are either (a) in the policy/safety industry AND forecast "
        "growth (regulatory risk), or (b) any cluster with rapid decline (forecast "
        "size < 60% of current) AND average sentiment negative."
    ),
}


def weak_signals() -> list[dict[str, Any]]:
    strict = _weak_pass(
        min_sources=WEAK_STRICT_MIN_SOURCES,
        max_size=WEAK_STRICT_MAX_SIZE,
        kind="strict",
    )

    if len(strict) >= WEAK_TARGET_MIN:
        return strict

    candidates = _weak_pass(
        min_sources=WEAK_FALLBACK_MIN_SOURCES,
        max_size=WEAK_FALLBACK_MAX_SIZE,
        kind="candidate",
    )
    seen_ids = {row["cluster_id"] for row in strict}
    additional = [c for c in candidates if c["cluster_id"] not in seen_ids]

    needed = WEAK_TARGET_MIN - len(strict)
    return strict + additional[:max(needed, 2)]


def _weak_pass(
    *,
    min_sources: int,
    max_size: int,
    kind: str,
) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                COUNT(DISTINCT s.source) AS distinct_sources,
                cs.composite_score, cs.trend_score
            FROM clusters c
            JOIN signal_clusters sc ON sc.cluster_id = c.id
            JOIN signals s ON s.id = sc.signal_id
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            WHERE c.size BETWEEN 3 AND ?
            GROUP BY c.id
            HAVING COUNT(DISTINCT s.source) >= ?
            ORDER BY distinct_sources DESC, c.size ASC
            LIMIT 20
            """,
            (max_size, min_sources),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        cluster_id = r["cluster_id"]

        is_rising_or_stable, history_days = _cluster_direction(cluster_id)

        if kind == "strict" and is_rising_or_stable is False:
            continue

        results.append({
            "cluster_id":          cluster_id,
            "label":               r["label"],
            "industry":            r["industry"] or "other",
            "size":                r["size"],
            "distinct_sources":    int(r["distinct_sources"]),
            "trend_score":         round(r["trend_score"] or 0.0, 3),
            "kind":                kind,
            "is_rising_or_stable": is_rising_or_stable,
            "history_days":        history_days,
            "evidence":            _evidence_for_cluster(cluster_id),
        })

    return results[:10]


def _cluster_direction(cluster_id: int) -> tuple[bool | None, int]:
    sizes = db.recent_cluster_sizes(cluster_id, days=7)
    if len(sizes) < 3:
        return (None, len(sizes))

    recent_avg = statistics.mean(sizes[-3:])
    earlier_avg = statistics.mean(sizes[:-3]) if len(sizes) > 3 else sizes[0]

    is_rising_or_stable = recent_avg >= earlier_avg * 0.9
    return (is_rising_or_stable, len(sizes))


def contrarian_signals() -> list[dict[str, Any]]:
    industry_baseline = _compute_industry_baselines()

    candidates: list[dict[str, Any]] = []

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                AVG(t.sentiment_score) AS avg_sentiment,
                cs.trend_score, cs.composite_score
            FROM clusters c
            JOIN signal_clusters sc ON sc.cluster_id = c.id
            JOIN topics t ON t.signal_id = sc.signal_id
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            GROUP BY c.id
            """
        ).fetchall()

    for r in rows:
        cluster_id = r["cluster_id"]
        industry = r["industry"] or "other"
        cluster_sentiment = r["avg_sentiment"] or 0.0
        cluster_trend = r["trend_score"] or 0.5

        baseline = industry_baseline.get(industry, {})
        industry_sentiment = baseline.get("avg_sentiment", 0.0)
        industry_trend = baseline.get("avg_trend", 0.5)

        sentiment_diff = cluster_sentiment - industry_sentiment
        trend_diff = cluster_trend - industry_trend

        is_contrarian = (
            abs(sentiment_diff) >= CONTRARIAN_DELTA or
            abs(trend_diff) >= 0.20
        )

        if not is_contrarian:
            continue

        contrarian_type = _classify_contrarian(
            sentiment_diff=sentiment_diff,
            trend_diff=trend_diff,
        )

        candidates.append({
            "cluster_id":         cluster_id,
            "label":              r["label"],
            "industry":           industry,
            "size":               r["size"],
            "cluster_sentiment":  round(cluster_sentiment, 3),
            "industry_sentiment": round(industry_sentiment, 3),
            "cluster_trend":      round(cluster_trend, 3),
            "industry_trend":     round(industry_trend, 3),
            "sentiment_diff":     round(sentiment_diff, 3),
            "trend_diff":         round(trend_diff, 3),
            "contrarian_type":    contrarian_type,
            "evidence":           _evidence_for_cluster(cluster_id),
        })

    candidates.sort(
        key=lambda x: max(abs(x["sentiment_diff"]), abs(x["trend_diff"])),
        reverse=True,
    )
    return candidates[:10]


def _classify_contrarian(*, sentiment_diff: float, trend_diff: float) -> str:
    sentiment_strong = abs(sentiment_diff) >= CONTRARIAN_DELTA
    trend_strong = abs(trend_diff) >= 0.20

    if sentiment_strong and trend_strong:
        return "double_divergence"
    if sentiment_strong:
        return "positive_outlier" if sentiment_diff > 0 else "negative_outlier"
    if trend_strong:
        return "rising_against_industry" if trend_diff > 0 else "falling_against_industry"
    return "weak_divergence"


def _compute_industry_baselines() -> dict[str, dict[str, float]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                c.industry,
                AVG(t.sentiment_score) AS avg_sentiment,
                AVG(cs.trend_score)    AS avg_trend,
                COUNT(DISTINCT c.id)   AS cluster_count
            FROM clusters c
            LEFT JOIN signal_clusters sc ON sc.cluster_id = c.id
            LEFT JOIN topics t ON t.signal_id = sc.signal_id
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            GROUP BY c.industry
            """
        ).fetchall()

    return {
        (r["industry"] or "other"): {
            "avg_sentiment": float(r["avg_sentiment"] or 0.0),
            "avg_trend":     float(r["avg_trend"] or 0.5),
            "cluster_count": int(r["cluster_count"] or 0),
        }
        for r in rows
    }


def _evidence_for_cluster(
    cluster_id: int,
    *,
    limit: int = EVIDENCE_LIMIT,
) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id, s.source, s.title, s.url,
                t.sentiment_score, t.source_quality
            FROM signal_clusters sc
            JOIN signals s ON s.id = sc.signal_id
            LEFT JOIN topics t ON t.signal_id = s.id
            WHERE sc.cluster_id = ?
            ORDER BY t.source_quality DESC NULLS LAST, s.id
            LIMIT ?
            """,
            (cluster_id, limit),
        ).fetchall()

    return [
        {
            "id":              r["id"],
            "source":          r["source"],
            "title":           (r["title"] or "")[:120],
            "url":             r["url"],
            "sentiment_score": round(r["sentiment_score"] or 0.0, 3),
        }
        for r in rows
    ]


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
