"""
db.py  (extended for clustering & scoring)
------------------------------------------
Adds three tables and their helpers:

  * clusters         — one row per discovered topic cluster
  * signal_clusters  — many signals : one cluster
  * cluster_scores   — trend / opportunity / market scores per cluster

Plus helper functions:
  * load_enriched_for_clustering()  — pulls signals + embeddings
  * save_clusters(...)              — atomic replacement of all clusters
  * top_clusters(limit, sort_by)    — for the /clusters/top API
  * cluster_with_signals(id)        — drill-down for /clusters/{id}

REPLACES the previous db.py. All previous functions remain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("db") / "app.sqlite"

_lock = threading.Lock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_hash   TEXT    NOT NULL UNIQUE,
    source        TEXT    NOT NULL,
    source_url    TEXT,
    title         TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    author        TEXT,
    published_at  TEXT,
    summary       TEXT,
    tags_json     TEXT,
    raw_json      TEXT,
    inserted_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_source       ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_inserted_at  ON signals(inserted_at);

CREATE TABLE IF NOT EXISTS seen_signals (
    signal_hash  TEXT    PRIMARY KEY,
    source       TEXT    NOT NULL,
    first_seen   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    signal_id           INTEGER PRIMARY KEY,
    topic_label         TEXT,
    topic_keywords      TEXT,
    topic_embedding     BLOB,
    sentiment_label     TEXT,
    sentiment_score     REAL,
    source_quality      REAL,
    industry            TEXT,
    industry_secondary  TEXT,
    enriched_at         TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_topics_industry  ON topics(industry);
CREATE INDEX IF NOT EXISTS idx_topics_sentiment ON topics(sentiment_label);

-- Clustering & scoring tables --------------------------------------------

CREATE TABLE IF NOT EXISTS clusters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT    NOT NULL,
    keywords_json TEXT,
    industry      TEXT,
    size          INTEGER NOT NULL,
    centroid      BLOB,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clusters_industry ON clusters(industry);

CREATE TABLE IF NOT EXISTS signal_clusters (
    signal_id  INTEGER PRIMARY KEY,
    cluster_id INTEGER NOT NULL,
    FOREIGN KEY (signal_id)  REFERENCES signals(id)  ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_signal_clusters_cluster ON signal_clusters(cluster_id);

CREATE TABLE IF NOT EXISTS cluster_scores (
    cluster_id        INTEGER PRIMARY KEY,
    trend_score       REAL,
    opportunity_score REAL,
    market_score      REAL,
    composite_score   REAL,
    computed_at       TEXT NOT NULL,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cluster_scores_composite ON cluster_scores(composite_score);

-- Daily snapshot of cluster sizes, used by trend score calculation.
-- One row per (cluster, day). Lets us compute "growth velocity" by
-- comparing today's size against the rolling average of the last 7 days.
CREATE TABLE IF NOT EXISTS cluster_history (
    cluster_id   INTEGER NOT NULL,
    snapshot_day TEXT    NOT NULL,   -- YYYY-MM-DD UTC
    size         INTEGER NOT NULL,
    PRIMARY KEY (cluster_id, snapshot_day),
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);
"""


_db_path: Path = DEFAULT_DB_PATH


def init_db(db_path: Path | str | None = None) -> None:
    global _db_path
    if db_path is not None:
        _db_path = Path(db_path)

    _db_path.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    logger.info("db: initialized at %s", _db_path)


@contextmanager
def _connect():
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------- dedup (unchanged) --------------------------------------------

def signal_hash(record: dict[str, Any]) -> str:
    url = (record.get("url") or "").strip().lower()
    title = (record.get("title") or "").strip().lower()
    payload = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def record_exists(hash_value: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM seen_signals WHERE signal_hash = ? LIMIT 1",
            (hash_value,),
        )
        return cur.fetchone() is not None


def mark_seen(hash_value: str, source: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_signals (signal_hash, source, first_seen) "
            "VALUES (?, ?, ?)",
            (hash_value, source, _now_iso()),
        )
        conn.commit()


