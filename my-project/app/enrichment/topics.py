from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

SPACY_MODEL_NAME = "en_core_web_sm"
SBERT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

EMBED_BATCH_SIZE = 32


_nlp = None
_encoder = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        logger.info("topics: loading spaCy model %s", SPACY_MODEL_NAME)
        _nlp = spacy.load(
            SPACY_MODEL_NAME,
            disable=["parser", "lemmatizer", "attribute_ruler"],
        )
    return _nlp


def _get_encoder():
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer
        logger.info("topics: loading sentence-transformer %s", SBERT_MODEL_NAME)
        _encoder = SentenceTransformer(SBERT_MODEL_NAME)
    return _encoder


KEEP_ENTITY_TYPES = {
    "ORG",
    "PRODUCT",
    "PERSON",
    "WORK_OF_ART",
    "EVENT",
    "GPE",
}

STOP_KEYWORDS = {
    "ai", "ml", "model", "models", "new", "today", "week", "year",
    "team", "company", "user", "users", "data", "system",
    "tldr", "rundown", "newsletter", "bites",
}


def extract_keywords(text: str, *, max_keywords: int = 8) -> list[str]:
    if not text or not text.strip():
        return []

    nlp = _get_nlp()
    doc = nlp(text)

    keywords: list[str] = []
    seen: set[str] = set()

    for ent in doc.ents:
        if ent.label_ not in KEEP_ENTITY_TYPES:
            continue
        term = ent.text.strip().lower()
        if _is_useless(term, seen):
            continue
        keywords.append(term)
        seen.add(term)
        if len(keywords) >= max_keywords:
            return keywords

    for token in doc:
        if token.pos_ not in {"PROPN", "NOUN"}:
            continue
        term = token.text.strip().lower()
        if _is_useless(term, seen):
            continue
        keywords.append(term)
        seen.add(term)
        if len(keywords) >= max_keywords:
            return keywords

    return keywords


def _is_useless(term: str, already_seen: set[str]) -> bool:
    if not term or len(term) < 2:
        return True
    if term in already_seen:
        return True
    if term in STOP_KEYWORDS:
        return True
    return False


def label_from_keywords(keywords: list[str]) -> str:
    if not keywords:
        return "untagged"
    return ", ".join(keywords[:3]).title()


def encode_batch(texts: list[str]) -> list[bytes]:
    if not texts:
        return []

    safe_texts = [t if (t and t.strip()) else " " for t in texts]

    encoder = _get_encoder()
    vectors: np.ndarray = encoder.encode(
        safe_texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    vectors = vectors.astype(np.float32, copy=False)
    return [row.tobytes() for row in vectors]


def decode_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
