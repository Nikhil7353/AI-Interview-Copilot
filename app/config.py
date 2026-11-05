"""Small, user-local configuration store."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def load_dotenv_file(path: Path | None = None) -> None:
    """Load key-value pairs from a .env file into os.environ if not already set."""
    target = path or Path(__file__).resolve().parents[1] / ".env"
    if not target.is_file():
        return
    try:
        content = target.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


# Auto-load on import
load_dotenv_file()


@dataclass
class AppConfig:
    provider: str = "ollama"
    model: str = "llama3.2:3b"
    ollama_url: str = "http://localhost:11434"
    openrouter_url: str = "https://openrouter.ai/api/v1"
    groq_url: str = "https://api.groq.com/openai/v1"
    answer_style: str = "Balanced"
    always_on_top: bool = False
    compact_always_on_top: bool = True
    exclude_from_capture: bool = True
    shortcut_toggle_compact: str = "Ctrl+Shift+Space"
    shortcut_copy_answer: str = "Ctrl+Shift+C"
    shortcut_pause: str = "Ctrl+Shift+P"
    shortcut_submit_question: str = "Ctrl+Return"
    font_size: int = 14
    audio_source: str = "system"
    use_postgresql: bool = True
    database_url: str = "postgresql://postgres:123@localhost:5432/interview_copilot"


def config_path() -> Path:
    override = os.environ.get("AI_INTERVIEW_COPILOT_CONFIG")
    if override:
        return Path(override)
    root = Path(os.environ.get("APPDATA", Path.home())) / "AIInterviewCopilot"
    return root / "settings.json"


def fallback_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".user_data" / "settings.json"


def load_config(path: Path | None = None) -> AppConfig:
    targets = [path] if path else [config_path(), fallback_config_path()]
    for target in targets:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            allowed = AppConfig.__dataclass_fields__
            return AppConfig(**{k: v for k, v in raw.items() if k in allowed})
        except (OSError, ValueError, TypeError):
            continue
    return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    targets = [path] if path else [config_path(), fallback_config_path()]
    last_error = None
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
            return target
        except OSError as exc:
            last_error = exc
    raise OSError(f"Could not save settings to the user profile or the local app fallback: {last_error}")
