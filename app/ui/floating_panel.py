"""Frameless, translucent real-time HUD overlay matching the video reference."""

from __future__ import annotations

try:
    import win32con
    import win32gui
except ImportError:
    win32con = None
    win32gui = None
from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import APP_STYLESHEET
from app.windows.capture_affinity import set_capture_exclusion

HUD_STYLESHEET = """
QFrame#hudContainer {
    background-color: rgba(10, 14, 24, 0.84);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 18px;
}
QFrame#hudQuestionBox {
    background-color: rgba(239, 68, 68, 0.10);
    border: 1px solid rgba(248, 113, 113, 0.32);
    border-radius: 12px;
}
QFrame#hudAnswerBox {
    background-color: rgba(16, 185, 129, 0.07);
    border: 1px solid rgba(52, 211, 153, 0.28);
    border-radius: 14px;
}
QLabel#hudQuestionHeader {
    color: #f87171;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
}
QLabel#hudAnswerHeader {
    color: #34d399;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
}
QLabel#hudSpeakingPulsePill {
    background-color: rgba(16, 185, 129, 0.40);
    border: 1px solid rgba(52, 211, 153, 0.95);
    border-radius: 11px;
    padding: 3px 10px;
    color: #a7f3d0;
    font-size: 11px;
    font-weight: 800;
}
QLabel#hudToastPill {
    background-color: rgba(99, 102, 241, 0.92);
    border: 1px solid rgba(167, 139, 250, 0.95);
    border-radius: 11px;
    padding: 3px 10px;
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#hudZoomBtn {
    background-color: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
    color: #e2e8f0;
}
QToolButton#hudZoomBtn:hover {
    background-color: rgba(255, 255, 255, 0.18);
    border-color: rgba(255, 255, 255, 0.32);
}
QToolButton#hudModeBtn {
    background-color: rgba(99, 102, 241, 0.22);
    border: 1px solid rgba(167, 139, 250, 0.45);
    border-radius: 9px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
    color: #c4b5fd;
}
QToolButton#hudModeBtn:hover {
    background-color: rgba(99, 102, 241, 0.38);
    border-color: rgba(167, 139, 250, 0.75);
    color: #ffffff;
}
QLabel#hudListeningPill {
    background-color: rgba(37, 99, 235, 0.28);
    border: 1px solid rgba(96, 165, 250, 0.65);
    border-radius: 11px;
    padding: 3px 10px;
    color: #bfdbfe;
    font-size: 11px;
    font-weight: 700;
}
QLabel#hudQuestionDetectedPill {
    background-color: rgba(239, 68, 68, 0.32);
    border: 1px solid rgba(248, 113, 113, 0.85);
    border-radius: 11px;
    padding: 3px 10px;
    color: #fecaca;
    font-size: 11px;
    font-weight: 700;
}
QLabel#hudRecordingPill {
    background-color: rgba(220, 38, 38, 0.35);
    border: 1px solid rgba(239, 68, 68, 0.8);
    border-radius: 11px;
    padding: 3px 10px;
    color: #fee2e2;
    font-size: 11px;
    font-weight: 700;
}
QLabel#hudGeneratedPill {
    background-color: rgba(16, 185, 129, 0.25);
    border: 1px solid rgba(52, 211, 153, 0.65);
    border-radius: 11px;
    padding: 3px 10px;
    color: #a7f3d0;
    font-size: 11px;
    font-weight: 700;
}
QLabel#hudShortcutHint {
    color: rgba(190, 200, 225, 0.68);
    font-size: 10px;
    font-weight: 600;
}
QToolButton#hudHideBtn {
    background-color: rgba(239, 68, 68, 0.20);
    border: 1px solid rgba(248, 113, 113, 0.45);
    border-radius: 9px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 700;
    color: #fca5a5;
}
QToolButton#hudHideBtn:hover {
    background-color: rgba(239, 68, 68, 0.38);
    border-color: rgba(248, 113, 113, 0.85);
    color: #ffffff;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 2px 0;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(52, 211, 153, 0.35);
    min-height: 24px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(52, 211, 153, 0.75);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QPlainTextEdit#hudQuestionText {
    background: transparent;
    border: none;
    padding: 2px 4px;
    color: #ffffff;
    font-size: 13px;
    font-weight: 600;
}
QPlainTextEdit#hudAnswerText {
    background: transparent;
    border: none;
    padding: 4px 6px;
    color: #f8fafc;
    font-size: 14px;
}
"""


