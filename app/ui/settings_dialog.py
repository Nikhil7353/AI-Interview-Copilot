from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import APP_STYLESHEET, DIALOG_BACKDROP_STYLES
from app.windows.dwm_backdrop import apply_premium_window_chrome


class SettingsDialog(QDialog):
    """Modern 3-Tab Settings Dialog: AI Brain | Audio & Live HUD | Storage & Advanced."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings · AI Interview Copilot")
        self.setMinimumWidth(540)
        self.setMinimumHeight(600)
        self.resize(560, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        sheet = QFrame()
        sheet.setObjectName("glassSheet")
        sheet_layout = QVBoxLayout(sheet)
        sheet_layout.setContentsMargins(20, 18, 20, 18)
        sheet_layout.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("title")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.DemiBold))
        sub = QLabel("Configure your AI providers, real-time audio pipeline, Live HUD, and storage.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        sheet_layout.addWidget(title)
        sheet_layout.addWidget(sub)

        # 3 Modern Categorized Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")

        # ================= TAB 1: AI BRAIN =================
        tab_ai = QWidget()
        ai_layout = QVBoxLayout(tab_ai)
        ai_layout.setContentsMargins(12, 16, 12, 14)
        ai_layout.setSpacing(14)

        ai_form = QFormLayout()
        ai_form.setSpacing(12)
        ai_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.provider = QComboBox()
        self.provider.addItem("Groq · ultra-fast live HUD (0.3s)", "groq")
        self.provider.addItem("OpenRouter · cloud models", "openrouter")
        self.provider.addItem("Ollama · local (free)", "ollama")
        self.provider.setCurrentIndex(max(0, self.provider.findData(config.provider)))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        ai_form.addRow("Active AI Provider", self.provider)

        self.model = QLineEdit(config.model)
        self.model.setPlaceholderText("openai/gpt-oss-120b")
        ai_form.addRow("Model Name", self.model)

        # API Key status pills
        groq_key = os.environ.get("GROQ_API_KEY", "")
        or_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.groq_key_label = QLabel(
            f"✓ Active in env ({groq_key[:5]}...{groq_key[-4:]})" if groq_key
            else "⚠️ Not set (Set GROQ_API_KEY in environment for 0.3s live streaming)"
        )
        self.groq_key_label.setStyleSheet("color: #34d399;" if groq_key else "color: #fbbf24;")
        ai_form.addRow("Groq API Key", self.groq_key_label)

        self.or_key_label = QLabel(
            f"✓ Active in env ({or_key[:6]}...{or_key[-4:]})" if or_key
            else "⚠️ Not set (Set OPENROUTER_API_KEY in environment for Nemotron)"
        )
        self.or_key_label.setStyleSheet("color: #34d399;" if or_key else "color: #94a3b8;")
        ai_form.addRow("OpenRouter Key", self.or_key_label)

        self.style = QComboBox()
        self.style.addItems(["Short", "Balanced", "Detailed", "STAR"])
        self.style.setCurrentText(config.answer_style)
        ai_form.addRow("Response Style", self.style)

        self.url = QLineEdit(config.ollama_url)
        self.openrouter_url = QLineEdit(config.openrouter_url)
        self.groq_url = QLineEdit(config.groq_url)
        ai_form.addRow("Groq API URL", self.groq_url)
        ai_form.addRow("OpenRouter URL", self.openrouter_url)
        ai_form.addRow("Ollama URL", self.url)
        ai_layout.addLayout(ai_form)

        ai_note = QLabel(
            "💡 Recommended for live interviews: Groq (openai/gpt-oss-120b) streams full technical answers in ~0.3s with zero delay."
        )
        ai_note.setObjectName("muted")
        ai_note.setWordWrap(True)
        ai_layout.addWidget(ai_note)
        ai_layout.addStretch()
        self.tabs.addTab(tab_ai, "🧠 AI Brain")

        # ================= TAB 2: AUDIO & LIVE HUD =================
        tab_audio = QWidget()
        audio_layout = QVBoxLayout(tab_audio)
        audio_layout.setContentsMargins(12, 16, 12, 14)
        audio_layout.setSpacing(14)

        audio_form = QFormLayout()
        audio_form.setSpacing(12)
        audio_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.audio_source = QComboBox()
        self.audio_source.addItem("System audio only (Recommended for Zoom/Meet/Teams)", "system")
        self.audio_source.addItem("System + Mic (Auto-detect Interviewer vs Candidate)", "both")
        self.audio_source.addItem("Microphone only (Mock interview / offline practice)", "mic")
        self.audio_source.setCurrentIndex(max(0, self.audio_source.findData(getattr(config, "audio_source", "system"))))
        audio_form.addRow("Audio Capture Source", self.audio_source)

        self.font = QSpinBox()
        self.font.setRange(11, 22)
        self.font.setValue(config.font_size)
        audio_form.addRow("HUD Font Size (px)", self.font)

        self.compact_top = QCheckBox("Keep Live HUD overlay always on top")
        self.compact_top.setChecked(config.compact_always_on_top)
        audio_form.addRow("HUD On-Top", self.compact_top)

        self.exclude_capture = QCheckBox("Exclude HUD from screen capture (Zoom / Meet)")
        self.exclude_capture.setChecked(config.exclude_from_capture)
        audio_form.addRow("Stealth Capture", self.exclude_capture)

        self.toggle_shortcut = QKeySequenceEdit(QKeySequence(config.shortcut_toggle_compact))
        self.copy_shortcut = QKeySequenceEdit(QKeySequence(config.shortcut_copy_answer))
        self.pause_shortcut = QKeySequenceEdit(QKeySequence(config.shortcut_pause))
        self.submit_shortcut = QKeySequenceEdit(QKeySequence(config.shortcut_submit_question))

        audio_form.addRow("Toggle Live HUD", self.toggle_shortcut)
        audio_form.addRow("Copy Spoken Answer", self.copy_shortcut)
        audio_form.addRow("Pause / Resume Audio", self.pause_shortcut)
        audio_form.addRow("Submit Question in App", self.submit_shortcut)
        audio_layout.addLayout(audio_form)

        audio_note = QLabel(
            "🔒 System audio loopback captures the interviewer's voice directly from your headphones/speakers without feedback. Toggle HUD visibility anytime using Ctrl+Shift+Space."
        )
        audio_note.setObjectName("muted")
        audio_note.setWordWrap(True)
        audio_layout.addWidget(audio_note)
        audio_layout.addStretch()
        self.tabs.addTab(tab_audio, "🎙️ Audio & Live HUD")

        # ================= TAB 3: STORAGE & ADVANCED =================
        tab_storage = QWidget()
        storage_layout = QVBoxLayout(tab_storage)
        storage_layout.setContentsMargins(12, 16, 12, 14)
        storage_layout.setSpacing(14)

        storage_form = QFormLayout()
        storage_form.setSpacing(12)
        storage_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.use_postgresql = QCheckBox("Use PostgreSQL + pgvector (uncheck for SQLite)")
        self.use_postgresql.setChecked(config.use_postgresql)
        storage_form.addRow("Storage Engine", self.use_postgresql)

        self.database_url = QLineEdit(config.database_url)
        self.database_url.setPlaceholderText("postgresql://postgres:123@localhost:5432/interview_copilot")
        storage_form.addRow("PostgreSQL URL", self.database_url)

        self.top = QCheckBox("Keep main dashboard window on top")
        self.top.setChecked(config.always_on_top)
        storage_form.addRow("Dashboard On-Top", self.top)

        storage_layout.addLayout(storage_form)

        db_note = QLabel(
            "PostgreSQL with pgvector enables high-accuracy semantic vector search across all your resumes and project codebases. If PostgreSQL is offline, the app seamlessly falls back to local SQLite."
        )
        db_note.setObjectName("muted")
        db_note.setWordWrap(True)
        storage_layout.addWidget(db_note)

        capture_warn = QLabel(
            "Screen capture exclusion uses Windows WDA_EXCLUDEFROMCAPTURE. Verify with a quick test call before an actual interview."
        )
        capture_warn.setObjectName("muted")
        capture_warn.setWordWrap(True)
        storage_layout.addWidget(capture_warn)
        storage_layout.addStretch()
        self.tabs.addTab(tab_storage, "⚙️ Storage & Advanced")

        sheet_layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        sheet_layout.addWidget(buttons)
        outer.addWidget(sheet)

        self.setStyleSheet(APP_STYLESHEET + DIALOG_BACKDROP_STYLES)
        self._provider_changed()

    def showEvent(self, event):
        super().showEvent(event)
        apply_premium_window_chrome(self, dialog=True)

    def _provider_changed(self):
        data = self.provider.currentData()
        current_model = self.model.text().strip()
        defaults = {
            "groq": "openai/gpt-oss-120b",
            "openrouter": "nvidia/nemotron-3.5-super-vl:free",
            "ollama": "llama3.2:3b",
        }
        other_defaults = {v for k, v in defaults.items() if k != data}
        if not current_model or current_model in other_defaults:
            self.model.setText(defaults.get(data, "openai/gpt-oss-120b"))
        self.openrouter_url.setEnabled(data == "openrouter")
        self.groq_url.setEnabled(data == "groq")

    def apply_to(self, config):
        config.provider = self.provider.currentData()
        config.model = self.model.text().strip() or (
            "openai/gpt-oss-120b" if config.provider == "groq"
            else "nvidia/nemotron-3.5-super-vl:free" if config.provider == "openrouter"
            else "llama3.2:3b"
        )
        config.ollama_url = self.url.text().strip() or "http://localhost:11434"
        config.openrouter_url = self.openrouter_url.text().strip() or "https://openrouter.ai/api/v1"
        config.groq_url = self.groq_url.text().strip() or "https://api.groq.com/openai/v1"
        config.answer_style = self.style.currentText()
        config.audio_source = self.audio_source.currentData() or "system"
        config.always_on_top = self.top.isChecked()
        config.compact_always_on_top = self.compact_top.isChecked()
        config.exclude_from_capture = self.exclude_capture.isChecked()
        config.shortcut_toggle_compact = self.toggle_shortcut.keySequence().toString(QKeySequence.PortableText)
        config.shortcut_copy_answer = self.copy_shortcut.keySequence().toString(QKeySequence.PortableText)
        config.shortcut_pause = self.pause_shortcut.keySequence().toString(QKeySequence.PortableText)
        config.shortcut_submit_question = self.submit_shortcut.keySequence().toString(QKeySequence.PortableText)
        config.font_size = self.font.value()
        config.use_postgresql = self.use_postgresql.isChecked()
        config.database_url = self.database_url.text().strip() or "postgresql://postgres:123@localhost:5432/interview_copilot"
