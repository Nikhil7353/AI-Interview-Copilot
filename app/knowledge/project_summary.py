"""Static summary of indexed project files. Does not execute repository code."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.knowledge.ingestion import is_forbidden, scan_directory

LANGUAGE_BY_SUFFIX = {
    "py": "Python",
    "js": "JavaScript",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "jsx": "JavaScript",
    "sql": "SQL",
    "java": "Java",
    "cs": "C#",
    "go": "Go",
    "rs": "Rust",
    "html": "HTML",
    "css": "CSS",
    "md": "Markdown",
    "markdown": "Markdown",
    "json": "JSON",
}

FRAMEWORK_MARKERS = (
    ("django", "Django"),
    ("rest_framework", "Django REST Framework"),
    ("fastapi", "FastAPI"),
    ("flask", "Flask"),
    ("react", "React"),
    ("pytest", "pytest"),
    ("postgresql", "PostgreSQL"),
    ("psycopg", "PostgreSQL"),
)


def summarize_indexed_files(filenames: list[str], sample_text: str = "") -> str:
    """Describe languages and frameworks found in indexed filenames and a text sample."""
    if not filenames and not sample_text:
        return "No indexed project files yet."
    languages: list[str] = []
    for name in filenames:
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        language = LANGUAGE_BY_SUFFIX.get(suffix)
        if language and language not in languages:
            languages.append(language)
    haystack = f"{' '.join(filenames)}\n{sample_text}".lower()
    frameworks = [label for marker, label in FRAMEWORK_MARKERS if marker in haystack and label not in languages]
    # frameworks list may duplicate labels
    seen: list[str] = []
    for label in frameworks:
        if label not in seen:
            seen.append(label)
    parts = [f"{len(filenames)} indexed file(s)"]
    if languages:
        parts.append("Languages: " + ", ".join(languages))
    if seen:
        parts.append("Detected: " + ", ".join(seen))
    return " · ".join(parts)


def _read_limited(path: Path, limit: int = 900) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except OSError:
        return ""


def analyze_project_folder(root: str | Path) -> str:
    """Describe a project from its files. The code is read, never executed."""
    root_path = Path(root)
    files = scan_directory(root_path, max_files=500)
    relative = []
    for path in files:
        try:
            relative.append(str(path.relative_to(root_path)).replace("\\", "/"))
        except ValueError:
            relative.append(path.name)
    lines = [f"Project folder: {root_path.name}", summarize_indexed_files(relative)]
    try:
        names = [child.name for child in root_path.iterdir() if not is_forbidden(child)][:24]
    except OSError:
        names = []
    if names:
        lines.append("Top level: " + ", ".join(names))
    for readme_name in ("README.md", "README.txt", "readme.md", "Readme.md"):
        readme = root_path / readme_name
        if readme.is_file():
            text = _read_limited(readme, 900)
            if text:
                lines.append("README:\n" + text)
            break
    requirements = root_path / "requirements.txt"
    if requirements.is_file():
        packages = []
        for line in _read_limited(requirements, 4000).splitlines():
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                packages.append(cleaned.split("==")[0].split(">=")[0].strip())
        if packages:
            lines.append("Python packages: " + ", ".join(packages[:25]))
    package_json = root_path / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            deps = list((data.get("dependencies") or {}).keys())[:20]
            bits = [str(data.get("name") or "package")]
            if data.get("description"):
                bits.append(str(data["description"]))
            if deps:
                bits.append("Dependencies: " + ", ".join(deps))
            lines.append("npm: " + ". ".join(bits))
    notable = [
        name for name in relative
        if name.rsplit("/", 1)[-1].lower() in {
            "manage.py", "main.py", "app.py", "models.py", "views.py", "urls.py",
            "settings.py", "serializers.py", "package.json", "requirements.txt",
            "tasks.py", "consumers.py", "services.py", "routes.py",
        }
    ][:24]
    if notable:
        lines.append("Important files: " + ", ".join(notable))
    snippets = []
    for path in files:
        if path.name.lower() not in {"models.py", "views.py", "urls.py", "main.py", "app.py", "serializers.py", "tasks.py"}:
            continue
        body = _read_limited(path, 400)
        if body:
            try:
                rel = str(path.relative_to(root_path)).replace("\\", "/")
            except ValueError:
                rel = path.name
            snippets.append(f"{rel}:\n{body}")
        if len(snippets) >= 6:
            break
    if snippets:
        lines.append("Code notes:\n" + "\n\n".join(snippets))
    return "\n".join(lines).strip()[:3200]


def build_project_analysis_prompt(structural_summary: str, project_title: str = "Project") -> str:
    """Prompt for Groq / OpenRouter / Ollama to synthesize a grounded interview architecture dossier."""
    return (
        f"You are a principal software architect preparing a candidate for a deep-dive technical interview on their codebase: '{project_title}'.\n"
        "CRITICAL RULES:\n"
        "- Use ONLY the exact frameworks, libraries, database tables, and filenames shown in the Verified Profile & Project Summary below.\n"
        "- NEVER invent or hallucinate libraries, filenames, or cloud services that are not in the summary.\n"
        "- Speak in natural first-person ('I built...', 'In our backend...').\n\n"
        f"Write a concise, high-signal Project Architecture Dossier for '{project_title}' structured into these 4 sections:\n"
        f"1. 30-SECOND ELEVATOR PITCH (First-person spoken summary of {project_title} and its exact tech stack)\n"
        "2. CORE ARCHITECTURE & DATA FLOW (How requests flow end-to-end through routes, controllers/views, models/database, and async workers/queues)\n"
        "3. KEY ENGINEERING CHALLENGES SOLVED (Specific implementation details and edge cases from the actual files in this project)\n"
        "4. TOP 5 INTERVIEWER DEEP-DIVE QUESTIONS & SPOKEN ANSWERS (Question + 2-3 sentence first-person answer citing real files from this project)\n\n"
        f"Verified Profile & Project Summary:\n{structural_summary[:5500]}\n\n"
        f"Project Architecture Dossier for {project_title}:"
    )


def summarize_store_for_ai_analysis(
    store,
    project_title: str = "Stock Market Advisory Platform",
    doc_ids: list[int] | None = None,
) -> str:
    """Build a comprehensive, ground-truth structural digest prioritizing verified profile, requirements, and project files."""
    if doc_ids:
        docs = [d for d in store.list_documents() if d.id in doc_ids and d.status == "indexed" and d.file_type != "project_brief"]
    else:
        docs = [d for d in store.list_documents() if d.status == "indexed" and d.file_type != "project_brief"]
    if not docs:
        return ""

    lines: list[str] = []

    # 1. Ground-truth Verified Candidate Profile (so the LLM never guesses the wrong stack)
    try:
        profile = store.get_full_profile() or {}
        if profile:
            summary = profile.get("professional_summary") or ""
            skills = profile.get("skills") or []
            projects = profile.get("projects") or []
            lines.append("VERIFIED CANDIDATE PROFILE & TECH STACK (GROUND TRUTH):")
            if summary:
                lines.append(f"Summary: {summary}")
            if skills:
                lines.append("Verified Tech Stack: " + ", ".join(str(s) for s in skills[:25]))
            for proj in projects:
                if isinstance(proj, dict):
                    lines.append(
                        f"Project: {proj.get('name')} | Role: {proj.get('role')} | "
                        f"Tech: {', '.join(proj.get('technologies', []))} | "
                        f"Description: {proj.get('description')} | "
                        f"Achievements: {'; '.join(proj.get('achievements', []))}"
                    )
    except Exception:
        pass

    # 2. Deterministic End-to-End Flow Map for this specific project
    filtered_ids = [d.id for d in docs if d.id is not None]
    flow_overview = build_project_flow_overview(store, filtered_ids, project_title)
    flow_overview = flow_overview.split("🧠 AI ARCHITECT DEEP-DIVE")[0].strip()
    lines.append(flow_overview)

    # 3. Prioritize core architectural files
    priority_names = {
        "requirements.txt", "manage.py", "settings.py", "urls.py",
        "models.py", "views.py", "serializers.py", "ocr_service.py",
        "face_match_service.py", "seed_client_demo.py", "tasks.py",
        "consumers.py", "package.json",
    }
    priority_docs = [d for d in docs if d.filename.lower() in priority_names]
    other_docs = [d for d in docs if d.filename.lower() not in priority_names]

    excerpts: list[str] = []
    for doc in (priority_docs + other_docs)[:25]:
        if doc.id is None:
            continue
        chunks = store.get_chunks_for_document(doc.id)
        if not chunks:
            continue
        first_text = chunks[0].text
        if doc.filename.lower() in priority_names or doc.file_type in ("md", "docx", "pdf"):
            excerpts.append(f"[Real File: {doc.filename}]\n{first_text[:500]}")

    if excerpts:
        lines.append("REAL CODE & DOCUMENT EXCERPTS:\n" + "\n\n".join(excerpts[:10]))

    return "\n\n".join(lines)[:6000]


_FLOW_MAP_CACHE: dict[tuple[str, int], str] = {}


def build_project_flow_overview(store, doc_ids: list[int], project_title: str) -> str:
    """Generate a structured Architecture & End-to-End Flow Map from the indexed project files."""
    cached = _FLOW_MAP_CACHE.get((project_title, len(doc_ids)))
    if cached:
        return cached
    # If an AI Architecture Dossier already exists in the store for this project, include it at the top
    ai_dossier = ""
    for doc in store.list_documents():
        if doc.file_type == "project_brief" and "ai_architecture_dossier" in str(doc.path) and doc.id is not None:
            p_name = (doc.metadata or {}).get("project_name") or ""
            if p_name and p_name.lower() != project_title.lower() and project_title.lower() not in str(doc.path).lower():
                continue
            chunks = store.get_chunks_for_document(doc.id)
            if chunks:
                ai_dossier = chunks[0].text.strip()
                break

    models_list: list[str] = []
    views_and_apis: list[str] = []
    services_and_tasks: list[str] = []
    frontend_and_docs: list[str] = []
    detected_flows: list[str] = []
    packages: list[str] = []

    all_text_lower = []
    selected_docs = []
    for did in doc_ids:
        doc = store.get_document(did)
        if doc:
            selected_docs.append(doc)

    for doc in selected_docs:
        fname = doc.filename
        lower_name = fname.lower()
        chunks = store.get_chunks_for_document(doc.id) if doc.id is not None else []
        sample = "\n".join(c.text for c in chunks[:2]) if chunks else ""
        all_text_lower.append(sample.lower())

        if lower_name == "requirements.txt":
            for ln in sample.splitlines():
                clean = ln.strip()
                if clean and not clean.startswith("#"):
                    pkg = re.split(r"[=<>~!]", clean)[0].strip()
                    if pkg and pkg not in packages:
                        packages.append(pkg)
            continue

        classes = re.findall(r"^class\s+([A-Za-z0-9_]+)", sample, flags=re.MULTILINE)
        funcs = [
            fn for fn in re.findall(r"^def\s+([A-Za-z0-9_]+)", sample, flags=re.MULTILINE)
            if not fn.startswith("_")
        ]
        symbols = (classes[:5] + funcs[:5])[:6]
        sym_str = f" → {', '.join(symbols)}" if symbols else ""

        if "model" in lower_name or any("Model" in c for c in classes):
            models_list.append(f"• {fname}{sym_str}")
        elif any(k in lower_name for k in ("view", "url", "serializer", "api", "route", "permission", "auth")):
            views_and_apis.append(f"• {fname}{sym_str}")
        elif any(k in lower_name for k in ("service", "task", "celery", "ocr", "face", "consumer", "ws", "socket", "seed", "payment", "billing")):
            services_and_tasks.append(f"• {fname}{sym_str}")
        elif doc.file_type in ("md", "html", "docx", "json") and doc.file_type != "project_brief":
            frontend_and_docs.append(f"• {fname}")

    joined_corpus = "\n".join(all_text_lower)

    # Detect end-to-end functional flows automatically from the codebase
    if any(k in joined_corpus for k in ("jwt", "otp", "login", "authentication", "permission")):
        detected_flows.append(
            "1. Authentication & Multi-Tenant Access Flow:\n"
            "   Client Request → OTP / SimpleJWT Token Verification → Workspace-Scoped Permission Check → Role-Based Routing (Investor / Advisor / Admin)."
        )
    if any(k in joined_corpus for k in ("ocr", "pan", "kyc", "face_match", "deepface", "tesseract")):
        detected_flows.append(
            "2. Automated KYC & Biometric Verification Flow:\n"
            "   Document Upload (PAN + Selfie) → OCR Extraction (Tesseract/EasyOCR in ocr_service.py) → DeepFace ArcFace Biometric Match (face_match_service.py) → Auto-Approve / Under-Review / Reject Decision."
        )
    if any(k in joined_corpus for k in ("signal", "websocket", "channels", "advisory", "trade", "scripmaster")):
        detected_flows.append(
            "3. Real-Time Trade Signal & Execution Flow:\n"
            "   Advisor Publishes Call (Entry / Target / Stop-Loss) → Django REST Serializer Validation → Django Channels / Redis WebSocket Broadcast → Live Investor Dashboard Update."
        )
    if any(k in joined_corpus for k in ("celery", "square", "angel", "smartapi", "ltp", "cron")):
        detected_flows.append(
            "4. Background Celery & EOD Auto Square-Off Flow:\n"
            "   Scheduled Celery Beat Task → Fetch Live LTP via Angel One SmartAPI → Evaluate Intraday Open Positions → Auto Square-Off & P&L Calculation."
        )
    if any(k in joined_corpus for k in ("razorpay", "gst", "invoice", "subscription", "billing", "cgst")):
        detected_flows.append(
            "5. Subscription & GST-Compliant Billing Flow:\n"
            "   Plan Selection (30/90/365-Day) → Razorpay Order & Webhook Verification → CGST/SGST/IGST Split Calculation → Automated PDF Invoice Generation."
        )

    out: list[str] = [
        f"📁 PROJECT ARCHITECTURE & FLOW MAP: {project_title.upper()}",
        f"Total Indexed Files: {len(selected_docs)}  |  " + summarize_indexed_files([d.filename for d in selected_docs], joined_corpus[:4000]),
    ]
    if packages:
        out.append("Core Dependencies: " + ", ".join(packages[:18]))

    if detected_flows:
        out.append("\n🔄 END-TO-END SYSTEM & DATA FLOWS (HOW THE PROJECT WORKS)\n" + "\n\n".join(detected_flows))

    out.append("\n🗂️ CODEBASE LAYER BREAKDOWN (WHAT IS INSIDE)")
    if models_list:
        out.append("Database Models & Schemas:\n  " + "\n  ".join(models_list[:10]))
    if views_and_apis:
        out.append("API Views, Serializers & Routing:\n  " + "\n  ".join(views_and_apis[:12]))
    if services_and_tasks:
        out.append("Business Services, AI/OCR & Background Workers:\n  " + "\n  ".join(services_and_tasks[:12]))
    if frontend_and_docs:
        out.append("Architecture Specs & UI Flows:\n  " + "\n  ".join(frontend_and_docs[:10]))

    if ai_dossier:
        out.append("\n🧠 AI ARCHITECT DEEP-DIVE & INTERVIEW Q&A\n" + ai_dossier)
    else:
        out.append(
            "\n💡 TIP: Click 'Analyze Project with AI' on the left toolbar to generate Spoken Interview Q&A from this flow map."
        )

    result_text = "\n\n".join(out)
    _FLOW_MAP_CACHE[(project_title, len(doc_ids))] = result_text
    return result_text
