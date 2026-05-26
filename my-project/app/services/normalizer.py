from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_record(
    *,
    source: str,
    source_url: str,
    title: str,
    url: str,
    summary: str = "",
    author: str | None = None,
    published_at: str | None = None,
    tags: Iterable[str] | None = None,
    raw: dict | None = None,
) -> dict[str, Any]:
    return {
        "source":       source,
        "source_url":   source_url,
        "title":        _clean_text(title),
        "url":          url.strip(),
        "author":       _clean_text(author) if author else None,
        "published_at": _parse_date(published_at),
        "summary":      _strip_html(summary),
        "tags":         list(tags) if tags else [],
        "raw":          raw or {},
    }


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    return _clean_text(no_tags)


def _parse_date(raw: str | None) -> str | None:
    if not raw:
        return None

    raw = raw.strip()

    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return _to_iso_utc(dt)
    except (TypeError, ValueError):
        pass

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
        return _to_iso_utc(dt)
    except ValueError:
        pass

    logger.debug("normalizer: could not parse date %r", raw)
    return None


def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
