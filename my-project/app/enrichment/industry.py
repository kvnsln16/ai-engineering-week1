from __future__ import annotations

import re
from typing import Iterable


INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "llm": [
        "gpt", "claude", "llama", "mistral", "gemini",
        "llm", "language model", "transformer", "prompt",
        "chatbot", "rag", "fine-tune", "fine-tuning", "instruct",
        "tokens", "context window", "embedding",
    ],
    "computer_vision": [
        "vision", "image", "video", "segmentation", "detection",
        "diffusion", "midjourney", "stable diffusion", "dall-e",
        "sora", "generative image", "image generation",
        "object detection", "facial recognition",
    ],
    "robotics": [
        "robot", "robotics", "autonomous", "drone", "manipulation",
        "embodied", "humanoid", "boston dynamics",
        "self-driving", "waymo", "tesla autopilot",
    ],
    "audio_speech": [
        "speech", "voice", "audio", "whisper", "tts", "asr",
        "text-to-speech", "speech-to-text", "elevenlabs",
        "music generation", "suno",
    ],
    "research": [
        "paper", "arxiv", "benchmark", "sota", "state-of-the-art",
        "evaluation", "study", "researchers", "publication",
        "preprint", "neurips", "icml", "iclr", "acl",
    ],
    "funding": [
        "series a", "series b", "series c", "raised", "funding",
        "valuation", "acquired", "acquisition", "ipo",
        "venture", "investors", "round", "million", "billion",
    ],
    "product_launch": [
        "launches", "launched", "releases", "released",
        "ships", "shipped", "announces", "announced",
        "available", "public beta", "general availability",
        "rollout", "now live",
    ],
    "policy_safety": [
        "regulation", "regulatory", "policy", "safety",
        "alignment", "eu ai act", "executive order",
        "compliance", "governance", "ethics", "bias",
        "ban", "lawsuit", "copyright",
    ],
}

DEFAULT_INDUSTRY = "other"


_compiled: dict[str, list[re.Pattern]] = {
    industry: [
        re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE)
        for kw in keywords
    ]
    for industry, keywords in INDUSTRY_KEYWORDS.items()
}


def detect(text: str) -> tuple[str, list[str]]:
    if not text or not text.strip():
        return (DEFAULT_INDUSTRY, [])

    scores: dict[str, int] = {}
    for industry, patterns in _compiled.items():
        hits = sum(1 for p in patterns if p.search(text))
        if hits > 0:
            scores[industry] = hits

    if not scores:
        return (DEFAULT_INDUSTRY, [])

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    primary = ranked[0][0]
    secondary = [name for name, _ in ranked[1:]]
    return (primary, secondary)


def detect_many(texts: Iterable[str]) -> list[tuple[str, list[str]]]:
    return [detect(t) for t in texts]
