from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = 1.0


def fetch_trends(
    keyword: str,
    *,
    timeframe: str = "today 12-m",
) -> Optional[list[int]]:
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("google_trends: pytrends not installed — skipping")
        return None

    try:
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(5, 15))
        pytrends.build_payload(
            kw_list=[keyword],
            timeframe=timeframe,
            geo="",
        )
        df = pytrends.interest_over_time()

        if df is None or df.empty:
            logger.warning("google_trends: no data returned for %r", keyword)
            return None

        if keyword not in df.columns:
            logger.warning(
                "google_trends: response missing column for %r (got %s)",
                keyword, list(df.columns),
            )
            return None

        values = df[keyword].tolist()
        return [int(v) for v in values]

    except Exception as exc:
        logger.warning(
            "google_trends: fetch failed for %r: %s — skipping",
            keyword, type(exc).__name__,
        )
        return None


def fetch_multiple(
    keywords: list[str],
    *,
    timeframe: str = "today 12-m",
) -> dict[str, list[int]]:
    import time

    results: dict[str, list[int]] = {}
    for i, kw in enumerate(keywords):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        series = fetch_trends(kw, timeframe=timeframe)
        if series is not None:
            results[kw] = series
            logger.info("google_trends: got %d points for %r", len(series), kw)

    return results
