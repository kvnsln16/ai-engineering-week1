from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from app import db
from app.forecasting import HORIZONS, MIN_HISTORY_DAYS
from app.health.tracker import shared_tracker
from app.integrations.openclaw import openclaw_client
from app.reporting import generate_report, list_reports

logger = logging.getLogger(__name__)


SORT_OPTIONS = {"composite", "trend", "opportunity", "market", "size"}
DIRECTIONS = {"growth", "decline", "stable"}


def create_app(*, trigger_callback=None) -> FastAPI:
    app = FastAPI(
        title="First Project Orchestrator",
        version="1.5.0",
        description="Signal pipeline: collect, enrich, cluster, forecast, predict, report.",
    )

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
            snapshot["forecasts"] = db.count_forecasts()
            snapshot["predictions"] = db.count_predictions()
        except Exception as exc:
            logger.warning("health: could not read DB counts: %s", exc)
            for k in ("total_signals_in_db", "enriched_signals",
                      "clusters", "forecasts", "predictions"):
                snapshot[k] = None
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

    @app.get("/clusters")
    def list_clusters(
        limit: int = Query(default=50, ge=1, le=500),
        sort: str = Query(default="composite"),
    ) -> list[dict[str, Any]]:
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
        if sort not in SORT_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"sort must be one of {sorted(SORT_OPTIONS)}",
            )
        clusters = db.top_clusters(limit=n, sort_by=sort)
        return {"n": len(clusters), "sort_by": sort, "clusters": clusters}

    @app.get("/clusters/stats")
    def clusters_stats() -> dict[str, Any]:
        total = db.count_clusters()
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
        cluster = db.cluster_with_signals(cluster_id)
        if cluster is None:
            raise HTTPException(
                status_code=404,
                detail=f"cluster {cluster_id} not found",
            )
        return cluster

    @app.get("/forecasts/stats")
    def forecasts_stats() -> dict[str, Any]:
        total = db.count_forecasts()
        total_clusters = db.count_clusters()
        clusters_forecasted = total // len(HORIZONS) if HORIZONS else 0
        return {
            "total_forecasts":       total,
            "horizons":              HORIZONS,
            "clusters_forecasted":   clusters_forecasted,
            "total_clusters":        total_clusters,
            "forecast_coverage":     (
                round(clusters_forecasted / total_clusters, 3)
                if total_clusters else 0.0
            ),
            "min_history_days":      MIN_HISTORY_DAYS,
        }

    @app.get("/forecasts/horizon/{days}")
    def forecasts_at_horizon(
        days: int,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        if days not in HORIZONS:
            raise HTTPException(
                status_code=400,
                detail=f"horizon must be one of {HORIZONS}",
            )
        forecasts = db.all_forecasts(horizon_days=days, limit=limit)
        return {
            "horizon_days": days,
            "count":        len(forecasts),
            "forecasts":    forecasts,
        }

    @app.get("/forecasts/cluster/{cluster_id}")
    def forecasts_for_one_cluster(cluster_id: int) -> dict[str, Any]:
        cluster = db.cluster_with_signals(cluster_id)
        if cluster is None:
            raise HTTPException(
                status_code=404,
                detail=f"cluster {cluster_id} not found",
            )

        forecasts = db.forecasts_for_cluster(cluster_id)
        if not forecasts:
            history = db.cluster_history_series(cluster_id, days=365)
            return {
                "cluster_id":    cluster_id,
                "label":         cluster["label"],
                "industry":      cluster["industry"],
                "status":        "insufficient_history",
                "history_days":  len(history),
                "required_days": MIN_HISTORY_DAYS,
                "message": (
                    f"Need at least {MIN_HISTORY_DAYS} days of cluster history "
                    f"to forecast. Currently have {len(history)}."
                ),
                "forecasts": [],
            }

        return {
            "cluster_id": cluster_id,
            "label":      cluster["label"],
            "industry":   cluster["industry"],
            "status":     "ok",
            "forecasts":  forecasts,
        }

    @app.get("/predictions/stats")
    def predictions_stats() -> dict[str, Any]:
        total = db.count_predictions()
        return {
            "total_predictions": total,
            "horizons":          HORIZONS,
            "directions":        sorted(DIRECTIONS),
        }

    @app.get("/predictions")
    def list_predictions(
        horizon: int | None = Query(default=None),
        min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
        cluster_id: int | None = Query(default=None),
        direction: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        if horizon is not None and horizon not in HORIZONS:
            raise HTTPException(
                status_code=400,
                detail=f"horizon must be one of {HORIZONS}",
            )
        if direction is not None and direction not in DIRECTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"direction must be one of {sorted(DIRECTIONS)}",
            )

        predictions = db.predictions_filtered(
            horizon_days=horizon,
            min_confidence=min_confidence,
            cluster_id=cluster_id,
            direction=direction,
            limit=limit,
        )
        return {
            "filters": {
                "horizon":        horizon,
                "min_confidence": min_confidence,
                "cluster_id":     cluster_id,
                "direction":      direction,
            },
            "count":       len(predictions),
            "predictions": predictions,
        }

    @app.get("/predictions/top")
    def predictions_top(
        n: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        predictions = db.predictions_filtered(limit=n)
        return {"n": len(predictions), "predictions": predictions}

    @app.get("/predictions/cluster/{cluster_id}")
    def predictions_for_one_cluster(cluster_id: int) -> dict[str, Any]:
        cluster = db.cluster_with_signals(cluster_id)
        if cluster is None:
            raise HTTPException(
                status_code=404,
                detail=f"cluster {cluster_id} not found",
            )
        predictions = db.predictions_for_cluster(cluster_id)
        return {
            "cluster_id":  cluster_id,
            "label":       cluster["label"],
            "industry":    cluster["industry"],
            "count":       len(predictions),
            "predictions": predictions,
        }

    @app.get("/predictions/{prediction_id}")
    def prediction_detail(prediction_id: int) -> dict[str, Any]:
        prediction = db.prediction_by_id(prediction_id)
        if prediction is None:
            raise HTTPException(
                status_code=404,
                detail=f"prediction {prediction_id} not found",
            )

        supporting = _hydrate_signals(prediction.get("supporting_signal_ids", []))
        counter = _hydrate_signals(prediction.get("counter_signal_ids", []))
        prediction["supporting_signals"] = supporting
        prediction["counter_signals"] = counter

        return prediction

    @app.get("/reports")
    def reports_list() -> dict[str, Any]:
        reports = list_reports()
        return {
            "count":   len(reports),
            "reports": reports,
        }

    @app.get("/reports/latest")
    def reports_latest_metadata() -> dict[str, Any]:
        reports = list_reports()
        if not reports:
            raise HTTPException(
                status_code=404,
                detail="no reports generated yet — POST /reports/generate to create one",
            )
        return reports[0]

    @app.get("/reports/latest/html", response_class=HTMLResponse)
    def reports_latest_html() -> str:
        latest = Path("reports") / "latest.html"
        if not latest.exists():
            raise HTTPException(
                status_code=404,
                detail="no latest.html exists yet — generate a report first",
            )
        return latest.read_text(encoding="utf-8")

    @app.get("/reports/latest/markdown", response_class=PlainTextResponse)
    def reports_latest_markdown() -> str:
        latest = Path("reports") / "latest.md"
        if not latest.exists():
            raise HTTPException(
                status_code=404,
                detail="no latest.md exists yet — generate a report first",
            )
        return latest.read_text(encoding="utf-8")

    @app.get("/reports/{timestamp}", response_class=PlainTextResponse)
    def reports_one(timestamp: str) -> str:
        md_path = Path("reports") / f"report-{timestamp}.md"
        if not md_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"no report found with timestamp {timestamp!r}",
            )
        return md_path.read_text(encoding="utf-8")

    @app.post("/reports/generate")
    def reports_generate() -> dict[str, Any]:
        try:
            return generate_report()
        except Exception as exc:
            logger.exception("reports/generate failed: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"report generation failed: {exc}",
            ) from exc

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


def _hydrate_signals(signal_ids: list[int]) -> list[dict[str, Any]]:
    if not signal_ids:
        return []

    from app.db import _connect

    placeholders = ",".join("?" * len(signal_ids))
    with _connect() as conn:
        cur = conn.execute(
            f"""
            SELECT id, source, title, url, published_at
            FROM signals
            WHERE id IN ({placeholders})
            """,
            signal_ids,
        )
        rows = [dict(r) for r in cur.fetchall()]

    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in signal_ids if i in by_id]
