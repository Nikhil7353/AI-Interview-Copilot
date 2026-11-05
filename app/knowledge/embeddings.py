"""Local semantic search through Ollama's all-minilm model (384 dimensions)."""

from __future__ import annotations

import json
import math

from app.ai.providers import ProviderError, _post_json

EMBED_MODEL = "all-minilm"
EMBED_DIMENSIONS = 384
MIN_SIMILARITY = 0.30


_EMBED_MISSING = False


def embed_texts(texts: list[str], ollama_url: str = "http://localhost:11434") -> list[list[float]] | None:
    """Return one 384-d vector per text, or None if the embedding model is unavailable."""
    global _EMBED_MISSING
    if _EMBED_MISSING:
        return None
    cleaned = [text.strip()[:2000] for text in texts if text and text.strip()]
    if not cleaned:
        return None
    try:
        result = _post_json(
            f"{ollama_url.rstrip('/')}/api/embed",
            {"model": EMBED_MODEL, "input": cleaned},
            timeout=45,
        )
    except ProviderError as exc:
        message = str(exc).lower()
        if "not found" in message or "404" in message or "try pulling" in message:
            _EMBED_MISSING = True
        return None
    vectors = result.get("embeddings") or []
    if len(vectors) != len(cleaned):
        return None
    if any(len(vector) != EMBED_DIMENSIONS for vector in vectors):
        return None
    return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def parse_vector(raw) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        values = raw
    else:
        text = str(raw).strip()
        if text.startswith("[") and not text.startswith("[["):
            try:
                values = json.loads(text)
            except json.JSONDecodeError:
                return None
        else:
            return None
    if len(values) != EMBED_DIMENSIONS:
        return None
    return [float(value) for value in values]
