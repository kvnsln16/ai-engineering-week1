from __future__ import annotations

import random
from typing import Any


def magnitude_bucket(relative_change: float) -> str:
    abs_change = abs(relative_change)
    if abs_change < 0.10:
        return "stable"
    if abs_change < 0.25:
        return "small"
    if abs_change < 0.75:
        return "moderate"
    return "large"


TEXT_TEMPLATES: dict[tuple[str, str], list[str]] = {
    ("growth", "small"): [
        "{topic} shows modest growth signals over the {horizon_text}.",
        "Coverage of {topic} ticks upward through the {horizon_text}.",
        "{topic} maintains gradual upward momentum in the {horizon_text}.",
    ],
    ("growth", "moderate"): [
        "{topic} continues gaining traction across the {horizon_text}.",
        "Sustained interest in {topic} is expected through the {horizon_text}.",
        "Coverage of {topic} is on track to expand noticeably over the {horizon_text}.",
    ],
    ("growth", "large"): [
        "{topic} is accelerating sharply over the {horizon_text}.",
        "Significant momentum behind {topic} is expected through the {horizon_text}.",
        "{topic} appears poised for substantial growth in the {horizon_text}.",
    ],

    ("decline", "small"): [
        "Interest in {topic} is cooling slightly across the {horizon_text}.",
        "{topic} shows minor decline indicators over the {horizon_text}.",
        "Coverage of {topic} drifts downward through the {horizon_text}.",
    ],
    ("decline", "moderate"): [
        "{topic} is losing momentum noticeably over the {horizon_text}.",
        "A meaningful cooldown in {topic} is expected through the {horizon_text}.",
        "Coverage of {topic} is on track to contract across the {horizon_text}.",
    ],
    ("decline", "large"): [
        "{topic} faces substantial decline indicators over the {horizon_text}.",
        "Sharp contraction in {topic} interest is expected through the {horizon_text}.",
        "{topic} appears to be entering a significant retreat across the {horizon_text}.",
    ],

    ("stable", "stable"): [
        "{topic} appears stable through the {horizon_text}.",
        "Steady coverage of {topic} is expected over the {horizon_text}.",
        "No major change predicted for {topic} across the {horizon_text}.",
    ],
}


HORIZON_TEXT = {
    30:  "next 30 days",
    90:  "next 3 months",
    180: "next 6 months",
    365: "next 12 months",
}


ACTION_RULES: dict[tuple[str, str], str] = {
    ("llm", "growth"):    "Consider investing in LLM developer tools, content, or training programs.",
    ("llm", "decline"):   "Diversify away from heavy single-vendor LLM dependencies.",
    ("llm", "stable"):    "Maintain current LLM positioning and monitor for sudden shifts.",

    ("computer_vision", "growth"):  "Explore CV-driven product opportunities or integrations.",
    ("computer_vision", "decline"): "Reassess CV-heavy roadmap items for relevance.",
    ("computer_vision", "stable"):  "Hold current CV initiatives steady.",

    ("robotics", "growth"):  "Track key robotics players for partnership or acquisition signals.",
    ("robotics", "decline"): "Pause major robotics commitments pending market clarity.",
    ("robotics", "stable"):  "Continue measured engagement with robotics ecosystem.",

    ("audio_speech", "growth"):  "Evaluate speech-AI integration opportunities in current products.",
    ("audio_speech", "decline"): "Defer non-essential audio-AI investments.",
    ("audio_speech", "stable"):  "Maintain existing audio-AI capabilities without expansion.",

    ("research", "growth"):  "Increase research-monitoring resources; emerging breakthroughs likely.",
    ("research", "decline"): "Reduce horizon-scanning effort in this area for now.",
    ("research", "stable"):  "Continue baseline research-tracking activities.",

    ("funding", "growth"):  "Track new deals; evaluate strategic investment or partnership opportunities.",
    ("funding", "decline"): "Reassess valuations of existing positions in this segment.",
    ("funding", "stable"):  "Hold current funding-related positions.",

    ("product_launch", "growth"):  "Monitor launches for competitive threats and partnership openings.",
    ("product_launch", "decline"): "Slow follower-strategy; lead-launch opportunity reduced.",
    ("product_launch", "stable"):  "Continue routine product-launch monitoring.",

    ("policy_safety", "growth"):  "Prepare for upcoming regulatory changes; consult legal/compliance.",
    ("policy_safety", "decline"): "Regulatory pressure easing; existing compliance posture sufficient.",
    ("policy_safety", "stable"):  "Maintain current compliance monitoring cadence.",

    ("other", "growth"):  "Investigate this trend for relevance to current strategy.",
    ("other", "decline"): "De-prioritize attention here; signal weakening.",
    ("other", "stable"):  "No action required; trend appears steady.",
}


ACTION_DISCLAIMER = " (Heuristic suggestion only — not financial or legal advice.)"


def render_text(
    *,
    direction: str,
    magnitude: str,
    cluster_keywords: list[str],
    cluster_label: str,
    horizon_days: int,
    seed_key: str,
) -> str:
    candidates = TEXT_TEMPLATES.get(
        (direction, magnitude),
        TEXT_TEMPLATES[("stable", "stable")],
    )

    chosen = candidates[hash(seed_key) % len(candidates)]

    topic = _topic_phrase(cluster_keywords, cluster_label)
    horizon_text = HORIZON_TEXT.get(horizon_days, f"next {horizon_days} days")

    return chosen.format(
        topic=topic,
        horizon=horizon_days,
        horizon_text=horizon_text,
    )


def render_action(industry: str | None, direction: str) -> str | None:
    if direction == "stable":
        pass

    industry_key = (industry or "other").lower()
    action = ACTION_RULES.get((industry_key, direction))

    if action is None:
        action = ACTION_RULES.get(("other", direction))

    if action is None:
        return None

    return action + ACTION_DISCLAIMER


def _topic_phrase(keywords: list[str], fallback_label: str) -> str:
    if keywords:
        cleaned = [str(k).strip() for k in keywords[:3] if k]
        if cleaned:
            return ", ".join(c.title() for c in cleaned)
    if fallback_label:
        return fallback_label
    return "this topic"
