"""Record the default microphone or Windows WASAPI speaker/headphone loopback to 16 kHz mono audio."""

from __future__ import annotations

import tempfile
import threading
import wave
from pathlib import Path


class CaptureError(RuntimeError):
    """The audio device could not be used."""


def _resample_to_16k_mono(data, channels: int, src_rate: int, np_mod):
    """Convert interleaved int16 PCM bytes/array into a 16 kHz float32 mono numpy array in [-1, 1]."""
    arr = np_mod.frombuffer(data, dtype=np_mod.int16).astype(np_mod.float32) / 32768.0
    if channels > 1 and arr.size >= channels:
        frames = arr.size // channels
        arr = arr[: frames * channels].reshape(frames, channels).mean(axis=1)
    if src_rate != 16000 and arr.size > 1:
        target_len = max(1, int(round(arr.size * 16000 / float(src_rate))))
        x_old = np_mod.linspace(0.0, 1.0, num=arr.size, endpoint=False)
        x_new = np_mod.linspace(0.0, 1.0, num=target_len, endpoint=False)
        arr = np_mod.interp(x_new, x_old, arr).astype(np_mod.float32)
    return arr


class _LoopbackStream:
    """Windows WASAPI loopback stream capturing speaker/headphone output via PyAudioWPatch."""

    def __init__(self, on_chunk_16k_float32):
        self.on_chunk = on_chunk_16k_float32
        self._pa = None
        self._stream = None

    def start(self) -> None:
        try:
            import numpy as np
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise CaptureError(
                "System speaker/headphone capture requires PyAudioWPatch. "
                "Run: .\\.venv\\Scripts\\python.exe -m pip install PyAudioWPatch"
            ) from exc

        try:
            self._pa = pyaudio.PyAudio()
            device = self._pa.get_default_wasapi_loopback()
            src_rate = int(device.get("defaultSampleRate") or 48000)
            channels = max(1, int(device.get("maxInputChannels") or 2))

            def _pyaudio_cb(in_data, _frame_count, _time_info, _status):
                if in_data:
                    mono_16k = _resample_to_16k_mono(in_data, channels, src_rate, np)
                    if mono_16k.size > 0:
                        self.on_chunk(mono_16k)
                return (None, pyaudio.paContinue)

            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=src_rate,
                frames_per_buffer=max(1024, int(src_rate * 0.1)),
                input=True,
                input_device_index=int(device["index"]),
                stream_callback=_pyaudio_cb,
            )
            self._stream.start_stream()
        except Exception as exc:
            self.stop()
            raise CaptureError(f"Could not open Windows speaker/headphone loopback: {exc}") from exc

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None


class MicrophoneRecorder:
    """Start and stop a 16 kHz mono recording from Microphone, System Audio, or Both."""

    def __init__(self, source: str = "both"):
        self.source = source  # "mic", "system", or "both"
        self._stream = None
        self._loopback: _LoopbackStream | None = None
        self._loopback_frames: list = []
        self._mic_frames: list = []

    def start(self) -> None:
        if self._stream is not None or self._loopback is not None:
            raise CaptureError("A recording is already in progress.")
        self._loopback_frames = []
        self._mic_frames = []
        started_any = False
        last_error: Exception | None = None

        if self.source in ("system", "both"):
            try:
                import numpy as np

                def _on_loopback(mono_float32):
                    pcm16 = (np.clip(mono_float32, -1.0, 1.0) * 32767.0).astype(np.int16).reshape(-1, 1)
                    self._loopback_frames.append(pcm16)

                self._loopback = _LoopbackStream(_on_loopback)
                self._loopback.start()
                started_any = True
            except Exception as exc:
                self._loopback = None
                last_error = exc
                if self.source == "system":
                    raise CaptureError(str(exc)) from exc

        if self.source in ("mic", "both"):
            try:
                import sounddevice as sd
            except ImportError as exc:
                if not started_any:
                    raise CaptureError(
                        "Live recording needs the optional sounddevice package. "
                        "Install it with: .\\.venv\\Scripts\\python.exe -m pip install sounddevice"
                    ) from exc
                return

            def _callback(indata, _frames, _time, status):
                if status:
                    return
                self._mic_frames.append(indata.copy())

            try:
                self._stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=_callback)
                self._stream.start()
                started_any = True
            except Exception as exc:
                self._stream = None
                if not started_any:
                    raise CaptureError(f"Could not open the microphone: {exc}") from exc

        if not started_any and last_error is not None:
            raise CaptureError(str(last_error))

    def stop(self) -> str:
        if self._stream is None and self._loopback is None:
            raise CaptureError("There is no active recording.")
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._loopback is not None:
            self._loopback.stop()
            self._loopback = None

        import numpy as np

        if self._loopback_frames and self._mic_frames:
            loop_audio = np.concatenate(self._loopback_frames, axis=0)
            mic_audio = np.concatenate(self._mic_frames, axis=0)
            min_len = min(len(loop_audio), len(mic_audio))
            if min_len > 0:
                audio = ((loop_audio[:min_len].astype(np.float32) + mic_audio[:min_len].astype(np.float32)) * 0.5).astype(np.int16)
            elif len(loop_audio) > 0:
                audio = loop_audio
            else:
                audio = mic_audio
        elif self._loopback_frames:
            audio = np.concatenate(self._loopback_frames, axis=0)
        elif self._mic_frames:
            audio = np.concatenate(self._mic_frames, axis=0)
        else:
            raise CaptureError("No audio was captured. Check the audio source and try again.")

        target = Path(tempfile.gettempdir()) / "interview_copilot_mic.wav"
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(audio.tobytes())
        return str(target)


