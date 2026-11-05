from app.audio.capture import CaptureError, MicrophoneRecorder
from app.audio.diarization import cluster_speakers
from app.knowledge.embeddings import cosine_similarity
from app.audio.transcription import (
    TranscriptionError,
    is_small_talk_or_mic_check,
    last_question_from_transcript,
    strip_transcript_metadata,
    transcribe_file,
)
from app.knowledge.project_summary import analyze_project_folder, summarize_indexed_files
from app.interview.dedup import is_duplicate, normalize_question
from app.interview.evaluation import build_evaluation_prompt
from app.interview.questions import next_question


def test_duplicate_questions_ignore_case_and_punctuation():
    previous = ["What is Django REST Framework?"]
    assert is_duplicate("what is django rest framework", previous)
    assert not is_duplicate("How do serializers work?", previous)
    assert normalize_question("  Tell   me. ") == "tell me"


def test_next_question_avoids_repeats_until_the_category_is_exhausted():
    seen = set()
    first = next_question("Python", seen)
    second = next_question("Python", seen)
    assert first != second
    assert first in seen and second in seen


def test_evaluation_prompt_keeps_the_candidate_answer():
    prompt = build_evaluation_prompt("What is an index?", "An index speeds lookups.", context="")
    assert "What is an index?" in prompt
    assert "An index speeds lookups." in prompt
    assert "Do not invent" in prompt


def test_last_question_from_transcript():
    transcript = "Hello there. What is Django? How do serializers work?"
    assert last_question_from_transcript(transcript) == "How do serializers work?"


def test_strip_metadata_and_ignore_mic_checks():
    raw = "[0.5-15.0] Speaker 1: Hi, hi, hi, can you hear me?"
    cleaned = last_question_from_transcript(raw)
    assert "[0.5-15.0]" not in cleaned
    assert "Speaker 1:" not in cleaned
    assert is_small_talk_or_mic_check(raw) is True
    assert is_small_talk_or_mic_check("How did you design the Django REST API in your project?") is False
    assert strip_transcript_metadata("[1.0-4.2] Interviewer: Walk me through your project") == "Walk me through your project"


def test_cluster_speakers_separates_distinct_voices():
    quiet = [[0.1, 0.1, 0.1], [0.12, 0.11, 0.09]]
    loud = [[0.9, 0.8, 0.7], [0.88, 0.82, 0.75]]
    labels = cluster_speakers(quiet + loud)
    assert labels[:2] == ["Speaker 1", "Speaker 1"]
    assert labels[2:] == ["Speaker 2", "Speaker 2"]


def test_similar_vectors_score_higher_than_unrelated_ones():
    base = [1.0, 0.0, 0.0] + [0.0] * 381
    close = [0.9, 0.1, 0.0] + [0.0] * 381
    far = [0.0, 1.0, 0.0] + [0.0] * 381
    assert cosine_similarity(base, close) > cosine_similarity(base, far)


