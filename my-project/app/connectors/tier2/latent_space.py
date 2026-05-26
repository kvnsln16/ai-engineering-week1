from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.tier2._rss import parse_feed
from app.services.normalizer import normalize_record


class LatentSpaceConnector(BaseConnector):
    name = "latent_space"
    source_url = "https://www.latent.space/feed"

    def parse(self, raw: bytes) -> list[dict[str, Any]]:
        items = parse_feed(raw)
        return [
            normalize_record(
                source=self.name,
                source_url=self.source_url,
                title=item.get("title", ""),
                url=item.get("link", ""),
                summary=item.get("summary", ""),
                author=item.get("author") or "Latent Space",
                published_at=item.get("published"),
                tags=item.get("tags") or ["newsletter", "ai", "engineering"],
                raw=item,
            )
            for item in items
            if item.get("title") and item.get("link")
        ]
