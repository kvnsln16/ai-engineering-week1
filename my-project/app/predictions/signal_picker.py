from __future__ import annotations

from typing import Any


SUPPORTING_LIMIT = 5
COUNTER_LIMIT = 5


def pick_signals(
    cluster_signals: list[dict[str, Any]],
    direction: str,
) -> tuple[list[int], list[int]]:
    if not cluster_signals:
        return [], []

    supporting_pool, counter_pool = _split_by_alignment(cluster_signals, direction)

    supporting_pool.sort(
        key=lambda s: (-(s.get("source_quality") or 0.0), s["id"])
    )
    counter_pool.sort(
        key=lambda s: (-(s.get("source_quality") or 0.0), s["id"])
    )

    supporting_ids = [s["id"] for s in supporting_pool[:SUPPORTING_LIMIT]]
    counter_ids = [s["id"] for s in counter_pool[:COUNTER_LIMIT]]

    return supporting_ids, counter_ids


def _split_by_alignment(
    cluster_signals: list[dict[str, Any]],
    direction: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supporting: list[dict[str, Any]] = []
    counter: list[dict[str, Any]] = []

    for signal in cluster_signals:
        sentiment = signal.get("sentiment_score")
        if sentiment is None:
            sentiment = 0.0

        if direction == "growth":
            if sentiment > 0.05:
                supporting.append(signal)
            elif sentiment < -0.05:
                counter.append(signal)

        elif direction == "decline":
            if sentiment < -0.05:
                supporting.append(signal)
            elif sentiment > 0.05:
                counter.append(signal)

        else:
            if -0.05 <= sentiment <= 0.05:
                supporting.append(signal)
            else:
                counter.append(signal)

    return supporting, counter
