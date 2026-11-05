"""Mock interview practice: answer first, then get feedback or a suggested answer."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import GlassFrame

from app.ai.providers import ProviderError, generate_from_prompt, iter_ollama_response
from app.interview.evaluation import build_evaluation_prompt
from app.interview.questions import CATEGORIES, next_question


class _FeedbackWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)
    partial = Signal(str)

    def __init__(self, question: str, answer: str, get_context, config):
        super().__init__()
        self.question = question
        self.answer = answer
        self.get_context = get_context
        self.config = config

    def run(self):
        try:
            context = self.get_context(self.question) if self.get_context else ""
            prompt = build_evaluation_prompt(self.question, self.answer, context)
            if self.config.provider == "ollama":
                parts: list[str] = []
                for piece in iter_ollama_response(prompt, self.config.model, self.config.ollama_url, max_tokens=280):
                    parts.append(piece)
                    self.partial.emit("".join(parts))
                text = "".join(parts).strip()
                if not text:
                    raise ProviderError("Ollama returned empty feedback. Confirm the model is available and try again.")
                self.finished.emit(text)
                return
            text = generate_from_prompt(
                prompt,
                self.config.provider,
                self.config.model,
                self.config.ollama_url,
                self.config.openrouter_url,
                self.config.groq_url,
            )
            self.finished.emit(text)
        except ProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected error: {exc}")


class PracticePanel(QWidget):
    suggest_requested = Signal(str)

    def __init__(self, get_config, get_context, parent=None):
        super().__init__(parent)
        self.get_config = get_config
        self.get_context = get_context
        self.seen: set[str] = set()
        self._worker = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---- Left Column: Question + Candidate Answer ----
        left_card = GlassFrame()
        left = QVBoxLayout(left_card)
        left.setContentsMargins(18, 18, 18, 18)
        left.setSpacing(10)

        header_row = QHBoxLayout()
        title = QLabel("Mock Interview Question")
        title.setObjectName("sectionLabel")
        header_row.addWidget(title)
        header_row.addStretch()
        self.category = QComboBox()
        self.category.addItems(list(CATEGORIES))
        header_row.addWidget(self.category)
        nxt = QPushButton("Next question")
        nxt.clicked.connect(self.ask_next)
        header_row.addWidget(nxt)
        left.addLayout(header_row)

        self.prompt = QPlainTextEdit()
        self.prompt.setReadOnly(True)
        self.prompt.setPlaceholderText("A practice question will appear here.")
        self.prompt.setMaximumHeight(88)
        left.addWidget(self.prompt)

        your_answer_label = QLabel("Your spoken / written answer")
        your_answer_label.setObjectName("sectionLabel")
        left.addWidget(your_answer_label)
        self.candidate = QPlainTextEdit()
        self.candidate.setPlaceholderText("Write your answer here before checking it against your resume & project context…")
        left.addWidget(self.candidate, 1)

        actions = QHBoxLayout()
        self.check = QPushButton("Check my answer")
        self.check.setObjectName("primary")
        self.check.clicked.connect(self.check_answer)
        suggest = QPushButton("Send to Live Copilot & Generate")
        suggest.clicked.connect(self.request_suggestion)
        actions.addWidget(self.check)
        actions.addWidget(suggest)
        left.addLayout(actions)
        splitter.addWidget(left_card)

        # ---- Right Column: Coach Feedback ----
        right_card = GlassFrame()
        right = QVBoxLayout(right_card)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)

        feedback_label = QLabel("AI Coach Feedback (Grounded in Your Verified Context)")
        feedback_label.setObjectName("sectionLabel")
        right.addWidget(feedback_label)
        note = QLabel("Evaluates clarity, technical depth, and whether your claims match your verified resume & codebase.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        right.addWidget(note)

        self.feedback = QPlainTextEdit()
        self.feedback.setReadOnly(True)
        self.feedback.setPlaceholderText("Coach feedback streams here when you click 'Check my answer'.")
        right.addWidget(self.feedback, 1)
        self.status = QLabel("Ready")
        self.status.setObjectName("muted")
        right.addWidget(self.status)
        splitter.addWidget(right_card)

        splitter.setSizes([580, 520])
        outer.addWidget(splitter, 1)
        self.ask_next()

    def ask_next(self):
        question = next_question(self.category.currentText(), self.seen)
        self.prompt.setPlainText(question)
        self.candidate.clear()
        self.feedback.clear()
        self.status.setText("Write your answer, then check it")

    def request_suggestion(self):
        question = self.prompt.toPlainText().strip()
        if not question:
            self.status.setText("Get a practice question first")
            return
        self.suggest_requested.emit(question)

    def check_answer(self):
        question = self.prompt.toPlainText().strip()
        answer = self.candidate.toPlainText().strip()
        if not question or not answer:
            self.status.setText("Write your answer before checking it")
            return
        if self._worker and self._worker.isRunning():
            self.status.setText("Please wait for the current feedback")
            return
        self.check.setEnabled(False)
        self.status.setText("Reviewing your answer…")
        self._worker = _FeedbackWorker(question, answer, self.get_context, self.get_config())
        self._worker.partial.connect(self.feedback.setPlainText)
        self._worker.finished.connect(self._on_feedback)
        self._worker.failed.connect(self._on_error)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_feedback(self, text: str):
        self.feedback.setPlainText(text)
        self.check.setEnabled(True)
        self.status.setText("Feedback ready")

    def _on_error(self, message: str):
        self.check.setEnabled(True)
        self.status.setText("Could not review the answer")
        self.feedback.setPlainText(message)
