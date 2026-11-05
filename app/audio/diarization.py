"""Estimate speaker turns from audio energy and tone. Labels can be renamed by the user."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def cluster_speakers(features: list[list[float]]) -> list[str]:
    """Group segment features into Speaker 1 and Speaker 2 when they clearly differ."""
    if len(features) < 2:
        return ["Speaker 1"] * len(features)
    vectors = [np.asarray(feature, dtype=float) for feature in features]
    first = vectors[0]
    second = max(vectors, key=lambda vector: float(np.linalg.norm(vector - first)))
    if float(np.linalg.norm(first - second)) < 0.2:
        return ["Speaker 1"] * len(features)
    labels = [0] * len(vectors)
    center_a, center_b = first, second
    for _ in range(8):
        groups: dict[int, list] = {0: [], 1: []}
        for index, vector in enumerate(vectors):
            label = 0 if np.linalg.norm(vector - center_a) <= np.linalg.norm(vector - center_b) else 1
            labels[index] = label
            groups[label].append(vector)
        if not groups[0] or not groups[1]:
            return ["Speaker 1"] * len(features)
        center_a = np.mean(groups[0], axis=0)
        center_b = np.mean(groups[1], axis=0)
    return ["Speaker 1" if label == 0 else "Speaker 2" for label in labels]


def _load_mono(path: str, sample_rate: int = 16000) -> np.ndarray | None:
    try:
        import av
    except ImportError:
        return None
    try:
        container = av.open(path)
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            return None
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=sample_rate)
        pieces = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                pieces.append(resampled.to_ndarray().reshape(-1))
        container.close()
        if not pieces:
            return None
        return np.concatenate(pieces).astype(np.float32)
    except Exception:
        return None


def _features(samples: np.ndarray, sample_rate: int, start: float, end: float) -> list[float]:
    begin = max(0, int(start * sample_rate))
    finish = max(begin + 1, int(end * sample_rate))
    clip = samples[begin:finish]
    if clip.size < 32:
        return [0.0, 0.0, 0.0]
    energy = float(np.sqrt(np.mean(clip * clip)) / 32768.0)
    window = clip[: min(clip.size, sample_rate)]
    spectrum = np.abs(np.fft.rfft(window))
    freqs = np.fft.rfftfreq(window.size, 1 / sample_rate)
    centroid = float(np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-9) / 4000.0)
    crossings = float(np.mean(np.abs(np.diff(np.sign(window)))) / 2.0)
    return [energy, centroid, crossings]


def label_speakers(path: str, segments: list[tuple[float, float, str]]) -> list[str]:
    """Return a speaker label for each transcript segment."""
    if len(segments) < 2:
        return ["Speaker 1"] * len(segments)
    samples = _load_mono(path)
    if samples is None or samples.size == 0:
        return ["Speaker 1"] * len(segments)
    features = [_features(samples, 16000, start, end) for start, end, _text in segments]
    return cluster_speakers(features)


def format_transcript(path: str, segments: list[tuple[float, float, str]]) -> str:
    labels = label_speakers(path, segments) if Path(path).is_file() else ["Speaker 1"] * len(segments)
    lines = []
    for label, (start, end, text) in zip(labels, segments):
        cleaned = text.strip()
        if cleaned:
            lines.append(f"[{start:.1f}-{end:.1f}] {label}: {cleaned}")
    return "\n".join(lines)
