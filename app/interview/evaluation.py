"""Coach feedback for an answer the candidate wrote first."""


def build_evaluation_prompt(question: str, candidate_answer: str, context: str = "") -> str:
    evidence = f"\nVerified context:\n{context.strip()}\n" if context.strip() else "\nNo verified personal context was retrieved.\n"
    return (
        "You are an interview coach. The candidate answered before seeing a suggested answer. "
        "Give honest feedback on clarity, completeness, and technical depth. "
        "Do not invent projects, metrics, or experience. "
        "If the answer claims personal work that is not in the verified context, say that it is unsupported. "
        "Keep the feedback to a short paragraph plus up to four bullet points.\n"
        f"{evidence}\nQuestion:\n{question.strip()}\n\nCandidate answer:\n{candidate_answer.strip()}\n\nFeedback:"
    )
