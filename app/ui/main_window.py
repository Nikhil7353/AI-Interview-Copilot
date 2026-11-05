from datetime import datetime
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QThread, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMessageBox, QPushButton,
                               QPlainTextEdit, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from app.config import save_config
from app.ui.floating_panel import FloatingPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.workers import AnswerWorker
from app.audio.capture import CaptureError, ContinuousListener, MicrophoneRecorder
from app.audio.transcription import (
    TranscriptionError,
    _get_whisper_model,
    is_small_talk_or_mic_check,
    last_question_from_transcript,
    strip_transcript_metadata,
    transcribe_file,
    transcribe_pcm_array,
)
from app.interview.dedup import is_duplicate
from app.ui.knowledge_panel import KnowledgePanel
from app.ui.practice_panel import PracticePanel
from app.ui.profile_editor import ProfileEditor
from app.knowledge.store import KnowledgeStore
from app.ui.theme import APP_STYLESHEET, GlassCanvas, GlassFrame
from app.windows.capture_affinity import set_capture_exclusion
from app.windows.dwm_backdrop import apply_premium_window_chrome
from app.windows.hotkeys import register_global_hotkeys, unregister_global_hotkeys


class _TranscribeThread(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.finished.emit(transcribe_file(self.path))
        except TranscriptionError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Transcription failed: {exc}")


class _UtteranceTranscribeThread(QThread):
    finished = Signal(str, str)

    def __init__(self, samples, source: str = "system"):
        super().__init__()
        self.samples = samples
        self.source = source

    def run(self):
        text = transcribe_pcm_array(self.samples, model_size="base.en")
        if text:
            self.finished.emit(text, self.source)


class _BackfillThread(QThread):
    def __init__(self, store, config=None):
        super().__init__()
        self.store = store
        self.config = config

    def run(self):
        import os

        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        try:
            self.store._backfill_embeddings()
        except Exception:
            pass
        try:
            _get_whisper_model("small.en")
        except Exception:
            pass
        if self.config and self.config.provider == "ollama":
            try:
                from app.ai.providers import _post_json

                _post_json(
                    f"{self.config.ollama_url.rstrip('/')}/api/generate",
                    {"model": self.config.model, "prompt": "hi", "stream": False, "keep_alive": "30m", "options": {"num_predict": 1}},
                    timeout=15,
                )
            except Exception:
                pass


class MainWindow(QMainWindow):
    _utterance_captured = Signal(object)

    def __init__(self, config):
        super().__init__()
        self._utterance_captured.connect(self._on_auto_utterance_audio)
        self.config = config
        self.thread = None
        self.worker = None
        self.history = []
        self.answered_questions = []
        self.session_transcript = []
        self._recorder = None
        self._continuous_listener = None
        self._utterance_threads = []
        self._transcribe_thread = None
        self._backfill_thread = None
        self.assistant_paused = False
        self.last_context = ""
        self._question_start_time = 0.0
        self.speaker_names = ("Interviewer", "Candidate")
        self._registered_hotkeys = []
        self.local_shortcuts = []
        self.knowledge_store = KnowledgeStore(
            database_url=config.database_url,
            use_postgresql=config.use_postgresql,
        )
        self.setWindowTitle("AI Interview Copilot")
        self.resize(1150, 760)
        self.setMinimumSize(720, 560)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._apply_config()
        self._setup_tray_icon()
        self._start_embedding_backfill()

    def _start_embedding_backfill(self):
        import os

        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        if self._backfill_thread and self._backfill_thread.isRunning():
            return
        self._backfill_thread = _BackfillThread(self.knowledge_store, self.config)
        self._backfill_thread.start()

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _build_ui(self):
        root = GlassCanvas()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        # ---- Top Header Bar ----
        header = QHBoxLayout()
        header.setSpacing(10)
        titlebox = QVBoxLayout()
        titlebox.setSpacing(1)
        title = QLabel("AI Interview Copilot")
        title.setObjectName("title")
        subtitle = QLabel("Real-time spoken answers grounded in your resume & codebase")
        subtitle.setObjectName("subtitle")
        titlebox.addWidget(title)
        titlebox.addWidget(subtitle)
        header.addLayout(titlebox)
        header.addStretch()

        self.provider_status = QLabel()
        self.provider_status.setObjectName("statusPill")
        self.provider_status.setFixedHeight(28)
        header.addWidget(self.provider_status, 0, Qt.AlignVCenter)

        self.capture_status = QLabel()
        self.capture_status.setObjectName("statusPill")
        self.capture_status.setFixedHeight(28)
        header.addWidget(self.capture_status, 0, Qt.AlignVCenter)

        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)

        compact = QPushButton("Live HUD  ·  Ctrl+Shift+Space")
        compact.setObjectName("primary")
        compact.clicked.connect(self.open_compact)
        header.addWidget(compact)
        outer.addLayout(header)

        # ---- Full-Window Workspace Tabs (Zero Overlap) ----
        self.workspace_tabs = QTabWidget()

        # ================= WORKSPACE 1: LIVE COPILOT =================
        self.live_tab = QWidget()
        live_outer = QVBoxLayout(self.live_tab)
        live_outer.setContentsMargins(6, 6, 6, 6)
        live_outer.setSpacing(10)

        live_splitter = QSplitter(Qt.Horizontal)
        live_splitter.setChildrenCollapsible(False)

        # Left 68%: Question + Audio Bar + Large Answer Stage
        left = GlassFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 16, 18, 16)
        left_layout.setSpacing(10)

        q_top_row = QHBoxLayout()
        q_top_row.addWidget(self._section_label("❓ QUESTION (LIVE SPEECH OR MANUAL)"))
        q_top_row.addStretch()
        self.status = QLabel("● Ready")
        self.status.setObjectName("liveStatusText")
        q_top_row.addWidget(self.status)
        left_layout.addLayout(q_top_row)

        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Spoken interview question appears here automatically (or type & press Ctrl+Enter)…")
        self.question.setMaximumHeight(88)
        left_layout.addWidget(self.question)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.auto_listen_button = QPushButton("Auto-Listen")
        self.auto_listen_button.setToolTip(
            "Hands-free mode: continuously listens to System Audio (Zoom/Meet headphones) + Mic and auto-generates answers"
        )
        self.auto_listen_button.clicked.connect(self.toggle_auto_listen)
        row.addWidget(self.auto_listen_button)

        self.ask = QPushButton("Generate answer  ·  Ctrl+Enter")
        self.ask.setObjectName("primary")
        self.ask.clicked.connect(self.submit_question)
        row.addWidget(self.ask)

        self.test_ai_button = QPushButton("🎯 Quick Test (Simulate Interviewer)")
        self.test_ai_button.setToolTip("Simulate an interviewer asking about your Trade Advisory platform to test Live HUD answer streaming in <1s")
        self.test_ai_button.clicked.connect(self.simulate_quick_test)
        row.addWidget(self.test_ai_button)

        self.record_button = QPushButton("Record")
        self.record_button.clicked.connect(self.toggle_recording)
        row.addWidget(self.record_button)

        row.addStretch()
        left_layout.addLayout(row)

        left_layout.addWidget(self._section_label("💡 ANSWER (REAL-TIME SPOKEN BULLETS)"))
        self.answer = QPlainTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setPlaceholderText(
            "• Click Auto-Listen (or open Live HUD) to capture interview questions automatically.\n"
            "• Scannable first-person bullet points grounded in your resume & codebase stream here."
        )
        left_layout.addWidget(self.answer, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        for label, tooltip, callback in [
            ("Copy", "Copy answer to clipboard (Ctrl+Shift+C)", self.copy_answer),
            ("Short", "Regenerate as 2–3 short spoken bullets", lambda: self.change_style("Short")),
            ("Balanced", "Regenerate as 4–5 balanced spoken bullets", lambda: self.change_style("Balanced")),
            ("Detailed", "Regenerate with deeper technical detail", lambda: self.change_style("Detailed")),
            ("STAR", "Regenerate in Situation · Task · Action · Result format", lambda: self.change_style("STAR")),
            ("Regenerate", "Generate a fresh version of this answer", self.regenerate),
        ]:
            button = QPushButton(label)
            button.setObjectName("kbActionBtn")
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            actions.addWidget(button)
        left_layout.addLayout(actions)
        live_splitter.addWidget(left)

        # Right 32%: Live Evidence Used + Session History Sidebar
        right_sidebar = GlassFrame()
        right_sidebar.setMinimumWidth(260)
        sidebar_layout = QVBoxLayout(right_sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 14)
        sidebar_layout.setSpacing(8)

        sidebar_layout.addWidget(self._section_label("Matched Evidence for This Answer"))
        self.live_evidence_badge = QLabel("Waiting for question…")
        self.live_evidence_badge.setObjectName("muted")
        self.live_evidence_badge.setWordWrap(True)
        sidebar_layout.addWidget(self.live_evidence_badge)

        self.live_context_snippet = QPlainTextEdit()
        self.live_context_snippet.setReadOnly(True)
        self.live_context_snippet.setMinimumHeight(95)
        self.live_context_snippet.setMaximumHeight(140)
        self.live_context_snippet.setPlaceholderText("Matched resume facts & project files used for the current answer appear here.")
        sidebar_layout.addWidget(self.live_context_snippet)

        hist_header = QHBoxLayout()
        hist_header.addWidget(self._section_label("Session Questions"))
        hist_header.addStretch()
        clear = QPushButton("Clear")
        clear.setObjectName("kbActionBtn")
        clear.clicked.connect(self.clear_session)
        hist_header.addWidget(clear)
        sidebar_layout.addLayout(hist_header)

        self.history_list = QListWidget()
        self.history_list.currentRowChanged.connect(self.select_history)
        sidebar_layout.addWidget(self.history_list, 1)

        privacy = QLabel("Local audio · Use tab 2 to manage documents & profile.")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)
        privacy.setContentsMargins(0, 2, 0, 2)
        sidebar_layout.addWidget(privacy)

        live_splitter.addWidget(right_sidebar)
        live_splitter.setStretchFactor(0, 7)
        live_splitter.setStretchFactor(1, 3)
        live_splitter.setSizes([760, 340])
        live_outer.addWidget(live_splitter, 1)
        self.workspace_tabs.addTab(self.live_tab, "🎙️ Live Interview")

        # ================= WORKSPACE 2: KNOWLEDGE & PROFILE (FULL WIDTH) =================
        self.knowledge_panel = KnowledgePanel(self.knowledge_store, self)
        self.knowledge_panel.edit_profile.connect(self.open_profile_editor)
        self.workspace_tabs.addTab(self.knowledge_panel, "📁 Codebase & Resume")

        # ================= WORKSPACE 3: MOCK PRACTICE (FULL WIDTH) =================
        self.practice_panel = PracticePanel(lambda: self.config, self.knowledge_panel.get_context_for_question, self)
        self.practice_panel.suggest_requested.connect(self.use_practice_question)
        self.workspace_tabs.addTab(self.practice_panel, "🎯 Mock Prep & Practice")

        outer.addWidget(self.workspace_tabs, 1)

    def showEvent(self, event):
        super().showEvent(event)
        apply_premium_window_chrome(self, dialog=False)

    def _apply_config(self):
        self.provider_status.setText(f"●  {self.config.provider.title()} · {self.config.model}")
        if getattr(self.knowledge_store, "fallback_warning", None):
            self.status.setText("SQLite storage active · PostgreSQL server offline")
            self.status.setToolTip(self.knowledge_store.fallback_warning)
        self.answer.setFont(QFont("Segoe UI", self.config.font_size))
        self.question.setFont(QFont("Segoe UI", self.config.font_size))
        flags = self.windowFlags()
        flags = flags | Qt.WindowStaysOnTopHint if self.config.always_on_top else flags & ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        # STEALTH_MODE: Uncomment the line below to hide Main Window from Windows taskbar
        # self._apply_win32_toolwindow()
        self._apply_capture_preference()
        self._apply_shortcuts()
        self._register_hotkeys()

    def _apply_win32_toolwindow(self):
        hwnd = int(self.winId())
        if not hwnd:
            return
        try:
            import win32con
            import win32gui
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style = (ex_style | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            win32gui.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE
                | win32con.SWP_NOSIZE
                | win32con.SWP_NOZORDER
                | win32con.SWP_FRAMECHANGED,
            )
        except Exception:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                gwl_exstyle = -20
                ws_ex_toolwindow = 0x00000080
                ws_ex_appwindow = 0x00040000
                swp_flags = 0x0001 | 0x0002 | 0x0004 | 0x0020
                ex = user32.GetWindowLongW(hwnd, gwl_exstyle)
                ex = (ex | ws_ex_toolwindow) & ~ws_ex_appwindow
                user32.SetWindowLongW(hwnd, gwl_exstyle, ex)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        # STEALTH_MODE: Uncomment the line below to hide Main Window from Windows taskbar
        # self._apply_win32_toolwindow()
        self._apply_capture_preference()

    def _setup_tray_icon(self):
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
        from PySide6.QtGui import QAction, QIcon
        from pathlib import Path

        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon_path = Path(__file__).resolve().parent.parent / "assets" / "app-icon.ico"
        icon = QIcon(str(icon_path)) if icon_path.is_file() else self.windowIcon()

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("AI Interview Copilot · Active")

        menu = QMenu()
        toggle_hud_action = QAction("Toggle Live HUD (Ctrl+Shift+Space)", self)
        toggle_hud_action.triggered.connect(self.toggle_compact)
        menu.addAction(toggle_hud_action)

        toggle_main_action = QAction("Show / Hide Main Dashboard", self)
        toggle_main_action.triggered.connect(self._toggle_main_window)
        menu.addAction(toggle_main_action)

        menu.addSeparator()
        quit_action = QAction("Exit App", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _toggle_main_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_compact()

    def _apply_capture_preference(self):
        ok, message = set_capture_exclusion(int(self.winId()), self.config.exclude_from_capture)
        self.capture_status.setText("Capture request set · unverified" if ok and self.config.exclude_from_capture else "Capture: normal" if ok else "Capture request unavailable · visible")
        self.capture_status.setToolTip(message)
        if hasattr(self, "floating"):
            panel_ok, panel_message = self.floating.apply_window_preferences(self.config.compact_always_on_top, self.config.exclude_from_capture)
            if not panel_ok:
                self.capture_status.setText("Capture request unavailable · visible")
                self.capture_status.setToolTip(panel_message)

    def _apply_shortcuts(self):
        for shortcut in getattr(self, "local_shortcuts", []):
            shortcut.setParent(None)
            shortcut.deleteLater()
        self.local_shortcuts = []
        bindings = [
            (self.config.shortcut_toggle_compact, self.toggle_compact),
            (self.config.shortcut_copy_answer, self.copy_answer),
            (self.config.shortcut_pause, self.toggle_pause),
            (self.config.shortcut_submit_question, self.submit_question),
        ]
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self, activated=callback)
            self.local_shortcuts.append(shortcut)

    def _register_hotkeys(self):
        if self._registered_hotkeys:
            unregister_global_hotkeys(int(self.winId()), self._registered_hotkeys)
            self._registered_hotkeys = []
        bindings = {
            0xA01: self.config.shortcut_toggle_compact,
            0xA02: self.config.shortcut_copy_answer,
            0xA03: self.config.shortcut_pause,
        }
        self._registered_hotkeys, errors = register_global_hotkeys(int(self.winId()), bindings)
        self.status.setToolTip("\n".join(errors) if errors else "Global shortcuts are active while the app is open.")
        if errors:
            self.status.setText("Some global shortcuts are unavailable · hover for details")

    def nativeEvent(self, event_type, message):
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == 0x0312:  # WM_HOTKEY
                actions = {0xA01: self.toggle_compact, 0xA02: self.copy_answer, 0xA03: self.toggle_pause}
                action = actions.get(int(msg.wParam))
                if action:
                    action()
                    return True, 0
        except (TypeError, ValueError, OSError):
            pass
        return False, 0

    def closeEvent(self, event):
        if self._continuous_listener is not None:
            self._continuous_listener.stop()
            self._continuous_listener = None
        unregister_global_hotkeys(int(self.winId()), self._registered_hotkeys)
        super().closeEvent(event)

    def restart_app(self):
        reply = QMessageBox.question(
            self,
            "Restart",
            "Restart AI Interview Copilot now? This session's questions and answers will be cleared. Imported documents and your profile stay in the database.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if getattr(sys, "frozen", False):
            exe_path = str(Path(sys.executable).resolve())
            result = QProcess.startDetached(exe_path, [], str(Path(exe_path).parent))
        else:
            root = str(Path(__file__).resolve().parents[2])
            result = QProcess.startDetached(sys.executable, ["-m", "app.main"], root)
        started = result[0] if isinstance(result, tuple) else bool(result)
        if not started:
            QMessageBox.warning(self, "Restart failed", "Could not start a new window. Close this one and run the app again.")
            return
        unregister_global_hotkeys(int(self.winId()), self._registered_hotkeys)
        self._registered_hotkeys = []
        QApplication.quit()

    def open_settings(self):
        previous_db = self.config.database_url
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            dialog.apply_to(self.config)
            try:
                saved_path = save_config(self.config)
                self.status.setText("Settings saved" if ".user_data" not in str(saved_path) else "Settings saved in the local workspace fallback")
            except OSError as exc:
                QMessageBox.warning(self, "Settings not saved", str(exc))
            if self.config.database_url != previous_db:
                try:
                    self.knowledge_store = KnowledgeStore(database_url=self.config.database_url)
                    self.knowledge_panel.store = self.knowledge_store
                    self.knowledge_panel._refresh_documents()
                    self.knowledge_panel._refresh_profile_summary()
                    self._start_embedding_backfill()
                except Exception as exc:
                    QMessageBox.warning(self, "Database connection", str(exc))
            self._apply_config()

    def open_profile_editor(self):
        dialog = ProfileEditor(self.knowledge_store, self)
        if dialog.exec():
            self.knowledge_panel._refresh_profile_summary()
            self.status.setText("Profile saved · answers will use verified facts")

    def use_practice_question(self, question: str):
        self.workspace_tabs.setCurrentIndex(0)
        self.question.setPlainText(question)
        self.submit_question(force=True)

    def transcribe_audio_file(self):
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Transcribe audio",
            "",
            "Audio (*.wav *.mp3 *.m4a *.flac *.ogg *.webm)",
        )
        if path:
            self._transcribe_path(path)

    def _set_auto_listen_state(self, active: bool):
        self.auto_listen_button.setText("Auto-Listen: ON" if active else "Auto-Listen")
        self.auto_listen_button.setObjectName("autoListenActive" if active else "")
        self.auto_listen_button.style().unpolish(self.auto_listen_button)
        self.auto_listen_button.style().polish(self.auto_listen_button)
        if hasattr(self, "floating"):
            self.floating.set_auto_listening(active)

    def toggle_auto_listen(self):
        if self._continuous_listener is not None and self._continuous_listener.is_running:
            self._continuous_listener.stop()
            self._continuous_listener = None
            self._set_auto_listen_state(False)
            self.status.setText("Auto-Listen stopped · Ready")
            if hasattr(self, "floating"):
                self.floating.set_status("Ready")
            return

        if self._recorder is not None:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
            self._set_record_button_state(False)

        def _handle_utterance(samples, source: str = "system"):
            self._utterance_captured.emit((samples, source))

        def _handle_speech_state(active: bool):
            if hasattr(self, "floating"):
                self.floating.set_speaking_state(active)
            if active:
                self.status.setText("● Interviewer speaking (capturing audio)…")
            elif self._continuous_listener and self._continuous_listener.is_running:
                self.status.setText("Auto-Listen ON · listening for question (0.6s pause to answer)…")

        self._continuous_listener = ContinuousListener(
            on_utterance_audio=_handle_utterance,
            on_speech_state=_handle_speech_state,
            source=getattr(self.config, "audio_source", "system"),
            silence_seconds=0.65,
            min_speech_seconds=0.50,
        )
        try:
            self._continuous_listener.start()
        except CaptureError as exc:
            self._continuous_listener = None
            self._set_auto_listen_state(False)
            QMessageBox.warning(self, "Auto-Listen", str(exc))
            return

        self._set_auto_listen_state(True)
        self.status.setText("Auto-Listen ON · listening for question (0.6s pause to answer)…")
        if hasattr(self, "floating"):
            self.floating.set_status("Auto-Listen ON · listening for question…")

    def _on_auto_utterance_audio(self, payload):
        if self.assistant_paused:
            return
        if isinstance(payload, tuple):
            samples, source = payload
        else:
            samples, source = payload, "system"
        worker = _UtteranceTranscribeThread(samples, source=source)
        self._utterance_threads.append(worker)
        worker.finished.connect(self._on_auto_utterance_text)
        worker.finished.connect(lambda text="", src="", w=worker: self._utterance_threads.remove(w) if w in self._utterance_threads else None)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_auto_utterance_text(self, raw_text: str, source: str = "system"):
        # If 'both' is selected and audio came from microphone, it is the CANDIDATE speaking!
        # Log to transcript as Candidate turn, DO NOT submit as a question or regenerate answer!
        if getattr(self.config, "audio_source", "system") == "both" and source == "mic":
            candidate_text = strip_transcript_metadata(raw_text).strip()
            if candidate_text and not is_small_talk_or_mic_check(candidate_text):
                self.session_transcript.append(f"{self.speaker_names[1]}: {candidate_text}")
                self._sync_transcript()
                if hasattr(self, "floating"):
                    self.floating.set_status(f"Candidate: {candidate_text[:40]}…")
                self.status.setText("Candidate spoken answer recorded in transcript (not submitted as question)")
            return

        question = last_question_from_transcript(raw_text)
        if not question or is_small_talk_or_mic_check(question):
            if self._continuous_listener and self._continuous_listener.is_running:
                self.status.setText(f"Auto-Listen ON · ignored greeting ({question[:32]}…)" if question else "Auto-Listen ON · listening…")
            return
        self.question.setPlainText(question)
        if hasattr(self, "floating"):
            self.floating.set_current_question(question)
        self.session_transcript.append(f"{self.speaker_names[0]}: {question}")
        self._sync_transcript()
        self.submit_question()

    def _set_record_button_state(self, active: bool):
        self.record_button.setText("Stop" if active else "Record")
        self.record_button.setObjectName("recording" if active else "")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        if hasattr(self, "floating"):
            self.floating.set_recording(active)

    def simulate_quick_test(self):
        """Simulate an interviewer asking about Nikhil's Trade Advisory platform to test Live HUD streaming."""
        sample_q = "Can you explain how you architected the real-time WebSocket signal streaming with Django Channels and Redis?"
        self.question.setPlainText(sample_q)
        self.open_compact()
        if hasattr(self, "floating"):
            self.floating.set_current_question(sample_q)
            self.floating.set_status("⚡ Generating simulated answer…")
        self.submit_question()

    def toggle_recording(self):
        if self._recorder is None:
            self._recorder = MicrophoneRecorder(source=getattr(self.config, "audio_source", "system"))
            try:
                self._recorder.start()
            except CaptureError as exc:
                self._recorder = None
                QMessageBox.warning(self, "Microphone", str(exc))
                return
            self._set_record_button_state(True)
            self.status.setText("Recording from the microphone… click Stop when the question is finished")
            return
        try:
            path = self._recorder.stop()
        except CaptureError as exc:
            self._recorder = None
            self._set_record_button_state(False)
            QMessageBox.warning(self, "Microphone", str(exc))
            return
        self._recorder = None
        self._set_record_button_state(False)
        self._transcribe_path(path)

    def _transcribe_path(self, path: str):
        if self._transcribe_thread and self._transcribe_thread.isRunning():
            self.status.setText("Please wait for the current transcription")
            return
        self.ask.setEnabled(False)
        self.record_button.setEnabled(False)
        self.status.setText("Transcribing on this PC…")
        self._transcribe_thread = _TranscribeThread(path)
        self._transcribe_thread.finished.connect(self._on_transcript)
        self._transcribe_thread.failed.connect(self._on_transcript_error)
        self._transcribe_thread.finished.connect(self._transcribe_thread.deleteLater)
        self._transcribe_thread.failed.connect(self._transcribe_thread.deleteLater)
        self._transcribe_thread.start()

    def prompt_speaker_names(self):
        first, ok_first = QInputDialog.getText(
            self, "Speaker 1", "Name for Speaker 1:", text=self.speaker_names[0]
        )
        if not ok_first:
            return
        second, ok_second = QInputDialog.getText(
            self, "Speaker 2", "Name for Speaker 2:", text=self.speaker_names[1]
        )
        if not ok_second:
            return
        old_first, old_second = self.speaker_names
        new_first = first.strip() or "Interviewer"
        new_second = second.strip() or "Candidate"
        self.speaker_names = (new_first, new_second)
        updated = []
        for entry in self.session_transcript:
            text = entry.replace(f"{old_first}:", f"{new_first}:").replace(f"{old_second}:", f"{new_second}:")
            text = text.replace("Speaker 1:", f"{new_first}:").replace("Speaker 2:", f"{new_second}:")
            updated.append(text)
        self.session_transcript = updated
        self._sync_transcript()
        self.status.setText(f"Speaker labels set to {new_first} & {new_second}")

    def _rename_speakers(self, transcript: str) -> str:
        if "Speaker 2:" not in transcript:
            return transcript
        first, second = self.speaker_names
        if first.strip():
            transcript = transcript.replace("Speaker 1:", f"{first.strip()}:")
        if second.strip():
            transcript = transcript.replace("Speaker 2:", f"{second.strip()}:")
        return transcript

    def _on_transcript(self, transcript: str):
        transcript = self._rename_speakers(transcript)
        question = last_question_from_transcript(transcript)
        self.question.setPlainText(question)
        if hasattr(self, "floating"):
            self.floating.set_current_question(question)
        self.session_transcript.append(f"Transcript:\n{transcript}")
        self._sync_transcript()
        self.ask.setEnabled(not self.assistant_paused)
        self.record_button.setEnabled(True)
        if question and not is_small_talk_or_mic_check(question) and not self.assistant_paused:
            self.submit_question()
        else:
            self.status.setText("Mic check / greeting ignored · ask an interview question or click Generate")

    def _on_transcript_error(self, message: str):
        self.ask.setEnabled(not self.assistant_paused)
        self.record_button.setEnabled(True)
        self.status.setText("Transcription unavailable")
        QMessageBox.warning(self, "Audio transcription", message)

    def submit_question(self, force=False, style_override: str | None = None):
        if self.assistant_paused:
            self.status.setText("Paused · resume to accept a new question")
            return
        question = self.question.toPlainText().strip()
        if not question:
            self.status.setText("Enter a question first")
            return
        if not force and is_small_talk_or_mic_check(question):
            self.status.setText("Mic check / greeting ignored · ask an interview question")
            return
        if self.thread and self.thread.isRunning():
            self.status.setText("Please wait for the current answer")
            return
        if not force and is_duplicate(question, self.answered_questions):
            self.status.setText("Already answered · use Regenerate for a new version")
            return
        self.last_question = question
        self._question_start_time = time.perf_counter()
        self.answered_questions.append(question)
        self.session_transcript.append(f"Question: {question}")
        self._sync_transcript()
        self.ask.setEnabled(False)
        self.status.setText("Retrieving context…")
        if hasattr(self, "floating"):
            self.floating.set_current_question(question)
            self.floating.set_status("Retrieving context…")
            self.floating.ask.setEnabled(False)

        self.answer.setPlainText("")
        active_style = style_override
        if not active_style:
            try:
                profile = self.knowledge_store.get_full_profile() or {}
                active_style = str(profile.get("preferred_answer_length") or "")
            except Exception:
                active_style = ""
        active_style = active_style or self.config.answer_style
        self.thread = QThread(self)
        self.worker = AnswerWorker(
            question,
            self.config.provider,
            self.config.model,
            active_style,
            self.config.ollama_url,
            "",
            self.config.openrouter_url,
            self.config.groq_url,
            store=self.knowledge_store,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.context_loaded.connect(self._on_context_loaded)
        self.worker.partial.connect(self.on_partial_answer)
        self.worker.finished.connect(self.on_answer)
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, "thread", None))
        self.thread.start()

    def _on_context_loaded(self, context: str, retrieval):
        self.last_context = context
        self.knowledge_panel.set_current_question(self.last_question, precomputed=(context, retrieval))
        if hasattr(self, "live_context_snippet"):
            self.live_context_snippet.setPlainText(context or "No personal document excerpt matched · using general technical knowledge.")
            if retrieval and getattr(retrieval, "has_evidence", False):
                sources = []
                for item in retrieval.items[:4]:
                    if item.source not in sources:
                        sources.append(item.source)
                self.live_evidence_badge.setText(f"{len(retrieval.items)} source(s): " + ", ".join(sources))
            else:
                self.live_evidence_badge.setText("General technical answer · no personal claims")
        if self.config.provider == "ollama":
            self.status.setText("Writing with Ollama…")
        else:
            self.status.setText("Generating answer…")

    def on_partial_answer(self, text):
        self.answer.setPlainText(text)
        self.status.setText("Writing answer…")
        if hasattr(self, "floating"):
            self.floating.set_answer(text)
            self.floating.set_status("Writing answer…")

    def on_answer(self, answer):
        elapsed = max(0.1, time.perf_counter() - getattr(self, "_question_start_time", time.perf_counter()))
        self.answer.setPlainText(answer)
        self.status.setText(f"Answer generated in {elapsed:.1f}s")
        if hasattr(self, "floating"):
            self.floating.set_answer(answer, elapsed_sec=elapsed)
            self.floating.set_status(
                "Audio: Listening"
                if (self._continuous_listener and self._continuous_listener.is_running)
                else f"Answer generated ({elapsed:.1f}s)"
            )
            self.floating.ask.setEnabled(not self.assistant_paused)
        self.ask.setEnabled(not self.assistant_paused)
        self.history.append((self.last_question, answer, datetime.now().strftime("%H:%M"), self.last_context))
        self.session_transcript.append(f"Suggested answer: {answer}")
        self._sync_transcript()
        self.history_list.insertItem(0, f"{self.history[-1][2]}  ·  {self.last_question[:55]}")

    def on_error(self, message):
        self.answer.setPlainText("")
        self.ask.setEnabled(not self.assistant_paused)
        self.status.setText("Could not generate answer")
        if hasattr(self, "floating"):
            self.floating.set_status("Provider error")
            self.floating.ask.setEnabled(not self.assistant_paused)
        QMessageBox.warning(self, "AI provider error", message)

    def copy_answer(self):
        value = self.answer.toPlainText().strip()
        if value:
            QApplication.clipboard().setText(value)
            self.status.setText("Answer copied")

    def regenerate(self):
        if hasattr(self, "last_question"):
            self.question.setPlainText(self.last_question)
            self.submit_question(force=True)

    def change_style(self, style):
        if not hasattr(self, "last_question"):
            self.status.setText("Generate an answer first")
            return
        self.question.setPlainText(self.last_question)
        self.submit_question(force=True, style_override=style)

    def select_history(self, row):
        if row >= 0 and row < len(self.history):
            question, answer, _, context = self.history[-1 - row]
            self.question.setPlainText(question)
            self.answer.setPlainText(answer)
            self.last_context = context
            if hasattr(self, "live_context_snippet"):
                self.live_context_snippet.setPlainText(context or "No personal document excerpt matched.")
            self.knowledge_panel.set_current_question(question)
            if hasattr(self, "floating"):
                self.floating.question.setText(question)
                self.floating.set_answer(answer)

    def clear_session(self):
        self.history.clear()
        self.answered_questions.clear()
        self.session_transcript.clear()
        self.history_list.clear()
        self.question.clear()
        self.answer.clear()
        self.last_context = ""
        if hasattr(self, "live_context_snippet"):
            self.live_context_snippet.clear()
            self.live_evidence_badge.setText("Waiting for question…")
        self.status.setText("Session cleared")
        if hasattr(self, "floating"):
            self.floating.set_transcript("")
            self.floating.set_answer("")
            self.floating.set_current_question("")

    def _sync_transcript(self):
        transcript = "\n\n".join(self.session_transcript)[-6000:]
        if hasattr(self, "floating"):
            self.floating.set_transcript(transcript)

    def set_paused(self, paused):
        self.assistant_paused = bool(paused)
        self.ask.setEnabled(not self.assistant_paused)
        if hasattr(self, "floating"):
            self.floating.set_paused(self.assistant_paused)
        self.status.setText("Paused · new requests are held" if paused else "Ready")

    def toggle_pause(self):
        self.set_paused(not self.assistant_paused)

    def open_compact(self):
        if not hasattr(self, "floating"):
            self.floating = FloatingPanel(self._submit_compact, self.copy_answer, None)
            self.floating.pause_toggled.connect(self.set_paused)
            self.floating.record_toggled.connect(self.toggle_recording)
            self.floating.auto_listen_toggled.connect(self.toggle_auto_listen)
            self.floating.set_paused(self.assistant_paused)
            self.floating.set_recording(self._recorder is not None)
            self.floating.set_auto_listening(
                self._continuous_listener is not None and self._continuous_listener.is_running
            )
        panel_ok, panel_message = self.floating.apply_window_preferences(self.config.compact_always_on_top, self.config.exclude_from_capture)
        if not panel_ok:
            self.capture_status.setText("Capture request unavailable · visible")
            self.capture_status.setToolTip(panel_message)
        self._sync_transcript()
        self.floating.show()

    def toggle_compact(self):
        if hasattr(self, "floating") and self.floating.isVisible():
            self.floating.hide()
        else:
            self.open_compact()

    def _submit_compact(self, question):
        self.question.setPlainText(question)
        self.submit_question()
        if hasattr(self, "floating"):
            if not self.assistant_paused:
                self.floating.set_status("Generating…")