def insert_record(record: dict[str, Any]) -> bool:
    h = signal_hash(record)

    with _lock, _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM seen_signals WHERE signal_hash = ? LIMIT 1",
            (h,),
        )
        if cur.fetchone() is not None:
            return False

        conn.execute(
            """
            INSERT INTO signals (
                signal_hash, source, source_url, title, url,
                author, published_at, summary, tags_json, raw_json,
                inserted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                h,
                record.get("source", ""),
                record.get("source_url"),
                record.get("title", ""),
                record.get("url", ""),
                record.get("author"),
                record.get("published_at"),
                record.get("summary", ""),
                json.dumps(record.get("tags", []), ensure_ascii=False),
                json.dumps(record.get("raw", {}), ensure_ascii=False),
                _now_iso(),
            ),
        )
        conn.execute(
            "INSERT INTO seen_signals (signal_hash, source, first_seen) "
            "VALUES (?, ?, ?)",
            (h, record.get("source", ""), _now_iso()),
        )
        conn.commit()
        return True


def insert_records(records: Iterable[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    duplicates = 0
    for r in records:
        if insert_record(r):
            inserted += 1
        else:
            duplicates += 1
    return inserted, duplicates


# ---------- enrichment helpers (unchanged) -------------------------------

def signals_needing_enrichment(limit: int = 1000) -> list[dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT s.id, s.source, s.title, s.summary, s.url
            FROM signals s
            LEFT JOIN topics t ON t.signal_id = s.id
            WHERE t.signal_id IS NULL
            ORDER BY s.id
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def save_enrichment(
    *,
    signal_id: int,
    topic_label: str,
    topic_keywords: list[str],
    topic_embedding: bytes,
    sentiment_label: str,
    sentiment_score: float,
    source_quality: float,
    industry: str,
    industry_secondary: list[str],
) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO topics (
                signal_id, topic_label, topic_keywords, topic_embedding,
                sentiment_label, sentiment_score, source_quality,
                industry, industry_secondary, enriched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                topic_label,
                json.dumps(topic_keywords, ensure_ascii=False),
                topic_embedding,
                sentiment_label,
                sentiment_score,
                source_quality,
                industry,
                json.dumps(industry_secondary, ensure_ascii=False),
                _now_iso(),
            ),
        )
        conn.commit()


def count_enriched() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM topics")
        return int(cur.fetchone()[0])


def enrichment_stats() -> dict[str, Any]:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]

        by_industry = {
            row["industry"]: row["n"]
            for row in conn.execute(
                "SELECT industry, COUNT(*) AS n FROM topics "
                "GROUP BY industry ORDER BY n DESC"
            ).fetchall()
        }

        by_sentiment = {
            row["sentiment_label"]: row["n"]
            for row in conn.execute(
                "SELECT sentiment_label, COUNT(*) AS n FROM topics "
                "GROUP BY sentiment_label"
            ).fetchall()
        }

        avg_quality = conn.execute(
            "SELECT AVG(source_quality) FROM topics"
        ).fetchone()[0]

    return {
        "total_enriched": int(total),
        "by_industry": by_industry,
        "by_sentiment": by_sentiment,
        "avg_source_quality": round(avg_quality, 3) if avg_quality else None,
    }


# ---------- clustering helpers (NEW) -------------------------------------

def load_enriched_for_clustering() -> list[dict[str, Any]]:
    """
    Pull every enriched signal with its embedding, for clustering.

    Returns rows shaped for the clusterer:
        signal_id, source, title, summary, keywords, industry,
        sentiment_score, source_quality, embedding (bytes)
    """
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT
                s.id               AS signal_id,
                s.source           AS source,
                s.title            AS title,
                s.summary          AS summary,
                t.topic_keywords   AS keywords,
                t.industry         AS industry,
                t.sentiment_score  AS sentiment_score,
                t.source_quality   AS source_quality,
                t.topic_embedding  AS embedding
            FROM signals s
            JOIN topics t ON t.signal_id = s.id
            WHERE t.topic_embedding IS NOT NULL
              AND LENGTH(t.topic_embedding) > 0
            ORDER BY s.id
            """
        )
        return [dict(row) for row in cur.fetchall()]


def save_clusters(
    clusters: list[dict[str, Any]],
    assignments: list[tuple[int, int]],
) -> dict[int, int]:
    """
    Atomically replace ALL clusters and their signal assignments.

    Args:
      clusters: list of dicts with keys
        local_id, label, keywords, industry, size, centroid_bytes
      assignments: list of (signal_id, local_cluster_id) pairs

    Returns: mapping from local_cluster_id -> db_cluster_id (the persisted PK)
    """
    now = _now_iso()

    with _lock, _connect() as conn:
        # Wipe previous clusters (CASCADE handles signal_clusters,
        # cluster_scores, cluster_history). History is intentionally
        # rebuilt to keep cluster IDs stable-ish per run.
        conn.execute("DELETE FROM clusters")

        # Insert new clusters and remember the new PK per local_id.
        local_to_db: dict[int, int] = {}
        for cluster in clusters:
            cur = conn.execute(
                """
                INSERT INTO clusters
                    (label, keywords_json, industry, size, centroid,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cluster["label"],
                    json.dumps(cluster.get("keywords", []), ensure_ascii=False),
                    cluster.get("industry"),
                    cluster["size"],
                    cluster.get("centroid_bytes"),
                    now,
                    now,
                ),
            )
            local_to_db[cluster["local_id"]] = cur.lastrowid

        # Insert signal-to-cluster mapping.
        for signal_id, local_cluster_id in assignments:
            db_cluster_id = local_to_db.get(local_cluster_id)
            if db_cluster_id is None:
                continue   # signal was noise (cluster -1)
            conn.execute(
                "INSERT OR REPLACE INTO signal_clusters (signal_id, cluster_id) "
                "VALUES (?, ?)",
                (signal_id, db_cluster_id),
            )

        conn.commit()
    return local_to_db


def save_cluster_scores(
    scores: list[dict[str, Any]],
) -> None:
    """
    Upsert scores for each cluster.

    Each dict has keys:
        cluster_id, trend_score, opportunity_score, market_score, composite_score
    """
    now = _now_iso()
    with _lock, _connect() as conn:
        for s in scores:
            conn.execute(
                """
                INSERT OR REPLACE INTO cluster_scores
                    (cluster_id, trend_score, opportunity_score,
                     market_score, composite_score, computed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    s["cluster_id"],
                    s["trend_score"],
                    s["opportunity_score"],
                    s["market_score"],
                    s["composite_score"],
                    now,
                ),
            )
        conn.commit()