def test_analyze_project_folder_reads_readme_without_running_code(tmp_path):
    (tmp_path / "README.md").write_text("Shop API for orders", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("django==4.2\n", encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "views.py").write_text("def order_list(request):\n    return []\n", encoding="utf-8")
    brief = analyze_project_folder(tmp_path)
    assert "Shop API for orders" in brief
    assert "django" in brief.lower()
    assert "views.py" in brief
    assert "order_list" in brief


def test_project_summary_detects_python_and_django():
    text = summarize_indexed_files(["app/views.py", "requirements.txt"], "django rest_framework")
    assert "Python" in text
    assert "Django" in text


def test_microphone_reports_missing_package(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name in ("sounddevice", "pyaudiowpatch"):
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    try:
        MicrophoneRecorder().start()
    except CaptureError as exc:
        assert "sounddevice" in str(exc)
    else:
        raise AssertionError("missing sounddevice should be reported")


def test_transcribe_missing_file(tmp_path):
    try:
        transcribe_file(str(tmp_path / "missing.wav"))
    except TranscriptionError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("missing audio should fail")


def test_transcribe_reports_missing_optional_package(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    import builtins
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    try:
        transcribe_file(str(audio))
    except TranscriptionError as exc:
        assert "faster-whisper" in str(exc)
    else:
        raise AssertionError("missing faster-whisper should be reported")


def test_last_question_extracts_question_when_dialogue_follows():
    from app.audio.transcription import is_small_talk_or_mic_check, last_question_from_transcript

    dialogue = "[0.0-3.5] Speaker 1: What is Django? [3.6-7.2] Speaker 2: We use it for web APIs."
    assert last_question_from_transcript(dialogue) == "What is Django?"

    greeting = "Hello, can you hear me?"
    assert is_small_talk_or_mic_check(greeting) is True

    real_q = "How do you handle database migrations in production?"
    assert is_small_talk_or_mic_check(real_q) is False

    intro_with_greeting = "Good morning Nikhil, please introduce yourself."
    assert is_small_talk_or_mic_check(intro_with_greeting) is False

    resume_with_greeting = "Good afternoon, let's talk about your resume."
    assert is_small_talk_or_mic_check(resume_with_greeting) is False

    pure_greeting = "Good morning"
    assert is_small_talk_or_mic_check(pure_greeting) is True

    pure_mic_check = "Am I audible?"
    assert is_small_talk_or_mic_check(pure_mic_check) is True


def test_utterance_detector_flushes_on_silence():
    import numpy as np
    from app.audio.capture import _UtteranceDetector

    flushed = []
    detector = _UtteranceDetector(
        on_utterance=lambda audio: flushed.append(audio),
        sample_rate=16000,
        silence_seconds=0.2,
        min_speech_seconds=0.1,
        energy_threshold=0.01,
    )
    # Speech chunk (high energy)
    speech = np.ones(1600, dtype=np.float32) * 0.1
    # Silence chunk (zero energy)
    silence = np.zeros(1600, dtype=np.float32)

    # Send 2 speech chunks (0.2s of speech)
    detector.process_chunk(speech, np)
    detector.process_chunk(speech, np)
    assert len(flushed) == 0

    # Send 3 silence chunks (0.3s of silence > silence_seconds 0.2s)
    detector.process_chunk(silence, np)
    detector.process_chunk(silence, np)
    detector.process_chunk(silence, np)
    assert len(flushed) == 1
    assert len(flushed[0]) == 1600 * 4  # pre-roll/speech chunks concatenated


def test_candidate_mic_speech_is_not_submitted_as_question(monkeypatch):
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from app.config import AppConfig
    from app.ui.main_window import MainWindow

    # Ensure QApplication exists for GUI tests
    _app = QApplication.instance() or QApplication([])

    cfg = AppConfig(audio_source="both")
    mock_store = MagicMock()
    mock_store.fallback_warning = None
    mock_store.total_chunks = MagicMock(return_value=0)
    mock_store.unembedded_count = MagicMock(return_value=0)
    monkeypatch.setattr("app.ui.main_window.KnowledgeStore", lambda **kw: mock_store)
    monkeypatch.setattr("app.ui.main_window.register_global_hotkeys", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr("app.ui.main_window.apply_premium_window_chrome", lambda *args, **kwargs: None)

    window = MainWindow(cfg)
    submitted = []
    window.submit_question = lambda: submitted.append(window.question.toPlainText())
    window.question.setPlainText("Interviewer question already on screen?")

    # Candidate speaks into their microphone in "both" mode
    window._on_auto_utterance_text("Yes, in our platform we used Celery workers for async execution.", source="mic")

    # The question on screen should NOT be overwritten by the candidate's speech
    assert window.question.toPlainText() == "Interviewer question already on screen?"
    # submit_question should NOT have been called!
    assert len(submitted) == 0
    # Candidate speech should be recorded in session_transcript as Candidate turn
    assert any("Candidate: Yes, in our platform" in line for line in window.session_transcript)

    # Now interviewer speaks via system audio (loopback)
    window._on_auto_utterance_text("How did you handle Redis failover?", source="system")
    # Interviewer question should be set and submitted!
    assert window.question.toPlainText() == "How did you handle Redis failover?"
    assert len(submitted) == 1


def test_floating_panel_teleprompter_and_zoom(monkeypatch):
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    from app.ui.floating_panel import FloatingPanel

    _app = QApplication.instance() or QApplication([])
    panel = FloatingPanel(submit=MagicMock(), copy=MagicMock())

    # Initial state
    assert not panel.teleprompter_mode
    assert not panel.q_box.isHidden()
    assert panel.hud_font_size == 14

    # Toggle Teleprompter (Mini Mode)
    panel.toggle_teleprompter()
    assert panel.teleprompter_mode
    assert panel.q_box.isHidden()
    assert panel.actions_widget.isHidden()
    assert panel.teleprompter_button.text() == "Full"

    # Toggle back to Full Mode
    panel.toggle_teleprompter()
    assert not panel.teleprompter_mode
    assert not panel.q_box.isHidden()
    assert not panel.actions_widget.isHidden()
    assert panel.teleprompter_button.text() == "Mini"

    # Test Font Zoom
    panel.zoom_font(+2)
    assert panel.hud_font_size == 16
    panel.zoom_font(-3)
    assert panel.hud_font_size == 13

    # Test Speaking state indicator
    panel.set_speaking_state(True)
    assert "Speaking" in panel.status.text()
    panel.set_speaking_state(False)
    assert "Listening" in panel.status.text()

    # Test Markdown answer rendering
    panel.set_answer("• **Celery workers**: Handled async signal distribution.", elapsed_sec=0.4)
    assert "Celery workers" in panel.answer.toPlainText()
    assert "0.4s" in panel.speed_badge.text()

    # Test Hide button
    assert hasattr(panel, "hide_button")
    assert "Hide" in panel.hide_button.text()

    # Test multi-bullet answer auto-fit and top-aligned scroll
    long_answer = (
        "• Cursor pagination queries keyset directly with index.\n"
        "• Stable consistency across high-throughput writes.\n"
        "• Integrates with DRF viewsets.\n"
        "• Eliminates slow SQL OFFSET scan on large PostgreSQL tables."
    )
    panel.set_answer(long_answer, elapsed_sec=0.5)
    assert panel.answer.verticalScrollBar().value() == 0
    assert panel.height() >= 520


def test_scan_directory_includes_pdf(tmp_path):
    from app.knowledge.ingestion import scan_directory

    pdf_file = tmp_path / "resume.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy")
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("notes", encoding="utf-8")

    scanned = scan_directory(tmp_path)
    names = {p.name for p in scanned}
    assert "resume.pdf" in names
    assert "notes.txt" in names
