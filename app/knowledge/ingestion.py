"""Document ingestion: text extraction, chunking, and source-code filtering."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from typing import Any

# Forbidden directory/file name fragments that must never be indexed.
FORBIDDEN_DIRS = {
    ".venv", "venv", "env", ".env", "node_modules", "__pycache__",
    ".git", ".hg", ".svn", "build", "dist", ".next", "out", "target",
    ".mypy_cache", ".pytest_cache", ".tox", "site-packages", "migrations", "staticfiles", "media", "coverage",
}
FORBIDDEN_FILES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "secrets.json", "id_rsa", "id_ed25519", "__init__.py",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
}
FORBIDDEN_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin", ".dat",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".zip", ".tar", ".gz",
}

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".json", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".log"}


@dataclass
class ExtractedDocument:
    filename: str
    file_type: str
    size_bytes: int
    text: str
    metadata: dict[str, Any]
    chunks: list[tuple[str, str | None]]  # (text, source_ref)
    error: str | None = None


def is_forbidden(path: Path) -> bool:
    """Return True if the path should be skipped during indexing."""
    parts = path.parts
    for part in parts:
        if part in FORBIDDEN_DIRS or part.startswith("."):
            return True
    name = path.name
    if name in FORBIDDEN_FILES or name.startswith("."):
        return True
    if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
        return True
    # Skip likely secret files by name pattern.
    lower = name.lower()
    if any(token in lower for token in ("secret", "credential", "token", "private_key", "api_key")):
        return True
    return False


def _read_text_file(path: Path, max_chars: int = 2_000_000) -> str:
    data = path.read_bytes()
    if len(data) > max_chars:
        data = data[:max_chars]
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    pages = []
    for page in doc:
        try:
            # Layout-aware block extraction: preserves columns in modern 2-column resumes
            blocks = page.get_text("blocks")
            text_blocks = [b[4].strip() for b in blocks if len(b) > 4 and b[4].strip()]
            if text_blocks:
                pages.append("\n\n".join(text_blocks))
            else:
                pages.append(page.get_text("text"))
        except Exception:
            pages.append(page.get_text("text"))
    doc.close()
    text = "\n\n".join(pages).strip()
    metadata = {"pages": len(pages)}
    return text, metadata


def _extract_docx(path: Path) -> tuple[str, dict[str, Any]]:
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    tables = []
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            tables.append(" | ".join(cells))
    text = "\n".join(paragraphs + tables).strip()
    metadata = {"paragraphs": len(paragraphs), "tables": len(doc.tables)}
    return text, metadata


def _extract_json(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw, {"parse_error": "invalid_json"}
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    return pretty, {"keys": list(data.keys()) if isinstance(data, dict) else ["root"]}


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[tuple[str, str | None]]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    # Split along top-level Python/JS class/function or Markdown heading boundaries first when present
    boundary_split = re.split(r"\n(?=(?:class\s+[A-Za-z0-9_]+|def\s+[A-Za-z0-9_]+|async\s+def\s+[A-Za-z0-9_]+|#{1,3}\s+\S))", normalized)
    raw_blocks = boundary_split if len(boundary_split) > 1 else normalized.split("\n\n")

    paragraphs: list[str] = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_chars:
            paragraphs.append(block)
        else:
            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            paragraphs.extend(lines if len(lines) > 1 else [block])

    chunks: list[tuple[str, str | None]] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append((current, None))
                current = ""
            step = max(1, max_chars - overlap)
            for start in range(0, len(para), step):
                piece = para[start : start + max_chars].strip()
                if piece:
                    chunks.append((piece, None))
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n" + para).strip() if current else para
        else:
            if current:
                chunks.append((current, None))
            current = para
    if current:
        chunks.append((current, None))
    return chunks


def extract_document(path: str | Path) -> ExtractedDocument:
    """Extract text and metadata from a supported document file."""
    p = Path(path)
    if not p.exists():
        return ExtractedDocument(
            filename=p.name, file_type="unknown", size_bytes=0, text="",
            metadata={}, chunks=[], error="File does not exist",
        )

    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            text, metadata = _extract_pdf(p)
            file_type = "pdf"
        elif suffix in {".docx", ".doc"}:
            text, metadata = _extract_docx(p)
            file_type = "docx"
        elif suffix == ".json":
            text, metadata = _extract_json(p)
            file_type = "json"
        elif suffix in SUPPORTED_TEXT_EXTENSIONS:
            text = _read_text_file(p)
            metadata = {}
            file_type = suffix.lstrip(".") or "text"
        else:
            return ExtractedDocument(
                filename=p.name, file_type="unsupported", size_bytes=p.stat().st_size,
                text="", metadata={}, chunks=[], error=f"Unsupported file type: {suffix}",
            )

        if not text or not text.strip():
            return ExtractedDocument(
                filename=p.name, file_type=file_type, size_bytes=p.stat().st_size,
                text="", metadata=metadata, chunks=[], error="No extractable text",
            )

        chunks = _chunk_text(text)
        return ExtractedDocument(
            filename=p.name, file_type=file_type, size_bytes=p.stat().st_size,
            text=text, metadata=metadata, chunks=chunks, error=None,
        )
    except Exception as exc:  # keep ingestion failures out of the UI thread
        return ExtractedDocument(
            filename=p.name, file_type=suffix.lstrip(".") or "unknown",
            size_bytes=p.stat().st_size if p.exists() else 0, text="",
            metadata={}, chunks=[], error=f"{type(exc).__name__}: {exc}",
        )


def scan_directory(root: str | Path, max_files: int = 500) -> list[Path]:
    """Yield supported, non-forbidden files under root, capped at max_files."""
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        return []
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Filter directories in-place so os.walk does not descend into forbidden ones.
        dirnames[:] = [d for d in dirnames if not is_forbidden(Path(dirpath) / d)]
        for name in filenames:
            if len(results) >= max_files:
                return results
            candidate = Path(dirpath) / name
            if is_forbidden(candidate):
                continue
            suffix = candidate.suffix.lower()
            if suffix in {".pdf", ".docx", ".doc", ".json"} or suffix in SUPPORTED_TEXT_EXTENSIONS:
                results.append(candidate)
    return results
