"""Practice questions grouped by interview topic."""

from __future__ import annotations

import random

CATEGORIES = ("Python", "Django", "REST APIs", "SQL", "Behavioral", "Resume")

QUESTIONS: dict[str, tuple[str, ...]] = {
    "Python": (
        "What is the difference between a list and a tuple?",
        "How does a Python decorator work?",
        "When would you use a generator instead of a list?",
        "How do you handle exceptions in production Python code?",
    ),
    "Django": (
        "What is Django REST Framework?",
        "How do serializers work?",
        "How do you validate nested data in a serializer?",
        "How do Django migrations work?",
    ),
    "REST APIs": (
        "How do you design a REST endpoint for creating and listing resources?",
        "What is the difference between authentication and authorization?",
        "How do you version an API?",
        "How would you debug a slow API endpoint?",
    ),
    "SQL": (
        "What is the difference between an inner join and a left join?",
        "How do you find a slow query in PostgreSQL?",
        "When would you add an index?",
        "How do you avoid N+1 queries?",
    ),
    "Behavioral": (
        "Tell me about a technical challenge you solved.",
        "Tell me about a time you disagreed with a teammate.",
        "Describe a bug you found in production.",
        "How do you prioritize work when deadlines conflict?",
    ),
    "Resume": (
        "Walk me through a project on your resume.",
        "Which part of that project did you personally implement?",
        "What would you improve if you rebuilt that project?",
        "Which skills on your resume have you used most recently?",
    ),
}


def next_question(category: str, seen: set[str] | None = None) -> str:
    """Return a question from the category, avoiding ones already shown."""
    pool = QUESTIONS.get(category) or QUESTIONS["Python"]
    used = seen if seen is not None else set()
    remaining = [question for question in pool if question not in used]
    if not remaining:
        used.clear()
        remaining = list(pool)
    choice = random.choice(remaining)
    used.add(choice)
    return choice