class _UtteranceDetector:
    """Detects spoken utterances in a single 16kHz float32 audio stream using energy-based VAD."""

    def __init__(
        self,
        on_utterance,
        on_speech_state=None,
        sample_rate: int = 16000,
        silence_seconds: float = 0.65,
        min_speech_seconds: float = 0.50,
        max_utterance_seconds: float = 28.0,
        energy_threshold: float = 0.005,
    ):
        self.on_utterance = on_utterance
        self.on_speech_state = on_speech_state
        self.sample_rate = sample_rate
        self.silence_limit = int(silence_seconds * sample_rate)
        self.min_speech = int(min_speech_seconds * sample_rate)
        self.max_samples = int(max_utterance_seconds * sample_rate)
        self.energy_threshold = energy_threshold

        self._speech_chunks: list = []
        self._pre_roll: list = []
        self._speaking = False
        self._silence_samples = 0
        self._speech_samples = 0
        self._lock = threading.Lock()

    def process_chunk(self, chunk_float32, np_mod) -> None:
        with self._lock:
            if chunk_float32.size == 0:
                return
            rms = float(np_mod.sqrt(np_mod.mean(chunk_float32 * chunk_float32)))

            if rms >= self.energy_threshold:
                if not self._speaking:
                    self._speaking = True
                    self._speech_chunks = list(self._pre_roll)
                    if self.on_speech_state:
                        self.on_speech_state(True)
                self._speech_chunks.append(chunk_float32)
                self._speech_samples += len(chunk_float32)
                self._silence_samples = 0
                if self._speech_samples >= self.max_samples:
                    self._flush_locked(np_mod)
            else:
                if self._speaking:
                    self._speech_chunks.append(chunk_float32)
                    self._silence_samples += len(chunk_float32)
                    if self._silence_samples >= self.silence_limit:
                        if self._speech_samples >= self.min_speech:
                            self._flush_locked(np_mod)
                        else:
                            self._reset_locked()
                else:
                    self._pre_roll.append(chunk_float32)
                    if len(self._pre_roll) > 6:
                        self._pre_roll.pop(0)

    def _flush_locked(self, np_mod) -> None:
        if not self._speech_chunks:
            self._reset_locked()
            return
        audio = np_mod.concatenate(self._speech_chunks, axis=0)
        self._reset_locked()
        try:
            self.on_utterance(audio)
        except Exception:
            pass

    def _reset_locked(self) -> None:
        self._speech_chunks = []
        self._speaking = False
        self._silence_samples = 0
        self._speech_samples = 0
        if self.on_speech_state:
            self.on_speech_state(False)

    def reset(self) -> None:
        with self._lock:
            self._reset_locked()


