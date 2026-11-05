"""Transcribe an audio file when faster-whisper is installed."""

from __future__ import annotations

from pathlib import Path
import re

from app.audio.diarization import format_transcript

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
_MODEL_CACHE: dict[str, object] = {}

_GREETING_PATTERNS = (
    "can you hear me",
    "can you here me",
    "you hear me",
    "you here me",
    "hear me now",
    "here me now",
    "am i audible",
    "are you able to hear",
    "are you there",
    "can you see my screen",
    "is my screen visible",
    "testing 1 2",
    "mic check",
    "hello hello",
    "hi hi",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you doing",
    "how are you today",
    "nice to meet you",
    "thanks for joining",
    "thank you for joining",
)


_INTERVIEW_INTENT_WORDS = {
    "tell", "introduce", "intro", "background", "experience", "project", "projects",
    "resume", "cv", "role", "roles", "skills", "skill", "work", "worked",
    "architecture", "explain", "describe", "detail", "details", "walk",
    "approach", "handle", "handled", "implemented", "implement", "designed",
    "why", "how", "what", "which", "where", "when", "can", "could", "would",
}


class TranscriptionError(RuntimeError):
    """The audio file could not be transcribed."""


def _get_whisper_model(model_size: str = "base.en", cpu_threads: int = 4):
    key = f"{model_size}_{cpu_threads}"
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    except Exception:
        if model_size != "base.en":
            return _get_whisper_model("base.en", cpu_threads=cpu_threads)
        raise
    _MODEL_CACHE[key] = model
    return model


def strip_transcript_metadata(text: str) -> str:
    """Remove [0.0-5.0] timestamps and Speaker/Interviewer/Candidate prefixes anywhere in the text."""
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\[\d+(?:\.\d+)?-\d+(?:\.\d+)?\]\s*", "", raw_line)
        line = re.sub(r"\b(?:Speaker\s*\d+|Interviewer|Candidate)\s*:\s*", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    return " ".join(cleaned_lines).strip()


def is_small_talk_or_mic_check(question: str) -> bool:
    """Return True if the spoken text is just a greeting or audio check rather than an interview question."""
    cleaned = strip_transcript_metadata(question).lower()
    words = re.findall(r"[a-z0-9]+", cleaned)
    if len(words) < 2:
        return True

    # If the text has question marks or clear interview prompts, it is an interview question
    has_interview_intent = any(w in _INTERVIEW_INTENT_WORDS for w in words)
    has_question_mark = "?" in question

    if has_interview_intent or has_question_mark:
        pure_mic_checks = (
            "can you hear me",
            "can you here me",
            "am i audible",
            "are you able to hear",
            "can you see my screen",
            "is my screen visible",
            "hear me now",
            "mic check",
            "testing 1 2",
        )
        if any(p in cleaned for p in pure_mic_checks) and len(words) <= 8 and not any(w in words for w in {"project", "experience", "background", "introduce", "tell", "explain", "resume"}):
            return True
        return False

    if any(pattern in cleaned for pattern in _GREETING_PATTERNS) and len(words) <= 8:
        return True
    return False


def transcribe_pcm_array(samples, model_size: str = "base.en") -> str:
    """Fast in-memory transcription of a 16kHz float32 numpy array without disk I/O."""
    try:
        model = _get_whisper_model(model_size, cpu_threads=4)
        raw_segments, _info = model.transcribe(
            samples,
            vad_filter=True,
            beam_size=1,
            best_of=1,
            without_timestamps=True,
        )
        parts = [(seg.text or "").strip() for seg in raw_segments if (seg.text or "").strip()]
        return " ".join(parts).strip()
    except Exception:
        return ""


def transcribe_file(path: str, model_size: str = "base.en") -> str:
    """Return a timestamped transcript with estimated speaker labels."""
    source = Path(path)
    if not source.is_file():
        raise TranscriptionError(f"Audio file not found: {source}")
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise TranscriptionError("Choose a WAV, MP3, M4A, FLAC, OGG, or WEBM file.")
    try:
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        raise TranscriptionError(
            "Audio transcription is optional and not installed. From the project folder run: "
            ".\\.venv\\Scripts\\python.exe -m pip install faster-whisper"
        ) from exc

    try:
        model = _get_whisper_model(model_size, cpu_threads=4)
        raw_segments, _info = model.transcribe(str(source), vad_filter=True)
        segments = []
        for segment in raw_segments:
            text = (segment.text or "").strip()
            if text:
                segments.append((float(segment.start), float(segment.end), text))
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    transcript = format_transcript(str(source), segments).strip()
    if not transcript:
        raise TranscriptionError("No speech was detected in that file.")
    return transcript


def last_question_from_transcript(transcript: str) -> str:
    """Extract a clean spoken question without [start-end] or Speaker prefixes."""
    cleaned = strip_transcript_metadata(transcript)
    if not cleaned:
        return ""
    if "?" not in cleaned:
        return cleaned
    before_last_q = cleaned.rsplit("?", 1)[0]
    parts = [p.strip() for p in re.split(r"[?!.]", before_last_q) if p.strip()]
    question_body = parts[-1] if parts else before_last_q.strip()
    return question_body.rstrip() + "?"
