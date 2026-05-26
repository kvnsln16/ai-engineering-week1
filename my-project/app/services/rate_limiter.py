from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    capacity: float
    refill_per_sec: float
    tokens: float
    last_refill: float


class RateLimiter:

    def __init__(
        self,
        default_rate_per_sec: float = 1.0,
        default_burst: float = 2.0,
    ) -> None:
        self._default_rate = default_rate_per_sec
        self._default_burst = default_burst
        self._buckets: Dict[str, _Bucket] = {}
        self._overrides: Dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def set_limit(
        self,
        domain: str,
        *,
        rate_per_sec: float,
        burst: float | None = None,
    ) -> None:
        burst = burst if burst is not None else max(1.0, rate_per_sec)
        self._overrides[domain.lower()] = (rate_per_sec, burst)

    def acquire(self, url_or_domain: str) -> None:
        domain = self._extract_domain(url_or_domain)

        while True:
            with self._lock:
                bucket = self._get_or_create_bucket(domain)
                self._refill(bucket)

                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return

                needed = 1.0 - bucket.tokens
                wait = needed / bucket.refill_per_sec

            logger.debug("rate_limiter: %s sleeping %.2fs", domain, wait)
            time.sleep(wait)

    @staticmethod
    def _extract_domain(url_or_domain: str) -> str:
        if "://" in url_or_domain:
            return (urlparse(url_or_domain).hostname or "").lower()
        return url_or_domain.lower()

    def _get_or_create_bucket(self, domain: str) -> _Bucket:
        bucket = self._buckets.get(domain)
        if bucket is not None:
            return bucket

        rate, burst = self._overrides.get(
            domain, (self._default_rate, self._default_burst)
        )
        bucket = _Bucket(
            capacity=burst,
            refill_per_sec=rate,
            tokens=burst,
            last_refill=time.monotonic(),
        )
        self._buckets[domain] = bucket
        return bucket

    @staticmethod
    def _refill(bucket: _Bucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(
            bucket.capacity,
            bucket.tokens + elapsed * bucket.refill_per_sec,
        )
        bucket.last_refill = now


shared_limiter = RateLimiter(default_rate_per_sec=1.0, default_burst=2.0)
shared_limiter.set_limit("futurepedia.com", rate_per_sec=0.5, burst=2)
shared_limiter.set_limit("www.futurepedia.io", rate_per_sec=0.5, burst=2)
shared_limiter.set_limit("tldr.tech", rate_per_sec=0.5, burst=2)
shared_limiter.set_limit("bensbites.com", rate_per_sec=0.5, burst=2)
shared_limiter.set_limit("www.therundown.ai", rate_per_sec=0.5, burst=2)
