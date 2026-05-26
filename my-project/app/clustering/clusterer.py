"""
clusterer.py
------------
HDBSCAN-based clustering of enriched signals.

Pipeline:
  1. Pull every signal with an embedding from the DB
  2. Stack embeddings into a (n, 384) numpy matrix
  3. Run HDBSCAN to assign each signal a cluster label
  4. For each cluster, compute:
       - centroid (average embedding)
       - dominant industry
       - top keywords (most frequent across member signals)
       - human-readable label

Why HDBSCAN over k-means:
  * No need to choose k upfront — it finds the natural number
  * Robust to noise — signals that don't fit get label -1 (excluded)
  * Density-based — handles uneven cluster sizes well

Why no UMAP (which BERTopic uses):
  * 384 dims is already manageable for HDBSCAN
  * UMAP adds a hyperparameter to tune and is non-deterministic
  * Skipping it keeps results reproducible and the pipeline simple
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Minimum signals required to form a cluster. Tunable in scheduler/jobs.py
# if you find clusters are too big or too small for your data volume.
DEFAULT_MIN_CLUSTER_SIZE = 5

# Cosine distance via euclidean on normalized embeddings.
# Our embeddings are already normalized (see topics.py encode_batch),
# so euclidean and cosine give equivalent rankings.
DEFAULT_METRIC = "euclidean"


def cluster_signals(
    enriched_rows: list[dict[str, Any]],
    *,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    """
    Cluster enriched signals.

    Args:
      enriched_rows: list of dicts from db.load_enriched_for_clustering()
      min_cluster_size: smallest valid cluster (HDBSCAN parameter)

    Returns:
      (clusters, assignments)
        clusters: list of dicts ready for db.save_clusters
                  keys: local_id, label, keywords, industry, size, centroid_bytes
        assignments: list of (signal_id, local_cluster_id) pairs

    Signals labeled as noise by HDBSCAN (label -1) are NOT included in
    the assignments — they belong to no cluster.
    """
    if len(enriched_rows) < min_cluster_size:
        # Not enough data yet — return empty clustering.
        logger.info(
            "clusterer: only %d signals, need >= %d; skipping",
            len(enriched_rows), min_cluster_size,
        )
        return [], []

    embeddings = _stack_embeddings(enriched_rows)
    labels = _run_hdbscan(embeddings, min_cluster_size=min_cluster_size)

    unique_labels = sorted({int(l) for l in labels if l != -1})
    logger.info(
        "clusterer: %d signals -> %d clusters (%d noise)",
        len(enriched_rows),
        len(unique_labels),
        int((labels == -1).sum()),
    )

    clusters: list[dict[str, Any]] = []
    assignments: list[tuple[int, int]] = []

    for local_id in unique_labels:
        member_mask = labels == local_id
        members = [
            row for row, in_cluster in zip(enriched_rows, member_mask)
            if in_cluster
        ]
        member_embeddings = embeddings[member_mask]

        clusters.append({
            "local_id":        local_id,
            "label":           _build_label(members),
            "keywords":        _top_keywords(members),
            "industry":        _dominant_industry(members),
            "size":            len(members),
            "centroid_bytes":  _centroid(member_embeddings),
        })

        for member in members:
            assignments.append((member["signal_id"], local_id))

    return clusters, assignments


# ---------- internals -----------------------------------------------------

def _stack_embeddings(rows: list[dict[str, Any]]) -> np.ndarray:
    """Convert each row's stored embedding bytes back into a stacked matrix."""
    vectors = [
        np.frombuffer(row["embedding"], dtype=np.float32)
        for row in rows
    ]
    return np.vstack(vectors)


def _run_hdbscan(embeddings: np.ndarray, *, min_cluster_size: int) -> np.ndarray:
    """
    Run HDBSCAN and return the label array.

    Imported here (not at module top) so a missing hdbscan package only
    breaks clustering, not the rest of the pipeline.
    """
    import hdbscan

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,                # less conservative; fewer noise points
        metric=DEFAULT_METRIC,
        cluster_selection_method="eom",
        prediction_data=False,
    )
    return clusterer.fit_predict(embeddings)


def _centroid(embeddings: np.ndarray) -> bytes:
    """Average the embeddings in a cluster and serialize to bytes."""
    centroid = embeddings.mean(axis=0).astype(np.float32)
    return centroid.tobytes()


def _dominant_industry(members: list[dict[str, Any]]) -> str:
    """Return the most common industry among cluster members."""
    counts = Counter(
        (m.get("industry") or "other") for m in members
    )
    return counts.most_common(1)[0][0]


def _top_keywords(
    members: list[dict[str, Any]],
    *,
    max_keywords: int = 6,
) -> list[str]:
    """
    Aggregate keywords across all cluster members and return the most
    frequent. The keywords column is stored as JSON in the topics table.
    """
    counts: Counter[str] = Counter()
    for member in members:
        try:
            kws = json.loads(member.get("keywords") or "[]")
        except json.JSONDecodeError:
            kws = []
        for kw in kws:
            if kw and isinstance(kw, str):
                counts[kw.lower()] += 1

    return [kw for kw, _ in counts.most_common(max_keywords)]


def _build_label(members: list[dict[str, Any]]) -> str:
    """
    Human-readable cluster label.

    Built from the top 3 keywords. Falls back to the first member's title
    if no keywords could be extracted.
    """
    top = _top_keywords(members, max_keywords=3)
    if top:
        return ", ".join(w.title() for w in top)
    # Fallback: use a title from the cluster
    first_title = members[0].get("title", "").strip()
    return first_title[:80] if first_title else "untitled cluster"
