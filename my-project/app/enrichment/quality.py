from __future__ import annotations


SOURCE_QUALITY: dict[str, float] = {
    "github":        0.90,
    "hackernews":    0.85,
    "producthunt":   0.75,
    "reddit":        0.70,
    "ai_news":       0.65,
    "tldr_ai":       0.80,
    "bens_bites":    0.80,
    "the_rundown":   0.75,
    "futurepedia":   0.60,
}

DEFAULT_QUALITY = 0.5


def score_for(source: str) -> float:
    return SOURCE_QUALITY.get(source.lower(), DEFAULT_QUALITY)