class FloatingPanel(QMainWindow):
    """Frameless, translucent real-time QUESTION / ANSWER HUD overlay."""

    pause_toggled = Signal(bool)
    record_toggled = Signal()
    auto_listen_toggled = Signal()

    def __init__(self, submit, copy, parent=None):
        super().__init__(
            parent,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.submit_callback = submit
        self.copy_callback = copy
        self.collapsed = False
        self.paused = False
        self.teleprompter_mode = False
        self.hud_font_size = 14
        self._drag_offset: QPoint | None = None
        self._expanded_size = None
        self.setWindowTitle("Interview Copilot · Live HUD")
        self.resize(780, 520)
        self.setMinimumSize(460, 180)
        self.setWindowOpacity(0.92)
        self.setStyleSheet(APP_STYLESHEET + HUD_STYLESHEET)

        outer_host = QWidget()
        outer_layout = QVBoxLayout(outer_host)
        outer_layout.setContentsMargins(6, 6, 6, 6)

        self.container = QFrame()
        self.container.setObjectName("hudContainer")
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # ---- Top HUD Bar (Draggable) ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.status = QLabel("● Audio: Ready")
        self.status.setObjectName("hudListeningPill")
        self.status.setFixedHeight(24)
        bar.addWidget(self.status)

        self.speed_badge = QLabel("")
        self.speed_badge.setObjectName("hudGeneratedPill")
        self.speed_badge.setFixedHeight(24)
        self.speed_badge.hide()
        bar.addWidget(self.speed_badge)

        self.copy_toast = QLabel("")
        self.copy_toast.setObjectName("hudToastPill")
        self.copy_toast.setFixedHeight(24)
        self.copy_toast.hide()
        bar.addWidget(self.copy_toast)

        bar.addStretch(1)

        self.btn_zoom_out = QToolButton()
        self.btn_zoom_out.setObjectName("hudZoomBtn")
        self.btn_zoom_out.setText("A-")
        self.btn_zoom_out.setToolTip("Decrease HUD text font size")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom_font(-1))
        bar.addWidget(self.btn_zoom_out)

        self.btn_zoom_in = QToolButton()
        self.btn_zoom_in.setObjectName("hudZoomBtn")
        self.btn_zoom_in.setText("A+")
        self.btn_zoom_in.setToolTip("Increase HUD text font size")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom_font(+1))
        bar.addWidget(self.btn_zoom_in)

        opacity_label = QLabel("Opacity")
        opacity_label.setObjectName("hudShortcutHint")
        bar.addWidget(opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(45, 100)
        self.opacity_slider.setValue(92)
        self.opacity_slider.setFixedWidth(64)
        self.opacity_slider.setToolTip("Adjust HUD see-through transparency over Google Meet / Zoom")
        self.opacity_slider.valueChanged.connect(lambda val: self.setWindowOpacity(val / 100.0))
        bar.addWidget(self.opacity_slider)

        self.teleprompter_button = QToolButton()
        self.teleprompter_button.setObjectName("hudModeBtn")
        self.teleprompter_button.setText("Mini")
        self.teleprompter_button.setToolTip("Teleprompter Mode: compact strip placed right under webcam")
        self.teleprompter_button.clicked.connect(self.toggle_teleprompter)
        bar.addWidget(self.teleprompter_button)

        self.hide_button = QToolButton()
        self.hide_button.setObjectName("hudHideBtn")
        self.hide_button.setText("👁 Hide")
        self.hide_button.setToolTip("Hide HUD overlay (Toggle anytime with Ctrl+Shift+Space)")
        self.hide_button.clicked.connect(self.hide)
        bar.addWidget(self.hide_button)

        self.collapse_button = QToolButton()
        self.collapse_button.setText("Collapse")
        self.collapse_button.clicked.connect(self.toggle_collapse)
        bar.addWidget(self.collapse_button)

        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setToolTip("Hide HUD (Ctrl+Shift+Space)")
        close_btn.clicked.connect(self.hide)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        # ---- Main HUD Body (QUESTION + ANSWER blocks) ----
        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 2, 0, 0)
        content_layout.setSpacing(8)

        # 1. QUESTION Block (Red / Coral Header like Video 2)
        self.q_box = QFrame()
        self.q_box.setObjectName("hudQuestionBox")
        q_box_layout = QVBoxLayout(self.q_box)
        q_box_layout.setContentsMargins(12, 8, 12, 8)
        q_box_layout.setSpacing(4)

        q_header_row = QHBoxLayout()
        q_header = QLabel("❓ QUESTION")
        q_header.setObjectName("hudQuestionHeader")
        q_header_row.addWidget(q_header)
        q_header_row.addStretch()
        q_hint = QLabel("Live speech or type below")
        q_hint.setObjectName("hudShortcutHint")
        q_header_row.addWidget(q_hint)
        q_box_layout.addLayout(q_header_row)

        self.question = QPlainTextEdit()
        self.question.setObjectName("hudQuestionText")
        self.question.setMaximumHeight(44)
        self.question.setPlaceholderText("Spoken interview question appears here automatically (or type & press Enter)…")
        self.question.text = lambda: self.question.toPlainText().strip()
        self.question.setText = lambda t: self.question.setPlainText(t)

        orig_key_press = self.question.keyPressEvent

        def _question_key_press(event):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self.submit()
                    return
            orig_key_press(event)

        self.question.keyPressEvent = _question_key_press
        q_box_layout.addWidget(self.question)
        content_layout.addWidget(self.q_box)

        # 2. ANSWER Block (Green Lightbulb Header + Bulleted Spoken Points like Video 2)
        a_box = QFrame()
        a_box.setObjectName("hudAnswerBox")
        a_box_layout = QVBoxLayout(a_box)
        a_box_layout.setContentsMargins(12, 10, 12, 10)
        a_box_layout.setSpacing(4)

        a_header_row = QHBoxLayout()
        a_header = QLabel("💡 ANSWER")
        a_header.setObjectName("hudAnswerHeader")
        a_header_row.addWidget(a_header)
        a_header_row.addStretch()
        a_shortcuts = QLabel("Copy: Ctrl+Shift+C  ·  Hide: Ctrl+Shift+Space")
        a_shortcuts.setObjectName("hudShortcutHint")
        a_header_row.addWidget(a_shortcuts)
        a_box_layout.addLayout(a_header_row)

        self.answer = QTextEdit()
        self.answer.setObjectName("hudAnswerText")
        self.answer.setReadOnly(True)
        self.answer.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.answer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.answer.text = lambda: self.answer.toPlainText().strip()
        self.answer.setText = lambda t: self.answer.setPlainText(t)
        self.answer.setPlaceholderText(
            "• Turn on Auto-Listen (or speak a question).\n"
            "• Real-time bulleted talking points grounded in your resume & codebase stream here."
        )
        a_box_layout.addWidget(self.answer, 1)
        content_layout.addWidget(a_box, 1)

        # Keep hidden transcript buffer for backward compatibility with tests/sync
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.hide()

        # ---- Bottom Action Bar ----
        self.actions_widget = QWidget()
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.auto_button = QPushButton("Auto-Listen")
        self.auto_button.clicked.connect(self.auto_listen_toggled.emit)
        self.ask = QPushButton("Generate")
        self.ask.setObjectName("primary")
        self.ask.clicked.connect(self.submit)
        self.record_button = QPushButton("Record")
        self.record_button.clicked.connect(self.record_toggled.emit)
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self._on_copy_clicked)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_pause)
        actions.addWidget(self.auto_button)
        actions.addWidget(self.ask)
        actions.addWidget(self.record_button)
        actions.addWidget(copy_button)
        actions.addWidget(self.pause_button)
        content_layout.addWidget(self.actions_widget)

        layout.addWidget(self.content, 1)
        outer_layout.addWidget(self.container)
        self.setCentralWidget(outer_host)

        # STEALTH MODE: Uncomment lines below to hide from Windows taskbar and exclude from capture
        # hwnd = int(self.winId())
        # self._apply_win32_toolwindow()
        # set_capture_exclusion(hwnd, True)

    # ---- Dragging support for frameless HUD ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _on_copy_clicked(self):
        self.copy_callback()
        self.show_toast("✓ Copied talking points!")

    def show_toast(self, text: str):
        self.copy_toast.setText(text)
        self.copy_toast.show()
        QTimer.singleShot(1800, self.copy_toast.hide)

    def zoom_font(self, delta: int):
        self.hud_font_size = max(11, min(24, self.hud_font_size + delta))
        font = self.answer.font()
        font.setPointSize(self.hud_font_size)
        self.answer.setFont(font)
        self.answer.document().setDefaultFont(font)
        self._auto_fit_answer()
        self.show_toast(f"Font: {self.hud_font_size}px")

    def toggle_teleprompter(self):
        self.teleprompter_mode = not getattr(self, "teleprompter_mode", False)
        if self.teleprompter_mode:
            self.q_box.hide()
            self.actions_widget.hide()
            self.teleprompter_button.setText("Full")
            self.teleprompter_button.setToolTip("Switch back to Full HUD")
            self._expanded_size = self.size()
            self.resize(max(520, self.width()), 280)
            self._auto_fit_answer()
            self.show_toast("Teleprompter Mode Active")
        else:
            self.q_box.show()
            self.actions_widget.show()
            self.teleprompter_button.setText("Mini")
            self.teleprompter_button.setToolTip("Switch to compact Teleprompter mode (under webcam)")
            if self._expanded_size:
                self.resize(self._expanded_size)
            else:
                self.resize(max(780, self.width()), 520)
            self._auto_fit_answer()

    def set_speaking_state(self, active: bool):
        if self.paused:
            return
        if active:
            self.status.setObjectName("hudSpeakingPulsePill")
            self.status.setText("● Speaking (Interviewer)")
        else:
            self.status.setObjectName("hudListeningPill")
            self.status.setText("● Listening (System Audio)")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def submit(self):
        self.submit_callback(self.question.text())

    def _auto_fit_answer(self):
        """Schedule layout measurement on next event loop tick so Qt's scrollbar range is exact."""
        QTimer.singleShot(0, self._do_auto_fit)

    def _do_auto_fit(self):
        """Expand HUD height to comfortably display all bullets with zero scrolling."""
        try:
            sb = self.answer.verticalScrollBar()
            extra = sb.maximum()
            if getattr(self, "teleprompter_mode", False):
                if extra > 0:
                    target_h = min(500, self.height() + extra + 18)
                    self.resize(self.width(), target_h)
            elif not getattr(self, "collapsed", False):
                if extra > 0:
                    target_h = min(720, self.height() + extra + 20)
                    self.resize(self.width(), target_h)
                elif self.height() < 520:
                    self.resize(self.width(), 520)
            sb.setValue(0)
        except Exception:
            pass

    def set_answer(self, value: str, elapsed_sec: float | None = None):
        if value.strip():
            self.answer.setMarkdown(value)
            self._auto_fit_answer()
            self.answer.verticalScrollBar().setValue(0)
        else:
            self.answer.clear()

        if elapsed_sec is not None and value.strip():
            self.speed_badge.setText(f"✓ Ready in {elapsed_sec:.1f}s")
            self.speed_badge.show()

    def set_transcript(self, value: str):
        self.transcript.setPlainText(value)

    def set_current_question(self, value: str):
        self.question.setText(value)

    def _apply_win32_toolwindow(self):
        hwnd = int(self.winId())
        if not hwnd:
            return
        try:
            if win32gui is not None and win32con is not None:
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
            else:
                import ctypes
                user32 = ctypes.windll.user32
                gwl_exstyle = -20
                ws_ex_toolwindow = 0x00000080
                ws_ex_appwindow = 0x00040000
                swp_flags = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED
                ex = user32.GetWindowLongW(hwnd, gwl_exstyle)
                ex = (ex | ws_ex_toolwindow) & ~ws_ex_appwindow
                user32.SetWindowLongW(hwnd, gwl_exstyle, ex)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, swp_flags)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # STEALTH MODE: Uncomment to force taskbar suppression and capture exclusion on show
        # hwnd = int(self.winId())
        # if hwnd:
        #     self._apply_win32_toolwindow()
        #     set_capture_exclusion(hwnd, True)

    def set_status(self, value: str):
        val_lower = value.lower()
        if "question" in val_lower or "detected" in val_lower:
            self.status.setObjectName("hudQuestionDetectedPill")
            self.status.setText("🔥 Question detected")
        elif "writing" in val_lower or "generating" in val_lower or "retrieving" in val_lower:
            self.status.setObjectName("hudListeningPill")
            self.status.setText("⚡ Generating answer…")
        elif "ready" in val_lower or "generated" in val_lower or "answer ready" in val_lower:
            self.status.setObjectName("hudGeneratedPill")
            self.status.setText("✓ Ready")
        elif "recording" in val_lower:
            self.status.setObjectName("hudRecordingPill")
            self.status.setText("● Recording mic…")
        elif "auto" in val_lower or "listening" in val_lower:
            self.status.setObjectName("hudListeningPill")
            self.status.setText("● Auto-Listen: ON")
        else:
            self.status.setObjectName("hudListeningPill")
            short = value if len(value) <= 36 else value[:34] + "…"
            self.status.setText(f"● {short}" if not short.startswith("●") else short)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_paused(self, paused: bool):
        self.paused = paused
        self.ask.setEnabled(not paused)
        self.pause_button.setText("Resume" if paused else "Pause")
        self.set_status("Paused · held" if paused else "Audio: Ready")

    def set_recording(self, active: bool):
        self.record_button.setText("Stop" if active else "Record")
        self.record_button.setObjectName("recording" if active else "")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        if active:
            self.set_status("Audio: Recording…")

    def set_auto_listening(self, active: bool):
        self.auto_button.setText("Auto: ON" if active else "Auto-Listen")
        self.auto_button.setObjectName("autoListenActive" if active else "")
        self.auto_button.style().unpolish(self.auto_button)
        self.auto_button.style().polish(self.auto_button)
        if active:
            self.set_status("Audio: Listening")

    def toggle_pause(self):
        self.pause_toggled.emit(not self.paused)

    def toggle_collapse(self):
        if self.collapsed:
            self.content.show()
            self.collapse_button.setText("Collapse")
            if self._expanded_size:
                self.resize(self._expanded_size)
        else:
            self._expanded_size = self.size()
            self.content.hide()
            self.collapse_button.setText("Expand")
            self.resize(max(360, self.width()), 56)
        self.collapsed = not self.collapsed

    def apply_window_preferences(self, always_on_top: bool, exclude_from_capture: bool):
        was_visible = self.isVisible()
        flags = Qt.Tool | Qt.FramelessWindowHint
        if always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # STEALTH MODE: Uncomment to re-apply taskbar suppression when preferences change
        # self._apply_win32_toolwindow()
        if was_visible:
            self.show()
        hwnd = int(self.winId())
        return set_capture_exclusion(hwnd, exclude_from_capture)
