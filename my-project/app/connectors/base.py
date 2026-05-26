from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.services.http_client import get as http_get, HttpError
from app.services.rate_limiter import shared_limiter
from app.services.retry import retry

logger = logging.getLogger(__name__)


class BaseConnector(ABC):

    name: str = "base"
    source_url: str = ""

    def collect(self) -> list[dict[str, Any]]:
        logger.info("[%s] collecting from %s", self.name, self.source_url)

        try:
            raw = self.fetch()
        except HttpError as exc:
            logger.warning("[%s] fetch failed: %s", self.name, exc)
            return []
        except Exception as exc:
            logger.exception("[%s] unexpected fetch error: %s", self.name, exc)
            return []

        try:
            records = self.parse(raw)
        except Exception as exc:
            logger.exception("[%s] parse failed: %s", self.name, exc)
            return []

        logger.info("[%s] collected %d records", self.name, len(records))
        return records

    @retry(max_attempts=3, base_delay=1.0)
    def fetch(self) -> bytes:
        if not self.source_url:
            raise ValueError(f"{self.name}: source_url is empty")
        shared_limiter.acquire(self.source_url)
        response = http_get(self.source_url)
        return response.body

    @abstractmethod
    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        raise NotImplementedError