def record_cluster_history(
    cluster_id: int,
    size: int,
    *,
    snapshot_day: str | None = None,
) -> None:
    """
    Save today's size for one cluster. Idempotent — re-running on the
    same day just updates the row.
    """
    day = snapshot_day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cluster_history "
            "(cluster_id, snapshot_day, size) VALUES (?, ?, ?)",
            (cluster_id, day, size),
        )
        conn.commit()


def recent_cluster_sizes(cluster_id: int, days: int = 7) -> list[int]:
    """
    Return up to `days` recent size snapshots for this cluster, oldest first.
    Used by the trend score to compute growth velocity.
    """
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT size
            FROM cluster_history
            WHERE cluster_id = ?
            ORDER BY snapshot_day DESC
            LIMIT ?
            """,
            (cluster_id, days),
        )
        rows = [int(r["size"]) for r in cur.fetchall()]
    return list(reversed(rows))


# ---------- read APIs (for /clusters endpoints) --------------------------

def count_clusters() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0])


def top_clusters(
    *,
    limit: int = 20,
    sort_by: str = "composite",
) -> list[dict[str, Any]]:
    """
    Return the top N clusters sorted by one of:
        composite, trend, opportunity, market, size
    """
    column = {
        "composite":   "cs.composite_score",
        "trend":       "cs.trend_score",
        "opportunity": "cs.opportunity_score",
        "market":      "cs.market_score",
        "size":        "c.size",
    }.get(sort_by, "cs.composite_score")

    with _connect() as conn:
        cur = conn.execute(
            f"""
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                c.keywords_json,
                cs.trend_score, cs.opportunity_score,
                cs.market_score, cs.composite_score
            FROM clusters c
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            ORDER BY {column} DESC NULLS LAST
            LIMIT ?
            """,
            (limit,),
        )
        return [_cluster_row_to_dict(r) for r in cur.fetchall()]


def cluster_with_signals(cluster_id: int) -> dict[str, Any] | None:
    """Full details for one cluster including its member signals."""
    with _connect() as conn:
        cluster_row = conn.execute(
            """
            SELECT
                c.id AS cluster_id, c.label, c.industry, c.size,
                c.keywords_json,
                cs.trend_score, cs.opportunity_score,
                cs.market_score, cs.composite_score
            FROM clusters c
            LEFT JOIN cluster_scores cs ON cs.cluster_id = c.id
            WHERE c.id = ?
            """,
            (cluster_id,),
        ).fetchone()

        if cluster_row is None:
            return None

        signals = [
            dict(r) for r in conn.execute(
                """
                SELECT s.id, s.source, s.title, s.url, s.published_at,
                       t.sentiment_label, t.sentiment_score, t.source_quality
                FROM signal_clusters sc
                JOIN signals s ON s.id = sc.signal_id
                LEFT JOIN topics t ON t.signal_id = s.id
                WHERE sc.cluster_id = ?
                ORDER BY t.source_quality DESC NULLS LAST, s.id
                """,
                (cluster_id,),
            ).fetchall()
        ]

    result = _cluster_row_to_dict(cluster_row)
    result["signals"] = signals
    return result


def _cluster_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Format one DB row as a JSON-safe dict, parsing the keywords blob."""
    try:
        keywords = json.loads(row["keywords_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        keywords = []
    return {
        "cluster_id":        row["cluster_id"],
        "label":             row["label"],
        "industry":          row["industry"],
        "size":              row["size"],
        "keywords":          keywords,
        "trend_score":       row["trend_score"],
        "opportunity_score": row["opportunity_score"],
        "market_score":      row["market_score"],
        "composite_score":   row["composite_score"],
    }


# ---------- small utilities ----------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def count_signals() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM signals")
        return int(cur.fetchone()[0])
