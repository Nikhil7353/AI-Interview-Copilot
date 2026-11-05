"""Hybrid Retrieval: semantic pgvector search + keyword overlap + verified profile & project architecture grounding."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.knowledge.store import KnowledgeStore, query_terms


@dataclass
class RetrievedItem:
    source: str          # document filename or "Candidate profile"
    source_ref: str | None
    text: str
    score: float
    is_profile: bool = False
    status: str = "document"


@dataclass
class RetrievalResult:
    items: list[RetrievedItem] = field(default_factory=list)
    verified_items: list[RetrievedItem] = field(default_factory=list)
    needs_review_items: list[RetrievedItem] = field(default_factory=list)
    has_evidence: bool = False


TOPIC_KEYWORDS = {
    "python": ["python", "django", "flask", "fastapi", "pip", "virtualenv", "pytest", "celery", "decorator", "generator"],
    "django": ["django", "orm", "migration", "model", "view", "template", "rest framework", "drf", "serializer", "channels", "websocket"],
    "rest": ["rest", "api", "endpoint", "json", "http", "serializer", "request", "response", "pagination", "cursor", "webhook"],
    "sql": ["sql", "postgresql", "database", "query", "index", "join", "migration", "schema", "n+1", "select_related", "prefetch_related"],
    "auth": ["auth", "login", "jwt", "oauth", "otp", "password", "permission", "session", "token", "tenant", "workspace", "role"],
    "git": ["git", "github", "branch", "commit", "merge", "pull request", "version control", "ci/cd", "docker"],
    "architecture": ["architecture", "design", "system", "flow", "scale", "scalability", "component", "layer", "redis", "celery", "background"],
    "behavioral": ["team", "conflict", "challenge", "failure", "success", "leadership", "project", "difficult", "bug", "production", "deadline"],
    "resume": [
        "resume", "experience", "employment", "work history", "achievement", "yourself",
        "background", "introduce", "walk me through", "built", "role", "company", "skills",
        "tech stack", "kyc", "ocr", "billing", "gst", "razorpay", "trade", "advisory", "signal",
    ],
}


def _topic_terms(question: str) -> list[str]:
    q = question.lower()
    found: set[str] = set()
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                found.add(topic)
    return list(found)


def _is_broad_personal_or_project_question(question: str, topic_terms: list[str]) -> bool:
    q = question.lower()
    if "resume" in topic_terms or "behavioral" in topic_terms or "architecture" in topic_terms:
        return True
    broad_phrases = (
        "tell me about",
        "walk me through",
        "introduce yourself",
        "your project",
        "your experience",
        "your role",
        "what did you build",
        "how did you build",
        "architecture",
        "tech stack",
    )
    return any(p in q for p in broad_phrases)


def retrieve(
    store: KnowledgeStore,
    question: str,
    limit_chunks: int = 6,
    limit_facts: int = 8,
) -> RetrievalResult:
    """Retrieve relevant verified profile facts, project architecture briefs, and code/document chunks."""
    result = RetrievalResult()

    terms = query_terms(question)
    topic_terms = _topic_terms(question)
    is_broad = _is_broad_personal_or_project_question(question, topic_terms)

    # 1. Score and attach Candidate Profile facts (Verified vs. Held-back Needs Review)
    scored_facts: list[tuple[float, dict]] = []
    for fact in store.list_profile_facts():
        fact_text = fact["fact"].lower()
        cat = (fact.get("category") or "").lower()
        score = sum(0.8 for term in terms if term in fact_text)
        for topic in topic_terms:
            for keyword in TOPIC_KEYWORDS.get(topic, []):
                if keyword in fact_text:
                    score += 0.35
        # Always include candidate identity, summary, projects, experience, and skills
        if cat == "identity":
            score = max(score, 3.0)
        elif is_broad and cat in ("summary", "projects", "experience", "skills"):
            score = max(score, 2.5 if cat in ("summary", "projects") else 2.0)
        if score > 0:
            scored_facts.append((score, fact))

    scored_facts.sort(key=lambda item: item[0], reverse=True)
    for score, fact in scored_facts[:limit_facts]:
        status = (fact.get("status") or "needs_review").lower()
        item = RetrievedItem(
            source="Candidate profile",
            source_ref=fact.get("category"),
            text=fact["fact"],
            score=round(score, 2),
            is_profile=True,
            status=status,
        )
        if status == "verified":
            result.items.append(item)
            result.verified_items.append(item)
        else:
            result.needs_review_items.append(item)

    # 2. Search document & codebase chunks (pgvector cosine similarity + keyword ranking)
    chunks = store.search_chunks(question, limit=limit_chunks * 2)
    seen_chunk_ids: set[int | None] = set()
    per_file_count: dict[str, int] = {}

    for chunk in chunks:
        fname = chunk.get("filename") or "document"
        # Cap at 2 chunks per individual file so one long file doesn't crowd out other sources
        if per_file_count.get(fname, 0) >= 2:
            continue
        seen_chunk_ids.add(chunk.get("id"))
        per_file_count[fname] = per_file_count.get(fname, 0) + 1

        chunk_lower = chunk["text"].lower()
        overlap = sum(1 for term in terms if term in chunk_lower)
        filename_match = sum(1.2 for term in terms if term in fname.lower())
        sim = float(chunk.get("similarity") or 0.0)
        base_score = max(float(overlap) + filename_match, round(sim * 5.0, 2))
        if base_score <= 0:
            base_score = 1.0
        if chunk.get("file_type") == "project_brief":
            base_score += 0.8

        result.items.append(
            RetrievedItem(
                source=fname,
                source_ref=chunk.get("source_ref"),
                text=chunk["text"],
                score=round(base_score, 2),
                is_profile=False,
                status="document",
            )
        )
        if len([i for i in result.items if not i.is_profile]) >= limit_chunks:
            break

    # 3. Attach Project Brief / AI Architecture Dossier as foundational project context
    q_lower = question.lower()
    for document in store.list_documents():
        if document.file_type != "project_brief" or document.status != "indexed" or document.id is None:
            continue
        p_name = str((document.metadata or {}).get("project_name") or "").lower()
        for chunk in store.get_chunks_for_document(document.id):
            if chunk.id in seen_chunk_ids:
                continue
            overlap = sum(1 for term in terms if term in chunk.text.lower())
            p_boost = 2.0 if p_name and (p_name in q_lower or any(part in q_lower for part in p_name.split() if len(part) > 3)) else 0.0
            result.items.append(
                RetrievedItem(
                    source=document.filename,
                    source_ref=chunk.source_ref,
                    text=chunk.text,
                    score=round(1.5 + float(overlap) + p_boost, 2),
                    is_profile=False,
                    status="document",
                )
            )
            seen_chunk_ids.add(chunk.id)
            break

    result.items.sort(key=lambda item: item.score, reverse=True)
    result.has_evidence = bool(result.items)
    return result


def build_context_string(result: RetrievalResult, max_chars: int = 3800) -> str:
    """Build a compact context string for the AI prompt, citing sources."""
    if not result.items:
        return ""

    parts: list[str] = []
    total = 0
    for item in result.items:
        kind = "verified profile" if item.status == "verified" else "document excerpt"
        ref = f" ({item.source_ref})" if item.source_ref else ""
        entry = f"[{item.source}{ref} · {kind}] {item.text.strip()}"
        if total + len(entry) > max_chars:
            remaining = max_chars - total
            if remaining > 280:
                parts.append(entry[:remaining].rstrip() + "…")
            break
        parts.append(entry)
        total += len(entry)

    if not parts:
        return ""
    return "\n".join(parts)
