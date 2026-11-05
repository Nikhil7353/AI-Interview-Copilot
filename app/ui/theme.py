"""Premium glassmorphism theme: aurora backdrop + shared Qt stylesheets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QWidget


class GlassFrame(QFrame):
    """Frosted panel with a bright top edge (glass rim)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -2, -2)
        radius = 20

        fill = QLinearGradient(0, rect.top(), 0, rect.bottom())
        fill.setColorAt(0.0, QColor(255, 255, 255, 28))
        fill.setColorAt(0.08, QColor(255, 255, 255, 14))
        fill.setColorAt(1.0, QColor(255, 255, 255, 6))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        painter.drawRoundedRect(rect, radius, radius)

        rim = QLinearGradient(0, rect.top(), rect.width(), rect.top())
        rim.setColorAt(0.0, QColor(255, 255, 255, 0))
        rim.setColorAt(0.35, QColor(255, 255, 255, 90))
        rim.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(QPen(rim, 1.5))
        painter.drawLine(rect.left() + radius, rect.top() + 1, rect.right() - radius, rect.top() + 1)
        painter.end()


class GlassCanvas(QWidget):
    """Paints a soft mesh-gradient backdrop; glass panels sit on top."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        painter.fillRect(rect, QColor(7, 9, 18))

        def orb(cx: float, cy: float, radius: float, color: QColor) -> None:
            grad = QRadialGradient(cx, cy, radius)
            grad.setColorAt(0.0, color)
            grad.setColorAt(0.55, QColor(color.red(), color.green(), color.blue(), max(0, color.alpha() // 3)))
            grad.setColorAt(1.0, Qt.GlobalColor.transparent)
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        orb(w * 0.12, h * 0.08, min(w, h) * 0.42, QColor(99, 102, 241, 70))
        orb(w * 0.88, h * 0.15, min(w, h) * 0.48, QColor(167, 139, 250, 55))
        orb(w * 0.55, h * 1.02, min(w, h) * 0.55, QColor(56, 189, 248, 45))
        orb(w * 0.02, h * 0.72, min(w, h) * 0.38, QColor(244, 114, 182, 35))
        orb(w * 0.72, h * 0.78, min(w, h) * 0.32, QColor(129, 140, 248, 40))

        painter.end()


APP_STYLESHEET = """
QMainWindow, QDialog {
    background: transparent;
}
QWidget {
    background: transparent;
    color: #eef0f8;
    font-family: 'Segoe UI', 'Inter', sans-serif;
}
QFrame#card {
    background: transparent;
    border: none;
}
QFrame#glassSheet {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 18px;
}
QFormLayout QLabel {
    color: rgba(200, 208, 230, 0.88);
    font-size: 12px;
    font-weight: 600;
}
QLabel#title {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.6px;
    color: #f8f9ff;
}
QLabel#subtitle {
    font-size: 14px;
    color: rgba(220, 226, 245, 0.62);
    font-weight: 400;
}
QLabel#muted {
    color: rgba(180, 188, 210, 0.72);
    font-size: 12px;
}
QLabel#sectionLabel {
    color: rgba(230, 234, 248, 0.88);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.02em;
}
QLabel#statusPill {
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 4px 12px;
    color: rgba(215, 222, 242, 0.9);
    font-size: 11px;
    font-weight: 600;
}
QLabel#liveStatusText {
    background: transparent;
    border: none;
    padding: 2px 4px;
    color: #a5b4fc;
    font-size: 12px;
    font-weight: 600;
}
QListWidget {
    background-color: rgba(8, 12, 24, 0.42);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 6px;
}
QListWidget::item {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.05);
    padding: 8px 12px;
    margin: 3px 2px;
    border-radius: 8px;
    color: #eef0f8;
}
QListWidget::item:hover {
    background-color: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.12);
}
QListWidget::item:selected {
    background-color: rgba(129, 140, 248, 0.28);
    border-color: rgba(167, 139, 250, 0.55);
    color: #ffffff;
}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QKeySequenceEdit {
    background-color: rgba(8, 12, 24, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    padding: 12px 14px;
    color: #f0f2fa;
    selection-background-color: rgba(129, 140, 248, 0.45);
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QKeySequenceEdit:focus {
    border: 1px solid rgba(167, 139, 250, 0.65);
    background-color: rgba(10, 14, 28, 0.72);
}
QComboBox {
    background-color: rgba(8, 12, 24, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    padding: 9px 12px;
    color: #f0f2fa;
    min-height: 20px;
}
QComboBox:hover, QComboBox:focus {
    border: 1px solid rgba(167, 139, 250, 0.55);
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox QAbstractItemView {
    background-color: rgba(14, 18, 32, 0.96);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
    color: #eef0f8;
    selection-background-color: rgba(129, 140, 248, 0.35);
}
QPushButton {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 12px;
    padding: 10px 18px;
    font-size: 13px;
    font-weight: 600;
    color: #eef0f8;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.22);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 0.04);
}
QPushButton:disabled {
    background-color: rgba(255, 255, 255, 0.03);
    color: rgba(180, 188, 210, 0.45);
    border-color: rgba(255, 255, 255, 0.06);
}
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(167, 139, 250, 0.95),
        stop:0.45 rgba(129, 140, 248, 0.95),
        stop:1 rgba(99, 102, 241, 0.95));
    border: 1px solid rgba(255, 255, 255, 0.28);
    color: #ffffff;
    font-weight: 700;
    padding: 11px 20px;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #c4b5fd,
        stop:0.5 #a5b4fc,
        stop:1 #818cf8);
    border-color: rgba(255, 255, 255, 0.38);
}
QPushButton#primary:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #8b5cf6,
        stop:1 #6366f1);
}
QPushButton#recording {
    background-color: rgba(239, 68, 68, 0.22);
    border: 1px solid rgba(248, 113, 113, 0.65);
    color: #fecaca;
    font-weight: 700;
}
QPushButton#recording:hover {
    background-color: rgba(239, 68, 68, 0.32);
    border-color: rgba(248, 113, 113, 0.85);
}
QPushButton#autoListenActive {
    background-color: rgba(16, 185, 129, 0.24);
    border: 1px solid rgba(52, 211, 153, 0.75);
    color: #a7f3d0;
    font-weight: 700;
}
QPushButton#autoListenActive:hover {
    background-color: rgba(16, 185, 129, 0.34);
    border-color: rgba(52, 211, 153, 0.92);
}
QPushButton#navTab {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 12px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    color: rgba(200, 210, 235, 0.85);
}
QPushButton#navTab:hover {
    background-color: rgba(255, 255, 255, 0.09);
    color: #ffffff;
}
QPushButton#navTabActive {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(167, 139, 250, 0.42),
        stop:1 rgba(99, 102, 241, 0.42));
    border: 1px solid rgba(167, 139, 250, 0.65);
    border-radius: 12px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
}
QFrame#subCard {
    background-color: rgba(8, 12, 24, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 14px;
}
QPushButton#kbActionBtn {
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 600;
    border-radius: 10px;
}
QToolButton {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    padding: 8px 12px;
    font-weight: 600;
    color: #eef0f8;
}
QToolButton:hover {
    background-color: rgba(255, 255, 255, 0.1);
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 16px;
    background-color: rgba(255, 255, 255, 0.03);
    top: -1px;
}
QTabBar::tab {
    background-color: rgba(255, 255, 255, 0.04);
    color: rgba(190, 198, 220, 0.85);
    padding: 11px 20px;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    margin-right: 8px;
    font-weight: 600;
    font-size: 13px;
    border: 1px solid transparent;
}
QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(167, 139, 250, 0.35),
        stop:1 rgba(99, 102, 241, 0.35));
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.18);
}
QTabBar::tab:hover:!selected {
    background-color: rgba(255, 255, 255, 0.08);
    color: #e8ecfa;
}
QSplitter::handle {
    background: transparent;
    width: 14px;
}
QHeaderView::section {
    background: transparent;
    border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 7px 10px;
    font-weight: 700;
    color: rgba(180, 188, 210, 0.85);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
QTableWidget {
    background-color: rgba(8, 12, 24, 0.4);
    alternate-background-color: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    gridline-color: rgba(255, 255, 255, 0.05);
    selection-background-color: rgba(129, 140, 248, 0.22);
}
QTableWidget::item {
    padding: 4px 10px;
    border: none;
    color: #eef0f8;
}
QTableWidget::item:selected {
    background-color: rgba(129, 140, 248, 0.28);
    color: #ffffff;
}
QGroupBox {
    background-color: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    margin-top: 18px;
    font-weight: 700;
    font-size: 15px;
    color: rgba(220, 226, 245, 0.92);
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 10px;
    color: rgba(190, 198, 220, 0.9);
}
QCheckBox {
    color: rgba(220, 226, 245, 0.9);
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.2);
    background-color: rgba(8, 12, 24, 0.5);
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a78bfa, stop:1 #6366f1);
    border-color: rgba(255, 255, 255, 0.25);
}
QScrollBar:vertical {
    background: rgba(255, 255, 255, 0.02);
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.16);
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(167, 139, 250, 0.45);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: rgba(255, 255, 255, 0.02);
    height: 8px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 0.16);
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: rgba(167, 139, 250, 0.45);
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::sub-page, QScrollBar::add-page {
    background: transparent;
}
QDialogButtonBox QPushButton:default {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a78bfa, stop:1 #6366f1);
    border: 1px solid rgba(255, 255, 255, 0.25);
    color: #ffffff;
    font-weight: 700;
}
QProgressBar {
    background-color: rgba(8, 12, 24, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 7px;
    height: 14px;
    text-align: center;
    font-size: 10px;
    font-weight: 700;
    color: #ffffff;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a78bfa, stop:1 #6366f1);
    border-radius: 6px;
}
"""

KNOWLEDGE_PANEL_STYLES = """
QGroupBox#kbCard {
    background-color: rgba(255, 255, 255, 0.02);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    margin-top: 10px;
    padding-top: 6px;
    font-weight: 700;
    font-size: 13px;
    color: rgba(220, 226, 245, 0.92);
}
QGroupBox#kbCard::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: rgba(190, 198, 220, 0.88);
}
QPushButton#kbActionBtn {
    padding: 7px 12px;
    font-size: 12px;
    border-radius: 10px;
}
QLabel#kbTitle { color: #f8f9ff; font-weight: 700; }
QLabel#kbMuted { color: rgba(180, 188, 210, 0.75); font-size: 12px; }
"""

DIALOG_BACKDROP_STYLES = """
QDialog {
    background-color: rgba(8, 10, 20, 0.72);
}
"""
