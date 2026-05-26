"""
api.py  (extended for clustering)
---------------------------------
Adds four cluster-related endpoints:

  GET /clusters                 — list of clusters (paginated)
  GET /clusters/top             — top N by composite score (or trend/opp/market)
  GET /clusters/{id}            — drill-down with member signals
  GET /clusters/stats           — overall counts

All previous endpoints (/, /health, /enrich/stats, /trigger) unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Query

from app import db
from app.health.tracker import shared_tracker
from app.integrations.openclaw import openclaw_client

logger = logging.getLogger(__name__)


SORT_OPTIONS = {"composite", "trend", "opportunity", "market", "size"}


def create_app(*, trigger_callback=None) -> FastAPI:
    app = FastAPI(
        title="First Project Orchestrator",
        version="1.2.0",
        description="Signal pipeline: collect, enrich, cluster, and score.",
    )

    # ---------- liveness & health -----------------------------------------

    @app.get("/")
    def root() -> dict[str, str]:
        return {"status": "up", "service": "first-project-orchestrator"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        snapshot = shared_tracker.snapshot()
        try:
            snapshot["total_signals_in_db"] = db.count_signals()
            snapshot["enriched_signals"] = db.count_enriched()
            snapshot["clusters"] = db.count_clusters()
        except Exception as exc:
            logger.warning("health: could not read DB counts: %s", exc)
            snapshot["total_signals_in_db"] = None
            snapshot["enriched_signals"] = None
            snapshot["clusters"] = None
        return snapshot

    @app.get("/health/collectors")
    def health_collectors() -> list[dict[str, Any]]:
        return shared_tracker.snapshot()["collectors"]

    @app.get("/health/collectors/{name}")
    def health_collector(name: str) -> dict[str, Any]:
        for c in shared_tracker.snapshot()["collectors"]:
            if c["name"] == name:
                return c
        raise HTTPException(status_code=404, detail=f"collector {name!r} not found")

    # ---------- enrichment stats ------------------------------------------

    @app.get("/enrich/stats")
    def enrich_stats() -> dict[str, Any]:
        try:
            stats = db.enrichment_stats()
        except Exception as exc:
            logger.warning("enrich_stats: could not read DB: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="could not read enrichment stats",
            ) from exc

        total_signals = db.count_signals()
        stats["total_signals_in_db"] = total_signals
        stats["enrichment_coverage"] = (
            round(stats["total_enriched"] / total_signals, 3)
            if total_signals else 0.0
        )
        return stats

    # ---------- clusters --------------------------------------------------

    @app.get("/clusters")
    def list_clusters(
        limit: int = Query(default=50, ge=1, le=500),
        sort: str = Query(default="composite"),
    ) -> list[dict[str, Any]]:
        """List clusters, sorted by one of the score columns."""
        if sort not in SORT_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"sort must be one of {sorted(SORT_OPTIONS)}",
            )
        return db.top_clusters(limit=limit, sort_by=sort)

    @app.get("/clusters/top")
    def clusters_top(
        n: int = Query(default=20, ge=1, le=100),
        sort: str = Query(default="composite"),
    ) -> dict[str, Any]:
        """
        Top N clusters by score. Spec calls for top 20 trending topics.

        Example:
            /clusters/top?n=20&sort=trend         — top 20 by growth velocity
            /clusters/top?n=10&sort=opportunity   — top 10 commercially interesting
        """
        if sort not in SORT_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"sort must be one of {sorted(SORT_OPTIONS)}",
            )
        clusters = db.top_clusters(limit=n, sort_by=sort)
        return {
            "n": len(clusters),
            "sort_by": sort,
            "clusters": clusters,
        }

    @app.get("/clusters/stats")
    def clusters_stats() -> dict[str, Any]:
        """Overall cluster counts and breakdowns."""
        total = db.count_clusters()
        # Drill into industry counts using top_clusters; reuse logic
        clusters = db.top_clusters(limit=10_000, sort_by="size")
        by_industry: dict[str, int] = {}
        for c in clusters:
            ind = c.get("industry") or "other"
            by_industry[ind] = by_industry.get(ind, 0) + 1

        return {
            "total_clusters": total,
            "by_industry": dict(sorted(
                by_industry.items(), key=lambda kv: kv[1], reverse=True
            )),
            "total_signals_clustered": sum(c["size"] for c in clusters),
        }

    @app.get("/clusters/{cluster_id}")
    def cluster_detail(cluster_id: int) -> dict[str, Any]:
        """Full cluster details with member signals."""
        cluster = db.cluster_with_signals(cluster_id)
        if cluster is None:
            raise HTTPException(
                status_code=404,
                detail=f"cluster {cluster_id} not found",
            )
        return cluster

    # ---------- trigger ---------------------------------------------------

    @app.post("/trigger")
    def trigger(
        background_tasks: BackgroundTasks,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        if trigger_callback is None:
            raise HTTPException(
                status_code=503,
                detail="trigger not configured on this server",
            )

        expected = openclaw_client.token
        if expected:
            provided = (authorization or "").removeprefix("Bearer ").strip()
            if provided != expected:
                raise HTTPException(status_code=401, detail="invalid token")

        background_tasks.add_task(trigger_callback)
        return {"status": "queued"}

    return app
