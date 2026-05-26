from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, Tuple, Type

from app.services.http_client import (
    HttpTimeoutError,
    HttpServerError,
    HttpConnectionError,
)

logger = logging.getLogger(__name__)

DEFAULT_RETRYABLE: Tuple[Type[BaseException], ...] = (
    HttpTimeoutError,
    HttpServerError,
    HttpConnectionError,
)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: Tuple[Type[BaseException], ...] = DEFAULT_RETRYABLE,
):
    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: BaseException | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except retryable as exc:
                    last_exc = exc

                    if attempt >= max_attempts:
                        logger.warning(
                            "retry: %s failed after %d attempts (%s)",
                            func.__name__, attempt, exc,
                        )
                        raise

                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    jitter = delay * 0.25 * (2 * random.random() - 1)
                    sleep_for = max(0.0, delay + jitter)

                    logger.info(
                        "retry: %s attempt %d/%d failed (%s); sleeping %.2fs",
                        func.__name__, attempt, max_attempts, exc, sleep_for,
                    )
                    time.sleep(sleep_for)

            if last_exc is not None:
                raise last_exc
            raise RuntimeError("retry: exited loop without result or exception")

        return wrapper

    return decorator
