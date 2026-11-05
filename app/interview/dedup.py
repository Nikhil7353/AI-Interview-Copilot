"""Avoid answering the same question twice in one session."""

from __future__ import annotations

import re


def normalize_question(question: str) -> str:
    text = question.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip("?.! ")


def is_duplicate(question: str, previous: list[str]) -> bool:
    key = normalize_question(question)
    if not key:
        return False
    return key in {normalize_question(item) for item in previous}
