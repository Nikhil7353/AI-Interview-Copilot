"""Phase 2 tests: knowledge base, candidate profile, retrieval, and privacy."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.providers import ProviderError, generate_answer
from app.ai.prompt_builder import build_prompt
from app.knowledge.ingestion import extract_document, is_forbidden, scan_directory
from app.knowledge.profile import CandidateProfile, EmploymentEntry, ProjectEntry
from app.knowledge.retrieval import retrieve, build_context_string
from app.knowledge.store import KnowledgeStore, db_path, fallback_db_path, init_db


# ---------------------------------------------------------------------------
# Store: CRUD, persistence, isolation
# ---------------------------------------------------------------------------

def test_store_init_creates_tables(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    store = KnowledgeStore(db)
    docs = store.list_documents()
    assert docs == []


def test_store_add_and_list_document(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    doc_id = store.add_document("resume.pdf", "/tmp/resume.pdf", "pdf", 1234, {"pages": 2})
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0].filename == "resume.pdf"
    assert docs[0].id == doc_id


def test_store_remove_document(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    doc_id = store.add_document("a.txt", "/tmp/a.txt", "txt", 10, {})
    assert store.remove_document(doc_id) is True
    assert store.remove_document(doc_id) is False
    assert store.list_documents() == []


def test_store_add_chunks_and_search(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    doc_id = store.add_document("resume.txt", "/tmp/resume.txt", "txt", 50, {})
    store.add_chunks(doc_id, [("I built a Django REST API", None), ("I used PostgreSQL for caching", None)])
    results = store.search_chunks("Django REST API", limit=5)
    assert len(results) >= 1
    assert any("Django" in r["text"] for r in results)


def test_store_search_returns_empty_for_unrelated(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_document("a.txt", "/tmp/a.txt", "txt", 10, {})
    store.add_chunks(1, [("Python web development", None)])
    results = store.search_chunks("quantum physics", limit=5)
    assert results == []


def test_store_profile_field_round_trip(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.set_profile_field("professional_summary", "Senior Python developer", "verified", "user_profile")
    value = store.get_profile_field("professional_summary")
    assert value == "Senior Python developer"
    store.set_profile_field("skills", ["Python", "Django"], "verified", "user_profile")
    assert store.get_profile_field("skills") == ["Python", "Django"]


def test_store_profile_facts(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    fid = store.add_profile_fact("experience", "Led a team of 5 engineers", "verified", "resume.pdf")
    facts = store.list_profile_facts("experience")
    assert len(facts) == 1
    assert facts[0]["fact"] == "Led a team of 5 engineers"
    assert facts[0]["status"] == "verified"
    assert store.set_fact_status(fid, "outdated") is True
    facts = store.list_profile_facts("experience")
    assert facts[0]["status"] == "outdated"
    assert store.remove_profile_fact(fid) is True
    assert store.list_profile_facts("experience") == []


def test_store_clear_profile_removes_facts(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.set_profile_field("professional_summary", "Summary", "needs_review", "user_profile")
    store.add_profile_fact("skills", "Python", "verified", "user_profile")
    store.clear_profile()
    assert store.get_full_profile() == {}
    assert store.list_profile_facts() == []


# ---------------------------------------------------------------------------
# Ingestion: supported formats, errors, forbidden paths
# ---------------------------------------------------------------------------

def test_ingest_text_file(tmp_path):
    f = tmp_path / "resume.txt"
    f.write_text("I am a Python developer with Django experience.", encoding="utf-8")
    extracted = extract_document(f)
    assert extracted.error is None
    assert "Python developer" in extracted.text
    assert extracted.file_type == "txt"
    assert len(extracted.chunks) >= 1


def test_ingest_markdown_file(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Project\n\nBuilt with FastAPI and PostgreSQL.", encoding="utf-8")
    extracted = extract_document(f)
    assert extracted.error is None
    assert "FastAPI" in extracted.text


def test_ingest_json_file(tmp_path):
    f = tmp_path / "data.json"
    f.write_text('{"name": "AI Copilot", "stack": ["Python", "PySide6"]}', encoding="utf-8")
    extracted = extract_document(f)
    assert extracted.error is None
    assert "AI Copilot" in extracted.text


def test_ingest_unsupported_file(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02\x03")
    extracted = extract_document(f)
    assert extracted.error is not None
    assert "Unsupported" in extracted.error


def test_ingest_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    extracted = extract_document(f)
    assert extracted.error is not None
    assert "No extractable text" in extracted.error


def test_ingest_nonexistent_file(tmp_path):
    extracted = extract_document(tmp_path / "missing.txt")
    assert extracted.error is not None


def test_is_forbidden_skips_venv_and_env(tmp_path):
    assert is_forbidden(tmp_path / ".venv" / "lib" / "site-packages" / "foo.py")
    assert is_forbidden(tmp_path / "node_modules" / "package.js")
    assert is_forbidden(tmp_path / ".env")
    assert is_forbidden(tmp_path / ".env.local")
    assert is_forbidden(tmp_path / "secrets.json")
    assert is_forbidden(tmp_path / "id_rsa")
    assert is_forbidden(tmp_path / ".git" / "config")
    assert is_forbidden(tmp_path / "build" / "output.exe")
    assert not is_forbidden(tmp_path / "src" / "main.py")
    assert not is_forbidden(tmp_path / "docs" / "readme.md")


def test_scan_directory_skips_forbidden(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "foo.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("# Docs", encoding="utf-8")
    files = scan_directory(tmp_path)
    names = {f.name for f in files}
    assert "main.py" in names
    assert "readme.md" in names
    assert "foo.py" not in names


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------

def test_profile_serialization_round_trip():
    profile = CandidateProfile(
        professional_summary="Backend engineer",
        skills=["Python", "Django"],
        skill_status="verified",
        employment=[EmploymentEntry(title="Dev", company="Acme", start_date="2020", end_date="Present", responsibilities=["Built APIs"], status="verified")],
        projects=[ProjectEntry(name="Copilot", description="AI assistant", technologies=["Python"], role="Solo dev", achievements=["Shipped MVP"], status="verified")],
    )
    data = profile.to_dict()
    restored = CandidateProfile.from_dict(data)
    assert restored.professional_summary == "Backend engineer"
    assert restored.skills == ["Python", "Django"]
    assert restored.skill_status == "verified"
    assert restored.employment[0].title == "Dev"
    assert restored.projects[0].name == "Copilot"


def test_profile_has_verified_experience():
    profile = CandidateProfile()
    assert profile.has_verified_experience() is False
    profile.employment.append(EmploymentEntry(status="verified"))
    assert profile.has_verified_experience() is True
    profile2 = CandidateProfile()
    profile2.projects.append(ProjectEntry(status="verified"))
    assert profile2.has_verified_experience() is True


def test_profile_missing_personal_evidence():
    profile = CandidateProfile()
    missing = profile.missing_personal_evidence()
    assert "employment or project experience" in missing
    assert "technical skills" in missing
    profile.skills = ["Python"]
    profile.skill_status = "verified"
    missing = profile.missing_personal_evidence()
    assert "technical skills" not in missing


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def test_retrieval_returns_context_for_matching_question(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_document("resume.txt", "/tmp/resume.txt", "txt", 50, {})
    store.add_chunks(1, [("I built a Django REST API with PostgreSQL", None)])
    store.add_profile_fact("skills", "Python", "verified", "user_profile")
    store.add_profile_fact("experience", "Led backend team at Acme", "verified", "user_profile")
    result = retrieve(store, "Tell me about your Django experience", limit_chunks=5, limit_facts=5)
    assert result.has_evidence is True
    assert len(result.items) >= 1


def test_retrieval_no_evidence_for_unrelated(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_document("resume.txt", "/tmp/resume.txt", "txt", 50, {})
    store.add_chunks(1, [("I built a Django REST API", None)])
    result = retrieve(store, "What is quantum entanglement?", limit_chunks=5, limit_facts=5)
    assert result.has_evidence is False
    assert len(result.items) == 0


def test_build_context_string_cites_sources(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_document("resume.txt", "/tmp/resume.txt", "txt", 50, {})
    store.add_chunks(1, [("I built a Django REST API with PostgreSQL and led backend experience", "page 1")])
    result = retrieve(store, "Django experience", limit_chunks=5, limit_facts=5)
    ctx = build_context_string(result)
    assert "resume.txt" in ctx
    assert "Django" in ctx
    assert "document excerpt" in ctx


def test_unverified_profile_facts_are_not_sent(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_profile_fact("experience", "Led a Django team at Acme", "needs_review", "user_profile")
    store.add_profile_fact("experience", "Shipped a Django API at Beta", "verified", "user_profile")
    result = retrieve(store, "Tell me about your Django experience")
    texts = [item.text for item in result.items]
    assert any("Beta" in text for text in texts)
    assert all("Acme" not in text for text in texts)
    assert any("Acme" in item.text for item in result.needs_review_items)
    assert "Acme" not in build_context_string(result)
    assert "Beta" in build_context_string(result)


def test_project_brief_is_sent_even_when_the_question_uses_different_words(tmp_path):
    store = KnowledgeStore(tmp_path / "brief.db")
    store.add_document("shop project brief", str(tmp_path / "shop") + "::project-brief", "project_brief", 40, {})
    store.add_chunks(1, [("Project folder: shop\nDjango checkout with PostgreSQL", "project brief")])
    result = retrieve(store, "quantum physics")
    assert any("Django checkout" in item.text for item in result.items)


def test_chunking_splits_single_newline_documents_and_autofills_profile(tmp_path):
    from app.knowledge.ingestion import _chunk_text
    from app.knowledge.profile import extract_profile_from_resume_text, save_candidate_profile

    long_single_newline = "\n".join(f"Line {i}:Built Django REST APIs and PostgreSQL models for fintech SaaS." for i in range(40))
    chunks = _chunk_text(long_single_newline, max_chars=500, overlap=100)
    assert len(chunks) >= 4
    assert sum(len(text) for text, _ in chunks) >= len(long_single_newline) * 0.9

    sample_resume = (
        "NIKHIL CHAVHAN\n"
        "SUMMARY\n"
        "Software developer building a fintech SaaS platform with Python, Django REST Framework, React, and PostgreSQL.\n"
        "WORK EXPERIENCE\n"
        "Software Developer — RSL Solution Pvt. Ltd. Oct 2025 – Present\n"
        "Verified Trade Advisory Platform (Fintech SaaS)\n"
        "Reduced manual billing effort by ~70% by automating GST-compliant Razorpay billing.\n"
    )
    store = KnowledgeStore(tmp_path / "autofill.db")
    profile = extract_profile_from_resume_text(sample_resume, status="verified")
    save_candidate_profile(store, profile)
    assert "Python" in profile.skills
    assert len(profile.employment) == 1
    assert len(profile.projects) == 1
    assert any(f["status"] == "verified" for f in store.list_profile_facts())


def test_question_stopwords_still_match_resume_chunk(tmp_path):
    store = KnowledgeStore(tmp_path / "test.db")
    store.add_document("resume.txt", "/tmp/resume.txt", "txt", 50, {})
    store.add_chunks(1, [("I built a Django REST API with PostgreSQL", None)])
    results = store.search_chunks("Tell me about your Django experience")
    assert any("Django" in row["text"] for row in results)


# ---------------------------------------------------------------------------
# Prompt builder: no invented facts, verified context boundary
# ---------------------------------------------------------------------------

def test_prompt_marks_missing_evidence():
    prompt = build_prompt("Tell me about your projects", context="")
    assert "do not invent personal experience" in prompt
    assert "no verified context" in prompt.lower() or "no verified context supports it" in prompt


def test_prompt_uses_verified_context_only():
    prompt = build_prompt("What did you build?", context="[resume.txt] I built a Django REST API")
    assert "Verified context" in prompt
    assert "I built a Django REST API" in prompt


# ---------------------------------------------------------------------------
# Provider: privacy — local-only mode never calls cloud
# ---------------------------------------------------------------------------

def test_ollama_provider_does_not_require_env_key(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers=None, timeout=90):
        captured["url"] = url
        captured["payload"] = payload
        return {"response": "A local answer."}

    monkeypatch.setattr("app.ai.providers._post_json", fake_post)
    # Ensure no cloud key leaks into the call
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    answer = generate_answer("What is Python?", "ollama", "llama3.2:3b")
    assert answer == "A local answer."
    assert "localhost" in captured["url"]


def test_ollama_provider_does_not_require_env_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    captured = {}

    def fake_post(url, payload, headers=None, timeout=90):
        captured.update(url=url)
        return {"response": "A local answer."}

    monkeypatch.setattr("app.ai.providers._post_json", fake_post)
    answer = generate_answer("What is Python?", "ollama", "llama3.2:3b")
    assert answer == "A local answer."
    assert "localhost" in captured["url"]


def test_unknown_provider_raises():
    with pytest.raises(ProviderError, match="Unknown provider"):
        generate_answer("Question", "nonexistent", "model")


# ---------------------------------------------------------------------------
# Provider failure handling
# ---------------------------------------------------------------------------

def test_provider_connection_error(monkeypatch):
    from app.ai.providers import ProviderError

    def fake_post(url, payload, headers=None, timeout=90):
        raise ProviderError("Could not reach the AI service: Connection refused")

    monkeypatch.setattr("app.ai.providers._post_json", fake_post)
    with pytest.raises(ProviderError, match="Could not reach the AI service"):
        generate_answer("What is Python?", "ollama", "llama3.2:3b")


def test_provider_empty_answer(monkeypatch):
    monkeypatch.setattr("app.ai.providers._post_json", lambda *a, **k: {"response": ""})
    with pytest.raises(ProviderError, match="empty answer"):
        generate_answer("What is Python?", "ollama", "llama3.2:3b")


# ---------------------------------------------------------------------------
# UI: knowledge panel (offscreen Qt)
# ---------------------------------------------------------------------------

def _offscreen_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_knowledge_panel_refresh_and_import(tmp_path):
    app = _offscreen_app()
    from app.ui.knowledge_panel import KnowledgePanel

    store = KnowledgeStore(tmp_path / "kb.db")
    panel = KnowledgePanel(store)
    panel.show()

    # Import a text file
    f = tmp_path / "resume.txt"
    f.write_text("I am a senior Python developer with Django and AWS experience.", encoding="utf-8")
    panel._import_single(str(f))
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0].filename == "resume.txt"

    # Context preview for matching question
    panel.set_current_question("Django experience")
    app.processEvents()
    ctx = panel.ctx_preview.toPlainText()
    assert "Django" in ctx or "No relevant" in ctx
    panel.close()


def test_knowledge_panel_remove_document(tmp_path):
    app = _offscreen_app()
    from app.ui.knowledge_panel import KnowledgePanel
    from PySide6.QtWidgets import QMessageBox

    store = KnowledgeStore(tmp_path / "kb.db")
    panel = KnowledgePanel(store)
    panel.show()

    store.add_document("a.txt", "/tmp/a.txt", "txt", 10, {})
    panel._refresh_documents()
    assert panel.doc_table.rowCount() == 1

    # Select and remove
    panel.doc_table.selectRow(0)
    with patch("app.ui.knowledge_panel.QMessageBox.question", return_value=QMessageBox.Yes):
        panel.remove_selected()
    assert panel.doc_table.rowCount() == 0
    panel.close()


def test_profile_editor_load_and_save(tmp_path):
    app = _offscreen_app()
    from app.ui.profile_editor import ProfileEditor

    store = KnowledgeStore(tmp_path / "kb.db")
    store.set_profile_field("professional_summary", "Senior developer", "needs_review", "user_profile")
    store.set_profile_field("skills", ["Python", "Django"], "verified", "user_profile")

    dlg = ProfileEditor(store)
    dlg.show()
    assert "Senior developer" in dlg.edit_summary.toPlainText()
    assert "Python" in dlg.edit_skills.toPlainText()

    dlg.edit_summary.setPlainText("Updated summary")
    dlg._save()
    assert store.get_profile_field("professional_summary") == "Updated summary"
    dlg.close()


def test_main_window_integrates_knowledge_panel(tmp_path):
    app = _offscreen_app()
    from app.config import AppConfig
    from app.ui.main_window import MainWindow

    config = AppConfig(use_postgresql=False)
    window = MainWindow(config)
    window.show()

    assert window.knowledge_panel is not None
    assert window.knowledge_store is not None

    # Submitting a question should retrieve context
    window.question.setPlainText("What is Django?")
    # Mock generate_answer to avoid network
    with patch("app.ui.workers.iter_ollama_response", return_value=iter(["Django is a web framework."])):
        window.submit_question()
        # Wait for the async worker to complete
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        window.worker.finished.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
        app.processEvents()
    answer = window.answer.toPlainText()
    assert "Django" in answer or "web framework" in answer

    window.close()


def test_postgres_unreachable_falls_back_to_sqlite(tmp_path):
    store = KnowledgeStore(
        path=tmp_path / "fallback.db",
        database_url="postgresql://invalid_user:invalid_pass@127.0.0.1:54321/nonexistent_db",
        use_postgresql=True,
    )
    assert store.use_postgresql is False
    assert store.fallback_warning is not None
    assert "fallback" in str(store._backend.path) or "fallback.db" in str(store._backend.path)


def test_entry_dialog_status_verification():
    _offscreen_app()
    from app.ui.profile_editor import _EntryDialog

    dlg = _EntryDialog(
        title="Add project",
        labels=["Project name", "Description"],
        status="verified",
    )
    assert dlg.status_value() == "verified"
    dlg.status_combo.setCurrentText("Outdated")
    assert dlg.status_value() == "outdated"
    dlg.close()


def test_multi_project_isolated_dossiers_and_retrieval(tmp_path):
    store = KnowledgeStore(path=tmp_path / "multi_proj.db", use_postgresql=False)

    # Project 1: Stock Market Advisory Platform
    doc1 = store.add_document(
        filename="models.py",
        path=str(tmp_path / "stock" / "models.py"),
        file_type="py",
        size_bytes=300,
        metadata={"project_name": "Stock Market Advisory Platform", "project_root": str(tmp_path / "stock")},
        status="indexed",
    )
    store.add_chunks(doc1, [("class TradeSignal(models.Model): symbol = models.CharField()", "models.py")])

    dossier1 = store.add_document(
        filename="AI Project Architecture Dossier — Stock Market Advisory Platform",
        path="ai_architecture_dossier::Stock Market Advisory Platform::project_brief",
        file_type="project_brief",
        size_bytes=500,
        metadata={"kind": "ai_architecture_dossier", "project_name": "Stock Market Advisory Platform"},
        status="indexed",
    )
    store.add_chunks(dossier1, [("Stock Market Advisory: Angel One SmartAPI, Celery auto square-off.", "dossier")])

    # Project 2: E-Commerce Store
    doc2 = store.add_document(
        filename="routes.py",
        path=str(tmp_path / "ecommerce" / "routes.py"),
        file_type="py",
        size_bytes=250,
        metadata={"project_name": "E-Commerce Store", "project_root": str(tmp_path / "ecommerce")},
        status="indexed",
    )
    store.add_chunks(doc2, [("def checkout_cart(): return StripePayment()", "routes.py")])

    dossier2 = store.add_document(
        filename="AI Project Architecture Dossier — E-Commerce Store",
        path="ai_architecture_dossier::E-Commerce Store::project_brief",
        file_type="project_brief",
        size_bytes=400,
        metadata={"kind": "ai_architecture_dossier", "project_name": "E-Commerce Store"},
        status="indexed",
    )
    store.add_chunks(dossier2, [("E-Commerce Store: FastAPI, Stripe webhooks, Redis cart cache.", "dossier")])

    # Test 1: Flow overview for Stock Market matches only its own dossier
    from app.knowledge.project_summary import build_project_flow_overview
    flow1 = build_project_flow_overview(store, [doc1], "Stock Market Advisory Platform")
    assert "Stock Market Advisory: Angel One" in flow1
    assert "E-Commerce Store" not in flow1

    # Test 2: Retrieval for Stock Market question boosts Stock Market dossier
    from app.knowledge.retrieval import retrieve
    res1 = retrieve(store, "How did you do square-off in your stock market advisory platform?")
    top_dossier1 = next(item for item in res1.items if "AI Project Architecture Dossier" in item.source)
    assert "Stock Market Advisory Platform" in top_dossier1.source

    # Test 3: Retrieval for E-Commerce question boosts E-Commerce dossier
    res2 = retrieve(store, "Tell me about checkout in your e-commerce store.")
    top_dossier2 = next(item for item in res2.items if "AI Project Architecture Dossier" in item.source)
    assert "E-Commerce Store" in top_dossier2.source