class ContinuousListener:
    """Hands-free voice activity listener supporting System Audio (Zoom/Meet loopback), Mic, or Both."""

    def __init__(
        self,
        on_utterance_audio,
        on_speech_state=None,
        source: str = "both",
        sample_rate: int = 16000,
        silence_seconds: float = 0.65,
        min_speech_seconds: float = 0.50,
        max_utterance_seconds: float = 28.0,
        energy_threshold: float = 0.008,
    ):
        self.on_utterance_audio = on_utterance_audio
        self.on_speech_state = on_speech_state
        self.source = source  # "system", "mic", or "both"
        self.sample_rate = sample_rate
        self.silence_seconds = silence_seconds
        self.min_speech_seconds = min_speech_seconds
        self.max_utterance_seconds = max_utterance_seconds
        self.energy_threshold = energy_threshold
        self._stream = None
        self._loopback: _LoopbackStream | None = None
        self._loopback_detector: _UtteranceDetector | None = None
        self._mic_detector: _UtteranceDetector | None = None
        self._active = False

    @property
    def is_running(self) -> bool:
        return self._active and (self._stream is not None or self._loopback is not None)

    def _on_detected_utterance(self, audio, source: str = "system") -> None:
        if not self._active:
            return
        try:
            self.on_utterance_audio(audio, source)
        except TypeError:
            self.on_utterance_audio(audio)
        except Exception:
            pass

    def start(self) -> None:
        if self.is_running:
            return
        try:
            import numpy as np
        except ImportError as exc:
            raise CaptureError("numpy is required for hands-free listening.") from exc

        self._active = True

        # System Loopback has near-zero digital floor: threshold 0.004 catches soft interviewer speech
        self._loopback_detector = _UtteranceDetector(
            on_utterance=lambda audio: self._on_detected_utterance(audio, source="system"),
            on_speech_state=self.on_speech_state,
            sample_rate=self.sample_rate,
            silence_seconds=self.silence_seconds,
            min_speech_seconds=self.min_speech_seconds,
            max_utterance_seconds=self.max_utterance_seconds,
            energy_threshold=0.004,
        )

        # Microphone has acoustic ambient room floor: threshold 0.008
        self._mic_detector = _UtteranceDetector(
            on_utterance=lambda audio: self._on_detected_utterance(audio, source="mic"),
            on_speech_state=self.on_speech_state,
            sample_rate=self.sample_rate,
            silence_seconds=self.silence_seconds,
            min_speech_seconds=self.min_speech_seconds,
            max_utterance_seconds=self.max_utterance_seconds,
            energy_threshold=self.energy_threshold,
        )

        started_any = False
        last_error: Exception | None = None

        if self.source in ("system", "both"):
            try:
                def _loopback_cb(chunk_float32):
                    if self._active and self._loopback_detector:
                        self._loopback_detector.process_chunk(chunk_float32, np)

                self._loopback = _LoopbackStream(_loopback_cb)
                self._loopback.start()
                started_any = True
            except Exception as exc:
                self._loopback = None
                last_error = exc
                if self.source == "system":
                    self._active = False
                    raise CaptureError(str(exc)) from exc

        if self.source in ("mic", "both"):
            try:
                import sounddevice as sd

                def _mic_cb(indata, _frames, _time, _status):
                    if not self._active or not self._mic_detector:
                        return
                    chunk = indata[:, 0].copy().astype(np.float32) / 32768.0
                    self._mic_detector.process_chunk(chunk, np)

                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=1600,
                    callback=_mic_cb,
                )
                self._stream.start()
                started_any = True
            except Exception as exc:
                self._stream = None
                if not started_any:
                    self._active = False
                    raise CaptureError(f"Could not start hands-free microphone listener: {exc}") from exc

        if not started_any:
            self._active = False
            raise CaptureError(str(last_error or "Could not open any audio input device."))

    def stop(self) -> None:
        self._active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._loopback is not None:
            self._loopback.stop()
            self._loopback = None

        if self._loopback_detector:
            self._loopback_detector.reset()
            self._loopback_detector = None
        if self._mic_detector:
            self._mic_detector.reset()
            self._mic_detector = None
