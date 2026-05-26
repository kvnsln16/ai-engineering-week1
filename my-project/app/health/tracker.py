from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class CollectorStatus:
    name: str
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    last_record_count: int = 0
    last_new_count: int = 0
    consecutive_failures: int = 0
    total_runs: int = 0


class HealthTracker:

    def __init__(self) -> None:
        self._statuses: dict[str, CollectorStatus] = {}
        self._lock = threading.Lock()
        self._started_at: str = _now_iso()

    def record_success(
        self,
        name: str,
        *,
        record_count: int,
        new_count: int,
    ) -> None:
        with self._lock:
            status = self._statuses.setdefault(name, CollectorStatus(name=name))
            now = _now_iso()
            status.last_run_at = now
            status.last_success_at = now
            status.last_error = None
            status.last_record_count = record_count
            status.last_new_count = new_count
            status.consecutive_failures = 0
            status.total_runs += 1

    def record_failure(self, name: str, error: str) -> None:
        with self._lock:
            status = self._statuses.setdefault(name, CollectorStatus(name=name))
            status.last_run_at = _now_iso()
            status.last_error = error
            status.consecutive_failures += 1
            status.total_runs += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            collectors = [asdict(s) for s in self._statuses.values()]

        if not collectors:
            overall = "unknown"
        elif any(c["consecutive_failures"] > 0 for c in collectors):
            overall = "degraded"
        elif any(c["last_success_at"] is None for c in collectors):
            overall = "degraded"
        else:
            overall = "healthy"

        return {
            "status": overall,
            "started_at": self._started_at,
            "checked_at": _now_iso(),
            "collector_count": len(collectors),
            "collectors": collectors,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


shared_tracker = HealthTracker()
