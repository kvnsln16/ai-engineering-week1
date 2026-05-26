from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


_analyzer = SentimentIntensityAnalyzer()

POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05


def analyze(text: str) -> tuple[str, float]:
    if not text or not text.strip():
        return ("neutral", 0.0)

    scores = _analyzer.polarity_scores(text)
    compound = float(scores["compound"])

    if compound >= POSITIVE_THRESHOLD:
        label = "positive"
    elif compound <= NEGATIVE_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"

    return (label, compound)
