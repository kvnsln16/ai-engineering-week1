from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.tier2._rss import parse_feed
from app.services.normalizer import normalize_record


class BensBitesConnector(BaseConnector):
    name = "bens_bites"
    source_url = "https://www.bensbites.com/feed"

    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        items = parse_feed(raw)
        return [
            normalize_record(
                source=self.name,
                source_url=self.source_url,
                title=item.get("title", ""),
                url=item.get("link", ""),
                summary=item.get("summary", ""),
                author=item.get("author") or "Ben's Bites",
                published_at=item.get("published"),
                tags=item.get("tags") or ["newsletter", "ai"],
                raw=item,
            )
            for item in items
            if item.get("title") and item.get("link")
        ]
