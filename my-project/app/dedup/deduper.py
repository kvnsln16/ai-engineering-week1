from __future__ import annotations

import logging
from typing import Any

from app import db

logger = logging.getLogger(__name__)


class Deduper:

    def filter_new(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        new: list[dict[str, Any]] = []
        duplicates = 0

        for record in records:
            h = db.signal_hash(record)
            if db.record_exists(h):
                duplicates += 1
            else:
                new.append(record)

        if duplicates:
            logger.info("deduper: %d duplicates filtered, %d new", duplicates, len(new))
        return new, duplicates
