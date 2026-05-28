from __future__ import annotations

import logging
import math
import random
import sys
from datetime import datetime, timedelta, timezone

from app import db


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(message)s",
)


HISTORY_DAYS = 35

PATTERNS = ["growth", "decline", "stable", "volatile"]


def main() -> int:
    db.init_db()

    clusters = db.top_clusters(limit=10_000, sort_by="size")
    if not clusters:
        print("No clusters found. Run `python run_once.py` first.")
        return 1

    print(f"Seeding {HISTORY_DAYS} days of synthetic history for {len(clusters)} clusters")
    print("(this is synthetic data, for demo purposes only)\n")

    today = datetime.now(timezone.utc).date()
    rng = random.Random(42)

    for i, cluster in enumerate(clusters):
        cluster_id = cluster["cluster_id"]
        current_size = cluster["size"]
        label = cluster["label"]
        pattern = PATTERNS[i % len(PATTERNS)]

        series = _build_series(
            current_size=current_size,
            days=HISTORY_DAYS,
            pattern=pattern,
            rng=rng,
        )

        for day_offset, size in enumerate(series):
            snapshot_day = today - timedelta(days=HISTORY_DAYS - 1 - day_offset)
            db.record_cluster_history(
                cluster_id,
                size,
                snapshot_day=snapshot_day.strftime("%Y-%m-%d"),
            )

        print(
            f"  Cluster {cluster_id:3d} ({label[:35]:35})  "
            f"pattern={pattern:8}  start={series[0]:3d} -> end={series[-1]:3d}"
        )

    print(f"\nDone. Seeded {len(clusters)} clusters x {HISTORY_DAYS} days.")
    print("\nNext: python run_once.py")
    return 0


def _build_series(*, current_size, days, pattern, rng):
    if pattern == "growth":
        start = max(2, int(current_size * 0.4))
        slope = (current_size - start) / max(days - 1, 1)
        base = [int(start + slope * t) for t in range(days)]
    elif pattern == "decline":
        start = max(current_size + 5, int(current_size * 1.7))
        slope = (current_size - start) / max(days - 1, 1)
        base = [int(start + slope * t) for t in range(days)]
    elif pattern == "stable":
        base = [current_size] * days
    elif pattern == "volatile":
        amplitude = max(2, int(current_size * 0.3))
        base = [
            int(current_size + amplitude * math.sin(2 * math.pi * t / 14))
            for t in range(days)
        ]
    else:
        base = [current_size] * days

    noise = [rng.randint(-1, 1) for _ in range(days)]
    return [max(1, b + n) for b, n in zip(base, noise)]


if __name__ == "__main__":
    sys.exit(main())