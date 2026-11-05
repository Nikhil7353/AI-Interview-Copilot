import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.ui.main_window import MainWindow

APP_USER_MODEL_ID = "AI.InterviewCopilot"


def _apply_app_icon(application: QApplication) -> None:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    candidates = [
        Path(__file__).resolve().parent / "assets" / "app-icon.ico",
        Path(getattr(sys, "_MEIPASS", "")) / "assets" / "app-icon.ico",
    ]
    icon_file = next((path for path in candidates if path.is_file()), None)
    if icon_file is not None:
        application.setWindowIcon(QIcon(str(icon_file)))


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("AI Interview Copilot")
    application.setQuitOnLastWindowClosed(False)
    _apply_app_icon(application)
    window = MainWindow(load_config())
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
