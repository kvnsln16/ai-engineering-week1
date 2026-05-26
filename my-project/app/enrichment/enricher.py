from __future__ import annotations

import logging
import time
from typing import Any

from app import db
from app.enrichment import industry, quality, sentiment, topics

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def enrich_new_signals(*, max_signals: int | None = None) -> dict[str, Any]:
    started = time.monotonic()
    total_processed = 0
    total_errors = 0
    batches_run = 0

    while True:
        if max_signals is not None:
            remaining = max_signals - total_processed
            if remaining <= 0:
                break
            fetch_n = min(BATCH_SIZE, remaining)
        else:
            fetch_n = BATCH_SIZE

        batch = db.signals_needing_enrichment(limit=fetch_n)
        if not batch:
            break

        processed, errors = _enrich_batch(batch)
        total_processed += processed
        total_errors += errors
        batches_run += 1

    elapsed = time.monotonic() - started

    summary = {
        "processed": total_processed,
        "errors": total_errors,
        "batches": batches_run,
        "duration_seconds": round(elapsed, 2),
        "signals_per_second": (
            round(total_processed / elapsed, 1) if elapsed > 0 else 0
        ),
    }

    if total_processed > 0:
        logger.info(
            "enricher: enriched %d signals in %.2fs (%.1f signals/sec, %d errors)",
            total_processed, elapsed,
            summary["signals_per_second"], total_errors,
        )
    else:
        logger.info("enricher: no signals needed enrichment")

    return summary


def _enrich_batch(batch: list[dict[str, Any]]) -> tuple[int, int]:
    processed = 0
    errors = 0

    texts = [_text_for_analysis(s) for s in batch]

    try:
        embeddings = topics.encode_batch(texts)
    except Exception as exc:
        logger.exception("enricher: embedding batch failed: %s", exc)
        embeddings = [b""] * len(batch)
        errors += len(batch)

    for signal_row, text, embedding in zip(batch, texts, embeddings):
        try:
            keywords = topics.extract_keywords(text)
            label = topics.label_from_keywords(keywords)

            sent_label, sent_score = sentiment.analyze(text)
            qual = quality.score_for(signal_row.get("source", ""))
            primary_industry, secondary = industry.detect(text)

            db.save_enrichment(
                signal_id=signal_row["id"],
                topic_label=label,
                topic_keywords=keywords,
                topic_embedding=embedding,
                sentiment_label=sent_label,
                sentiment_score=sent_score,
                source_quality=qual,
                industry=primary_industry,
                industry_secondary=secondary,
            )
            processed += 1

        except Exception as exc:
            logger.exception(
                "enricher: signal %s failed: %s",
                signal_row.get("id"), exc,
            )
            errors += 1

    return processed, errors


def _text_for_analysis(signal_row: dict[str, Any]) -> str:
    title = (signal_row.get("title") or "").strip()
    summary = (signal_row.get("summary") or "").strip()

    if title and summary:
        return f"{title}. {summary}"
    return title or summary or ""
