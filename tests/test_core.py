from app.ai.prompt_builder import build_prompt
from app.config import AppConfig, load_config, save_config
from app.windows import capture_affinity, hotkeys


def test_prompt_avoids_unverified_personal_claims():
    prompt = build_prompt("Tell me about your projects")
    assert "do not invent personal experience" in prompt
    assert "Tell me about your projects" in prompt


def test_prompt_includes_verified_context():
    prompt = build_prompt("What did you build?", context="Implemented a REST endpoint")
    assert "Verified context" in prompt
    assert "Implemented a REST endpoint" in prompt


def test_config_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    config = AppConfig(provider="groq", model="llama-3.3-70b-versatile", font_size=17,
                       compact_always_on_top=False, exclude_from_capture=True,
                       shortcut_toggle_compact="Alt+F8")
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.provider == "groq"
    assert loaded.font_size == 17
    assert loaded.compact_always_on_top is False
    assert loaded.exclude_from_capture is True
    assert loaded.shortcut_toggle_compact == "Alt+F8"


def test_invalid_config_uses_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json", encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_settings_save_uses_local_fallback_when_profile_is_read_only(tmp_path, monkeypatch):
    from app import config as config_module

    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("block", encoding="utf-8")
    fallback = tmp_path / "workspace" / "settings.json"
    monkeypatch.setattr(config_module, "config_path", lambda: blocked_parent / "settings.json")
    monkeypatch.setattr(config_module, "fallback_config_path", lambda: fallback)
    saved = config_module.save_config(AppConfig(shortcut_pause="Ctrl+Alt+J"))
    assert saved == fallback
    assert config_module.load_config().shortcut_pause == "Ctrl+Alt+J"


def test_global_shortcut_parser_requires_modifier():
    modifiers, key = hotkeys.parse_shortcut("Ctrl+Alt+K")
    assert modifiers & hotkeys.MOD_CONTROL
    assert modifiers & hotkeys.MOD_ALT
    assert key == ord("K")
    try:
        hotkeys.parse_shortcut("K")
    except ValueError as exc:
        assert "must include" in str(exc)
    else:
        raise AssertionError("Unmodified global shortcuts should be rejected")


def test_capture_exclusion_reports_api_state_only(monkeypatch):
    import ctypes
    from ctypes import wintypes
    from unittest.mock import MagicMock

    monkeypatch.setattr(capture_affinity.os, "name", "nt")
    state = {"affinity": capture_affinity.WDA_NONE}
    fake = MagicMock()
    fake.SetWindowDisplayAffinity.side_effect = lambda hwnd, value: state.update(affinity=value) or 1

    def get_affinity(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = state["affinity"]
        return 1

    fake.GetWindowDisplayAffinity.side_effect = get_affinity
    ok, message = capture_affinity.set_capture_exclusion(1234, True, api=fake, build=22000)
    assert ok
    assert "unverified" in message
    assert state["affinity"] == capture_affinity.WDA_EXCLUDEFROMCAPTURE


def test_capture_exclusion_uses_visible_fallback_on_old_windows(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(capture_affinity.os, "name", "nt")
    fake = MagicMock()
    ok, message = capture_affinity.set_capture_exclusion(1234, True, api=fake, build=19040)
    assert not ok
    assert "remains visible" in message
    fake.SetWindowDisplayAffinity.assert_not_called()


def test_floating_panel_can_collapse_resume_resize_and_reposition(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.ui.floating_panel import FloatingPanel
    import app.ui.floating_panel as panel_module

    app = QApplication.instance() or QApplication([])
    panel = FloatingPanel(lambda question: None, lambda: None)
    panel.resize(430, 510)
    panel.move(64, 72)
    assert panel.pos().x() == 64 and panel.pos().y() == 72
    monkeypatch.setattr(panel_module, "set_capture_exclusion", lambda hwnd, enabled: (True, "mocked"))
    panel.apply_window_preferences(True, False)
    assert panel.windowFlags() & __import__("PySide6").QtCore.Qt.WindowStaysOnTopHint
    full_size = panel.size()
    panel.toggle_collapse()
    app.processEvents()
    assert panel.collapsed
    panel.toggle_collapse()
    app.processEvents()
    assert not panel.collapsed
    assert panel.size() == full_size
    panel.set_paused(True)
    assert not panel.ask.isEnabled()
    assert panel.pause_button.text() == "Resume"
    panel.set_paused(False)
    assert panel.ask.isEnabled()
    panel.close()


def test_settings_dialog_persists_compact_capture_and_hotkeys():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.ui.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    config = AppConfig()
    dialog = SettingsDialog(config)
    dialog.compact_top.setChecked(False)
    dialog.exclude_capture.setChecked(True)
    dialog.toggle_shortcut.setKeySequence("Alt+F8")
    dialog.copy_shortcut.setKeySequence("Ctrl+Alt+C")
    dialog.pause_shortcut.setKeySequence("Ctrl+Alt+P")
    dialog.submit_shortcut.setKeySequence("Alt+Return")
    dialog.apply_to(config)
    assert config.compact_always_on_top is False
    assert config.exclude_from_capture is True
    assert config.shortcut_toggle_compact == "Alt+F8"
    assert config.shortcut_copy_answer == "Ctrl+Alt+C"
    assert config.shortcut_pause == "Ctrl+Alt+P"
    assert config.shortcut_submit_question == "Alt+Return"
    dialog.close()


def test_dotenv_loader(tmp_path):
    import os
    from app.config import load_dotenv_file

    env_path = tmp_path / ".env"
    env_path.write_text("TEST_MOCK_ENV_KEY_123=test_mock_value_456\n# Comment\n", encoding="utf-8")
    load_dotenv_file(env_path)
    assert os.environ.get("TEST_MOCK_ENV_KEY_123") == "test_mock_value_456"
    del os.environ["TEST_MOCK_ENV_KEY_123"]
