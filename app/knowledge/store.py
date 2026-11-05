"""Storage backend for documents, chunks, candidate profile, and profile facts.

Production use is PostgreSQL with pgvector. SQLite remains available for unit tests only.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


DB_NAME = "knowledge.db"

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "about", "as", "at", "be", "can", "could", "did", "do", "does",
    "explain", "for", "from", "have", "has", "hear", "here", "hello", "hey", "hi", "how",
    "i", "in", "is", "it", "just", "know", "like", "me", "my", "now", "of", "okay", "ok",
    "on", "or", "please", "say", "see", "some", "so", "talk", "tell", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "through", "to", "us", "walk", "was",
    "we", "were", "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "yeah", "yes", "you", "your",
})


def query_terms(query: str) -> list[str]:
    """Significant words for keyword search. Drops stopwords and very short tokens."""
    terms: list[str] = []
    for raw in query.lower().split():
        term = "".join(ch for ch in raw if ch.isalnum())
        if len(term) < 3 or term in _STOPWORDS or term in terms:
            continue
        terms.append(term)
    return terms[:12]


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def rank_chunks(rows: list[dict[str, Any]], terms: list[str], limit: int) -> list[dict[str, Any]]:
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        text = str(row.get("text", "")).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, index, row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:limit]]


class PostgresStorageError(RuntimeError):
    """PostgreSQL or pgvector setup failed."""


def ensure_postgres_database(database_url: str) -> None:
    """Create the target database if it does not exist yet (connects via the maintenance DB)."""
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    parsed = urlparse(database_url)
    dbname = (parsed.path or "").lstrip("/")
    if not dbname or dbname == "postgres":
        return

    maintenance = urlunparse(parsed._replace(path="/postgres"))
    try:
        conn = psycopg2.connect(maintenance)
    except psycopg2.Error as exc:
        raise PostgresStorageError(
            f"Could not connect to PostgreSQL at {parsed.hostname}:{parsed.port or 5432}. "
            f"Check that the server is running and the password in Settings is correct. ({exc})"
        ) from exc

    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone():
                return
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    except psycopg2.Error as exc:
        raise PostgresStorageError(f"Could not create database {dbname!r}: {exc}") from exc
    finally:
        conn.close()


@dataclass
class DocumentRecord:
    id: int | None
    filename: str
    path: str
    file_type: str
    size_bytes: int
    metadata: dict[str, Any]
    indexed_at: str
    status: str = "indexed"
    error_message: str | None = None


@dataclass
class ChunkRecord:
    id: int | None
    document_id: int
    chunk_index: int
    text: str
    source_ref: str | None
    created_at: str


class _SQLiteStore:
    """SQLite-backed implementation."""

    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        target = self.path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(target))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            return conn
        except (OSError, sqlite3.OperationalError):
            target = fallback_db_path()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(target))
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                return conn
            except (OSError, sqlite3.OperationalError):
                conn = sqlite3.connect(":memory:")
                conn.row_factory = sqlite3.Row
                return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}',
                    indexed_at TEXT NOT NULL,
                    status TEXT DEFAULT 'indexed',
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    source_ref TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    status TEXT DEFAULT 'needs_review',
                    source TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    status TEXT DEFAULT 'needs_review',
                    source TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_profile_key ON candidate_profile(key);
                CREATE INDEX IF NOT EXISTS idx_facts_category ON profile_facts(category);
                """
            )
            conn.commit()
            try:
                conn.execute("ALTER TABLE document_chunks ADD COLUMN embedding TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

    def save_embeddings(self, pairs: list[tuple[int, str]]) -> None:
        conn = self._connect()
        try:
            conn.executemany("UPDATE document_chunks SET embedding = ? WHERE id = ?", [(raw, chunk_id) for chunk_id, raw in pairs])
            conn.commit()
        finally:
            conn.close()

    def list_embedded_chunks(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.document_id, c.chunk_index, c.text, c.source_ref, c.embedding,
                       d.filename, d.path, d.file_type
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'indexed' AND c.embedding IS NOT NULL
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def documents_missing_embeddings(self) -> list[int]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT c.document_id
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'indexed' AND c.embedding IS NULL
                """
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    # ---- Documents ----

    def add_document(
        self,
        filename: str,
        path: str,
        file_type: str,
        size_bytes: int,
        metadata: dict[str, Any] | None = None,
        status: str = "indexed",
        error_message: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO documents (filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    filename=excluded.filename,
                    file_type=excluded.file_type,
                    size_bytes=excluded.size_bytes,
                    metadata=excluded.metadata,
                    indexed_at=excluded.indexed_at,
                    status=excluded.status,
                    error_message=excluded.error_message
                """,
                (
                    filename,
                    path,
                    file_type,
                    size_bytes,
                    json.dumps(metadata or {}),
                    now,
                    status,
                    error_message,
                ),
            )
            doc_id = cur.lastrowid
            conn.commit()
            return int(doc_id) if doc_id is not None else 0
        finally:
            conn.close()

    def remove_document(self, doc_id: int) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def clear_documents(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM document_chunks")
            conn.execute("DELETE FROM documents")
            conn.commit()
        finally:
            conn.close()

    def list_documents(self) -> list[DocumentRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message FROM documents ORDER BY indexed_at DESC"
            ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if not isinstance(d.get("metadata"), dict):
                    try:
                        d["metadata"] = json.loads(d.get("metadata") or "{}")
                    except (ValueError, TypeError):
                        d["metadata"] = {}
                out.append(DocumentRecord(**d))
            return out
        finally:
            conn.close()

    def get_document(self, doc_id: int) -> DocumentRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
            return DocumentRecord(**dict(row)) if row else None
        finally:
            conn.close()

    def add_chunks(self, document_id: int, chunks: list[tuple[str, str | None]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            conn.executemany(
                """
                INSERT INTO document_chunks (document_id, chunk_index, text, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(document_id, idx, text, ref, now) for idx, (text, ref) in enumerate(chunks)],
            )
            conn.commit()
        finally:
            conn.close()

    def get_chunks_for_document(self, document_id: int) -> list[ChunkRecord]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, document_id, chunk_index, text, source_ref, created_at FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
                (document_id,),
            ).fetchall()
            return [ChunkRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    def search_chunks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        conn = self._connect()
        try:
            where = " OR ".join(["LOWER(text) LIKE ? ESCAPE '\\'"] * len(terms))
            params = [_like_pattern(term) for term in terms]
            rows = conn.execute(
                f"""
                SELECT c.id, c.document_id, c.chunk_index, c.text, c.source_ref,
                       d.filename, d.path, d.file_type
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'indexed' AND ({where})
                LIMIT 200
                """,
                params,
            ).fetchall()
            return rank_chunks([dict(row) for row in rows], terms, limit)
        finally:
            conn.close()

    # ---- Candidate profile ----

    def set_profile_field(
        self, key: str, value: Any, status: str = "needs_review", source: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(value, ensure_ascii=False)
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO candidate_profile (key, value, status, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    status=excluded.status,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (key, serialized, status, source, now),
            )
            conn.commit()
        finally:
            conn.close()

    def get_profile_field(self, key: str) -> Any | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value, status FROM candidate_profile WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["value"])
            except (ValueError, TypeError):
                return row["value"]
        finally:
            conn.close()

    def get_full_profile(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, value, status, source, updated_at FROM candidate_profile ORDER BY key").fetchall()
            profile: dict[str, Any] = {}
            for r in rows:
                try:
                    profile[r["key"]] = json.loads(r["value"])
                except (ValueError, TypeError):
                    profile[r["key"]] = r["value"]
            return profile
        finally:
            conn.close()

    def clear_profile(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM candidate_profile")
            conn.execute("DELETE FROM profile_facts")
            conn.commit()
        finally:
            conn.close()

    # ---- Profile facts ----

    def add_profile_fact(
        self, category: str, fact: str, status: str = "needs_review", source: str | None = None
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                INSERT INTO profile_facts (category, fact, status, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (category, fact, status, source, now),
            )
            conn.commit()
            return int(cur.lastrowid) if cur.lastrowid is not None else 0
        finally:
            conn.close()

    def list_profile_facts(self, category: str | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            if category:
                rows = conn.execute(
                    "SELECT id, category, fact, status, source, created_at FROM profile_facts WHERE category = ? ORDER BY created_at DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, category, fact, status, source, created_at FROM profile_facts ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def set_fact_status(self, fact_id: int, status: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("UPDATE profile_facts SET status = ? WHERE id = ?", (status, fact_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def remove_profile_fact(self, fact_id: int) -> bool:
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM profile_facts WHERE id = ?", (fact_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def clear_session_data(self) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM candidate_profile")
            conn.execute("DELETE FROM profile_facts")
            conn.commit()
        finally:
            conn.close()


class _PostgresStore:
    """PostgreSQL-backed implementation with pgvector support."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        import psycopg2

        self._psycopg2 = psycopg2
        self._init_db()

    def _connect(self):
        return self._psycopg2.connect(self.database_url)

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                except self._psycopg2.Error as exc:
                    raise PostgresStorageError(
                        "The pgvector extension is not installed on this PostgreSQL server. "
                        "Run scripts/install_pgvector.ps1 as Administrator (PostgreSQL 18), then restart the app."
                    ) from exc
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        filename TEXT NOT NULL,
                        path TEXT NOT NULL UNIQUE,
                        file_type TEXT NOT NULL,
                        size_bytes INTEGER DEFAULT 0,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        indexed_at TIMESTAMPTZ NOT NULL,
                        status TEXT DEFAULT 'indexed',
                        error_message TEXT
                    );
                    CREATE TABLE IF NOT EXISTS document_chunks (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        source_ref TEXT,
                        embedding vector(384),
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS candidate_profile (
                        key TEXT PRIMARY KEY,
                        value JSONB NOT NULL,
                        status TEXT DEFAULT 'needs_review',
                        source TEXT,
                        updated_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS profile_facts (
                        id SERIAL PRIMARY KEY,
                        category TEXT NOT NULL,
                        fact TEXT NOT NULL,
                        status TEXT DEFAULT 'needs_review',
                        source TEXT,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
                    CREATE INDEX IF NOT EXISTS idx_profile_key ON candidate_profile(key);
                    CREATE INDEX IF NOT EXISTS idx_facts_category ON profile_facts(category);
                    """
                )
        finally:
            conn.close()

    # ---- Documents ----

    def add_document(
        self,
        filename: str,
        path: str,
        file_type: str,
        size_bytes: int,
        metadata: dict[str, Any] | None = None,
        status: str = "indexed",
        error_message: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        file_type = EXCLUDED.file_type,
                        size_bytes = EXCLUDED.size_bytes,
                        metadata = EXCLUDED.metadata,
                        indexed_at = EXCLUDED.indexed_at,
                        status = EXCLUDED.status,
                        error_message = EXCLUDED.error_message
                    RETURNING id
                    """,
                    (
                        filename,
                        path,
                        file_type,
                        size_bytes,
                        json.dumps(metadata or {}),
                        now,
                        status,
                        error_message,
                    ),
                )
                row = cur.fetchone()
                doc_id = row[0] if row else 0
            conn.commit()
            return int(doc_id)
        finally:
            conn.close()

    def remove_document(self, doc_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
                removed = cur.rowcount > 0
            conn.commit()
            return removed
        finally:
            conn.close()

    def clear_documents(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM document_chunks")
                cur.execute("DELETE FROM documents")
            conn.commit()
        finally:
            conn.close()

    def list_documents(self) -> list[DocumentRecord]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message FROM documents ORDER BY indexed_at DESC"
                )
                rows = cur.fetchall()
            return [
                DocumentRecord(
                    id=r[0],
                    filename=r[1],
                    path=r[2],
                    file_type=r[3],
                    size_bytes=r[4],
                    metadata=r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                    indexed_at=r[6].isoformat() if r[6] else "",
                    status=r[7],
                    error_message=r[8],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_document(self, doc_id: int) -> DocumentRecord | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, filename, path, file_type, size_bytes, metadata, indexed_at, status, error_message FROM documents WHERE id = %s",
                    (doc_id,),
                )
                row = cur.fetchone()
            if not row:
                return None
            return DocumentRecord(
                id=row[0],
                filename=row[1],
                path=row[2],
                file_type=row[3],
                size_bytes=row[4],
                metadata=row[5] if isinstance(row[5], dict) else json.loads(row[5] or "{}"),
                indexed_at=row[6].isoformat() if row[6] else "",
                status=row[7],
                error_message=row[8],
            )
        finally:
            conn.close()

    def add_chunks(self, document_id: int, chunks: list[tuple[str, str | None]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
                if chunks:
                    cur.executemany(
                        """
                        INSERT INTO document_chunks (document_id, chunk_index, text, source_ref, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        [(document_id, idx, text, ref, now) for idx, (text, ref) in enumerate(chunks)],
                    )
            conn.commit()
        finally:
            conn.close()

    def save_embeddings(self, pairs: list[tuple[int, str]]) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                for chunk_id, raw in pairs:
                    cur.execute("UPDATE document_chunks SET embedding = %s::vector WHERE id = %s", (raw, chunk_id))
            conn.commit()
        finally:
            conn.close()

    def list_embedded_chunks(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.document_id, c.chunk_index, c.text, c.source_ref, c.embedding::text,
                           d.filename, d.path, d.file_type
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.status = 'indexed' AND c.embedding IS NOT NULL
                    """
                )
                rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "document_id": row[1],
                    "chunk_index": row[2],
                    "text": row[3],
                    "source_ref": row[4],
                    "embedding": row[5],
                    "filename": row[6],
                    "path": row[7],
                    "file_type": row[8],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def vector_search(self, vector_str: str, min_similarity: float, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.id, c.document_id, c.chunk_index, c.text, c.source_ref,
                           d.filename, d.path, d.file_type,
                           1 - (c.embedding <=> %s::vector) AS similarity
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.status = 'indexed'
                      AND c.embedding IS NOT NULL
                      AND (1 - (c.embedding <=> %s::vector)) >= %s
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector_str, vector_str, min_similarity, vector_str, limit),
                )
                rows = cur.fetchall()
            return [
                {
                    "id": row[0],
                    "document_id": row[1],
                    "chunk_index": row[2],
                    "text": row[3],
                    "source_ref": row[4],
                    "filename": row[5],
                    "path": row[6],
                    "file_type": row[7],
                    "similarity": float(row[8]) if row[8] is not None else 0.0,
                }
                for row in rows
            ]
        except Exception:
            return []
        finally:
            conn.close()

    def documents_missing_embeddings(self) -> list[int]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT c.document_id
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.status = 'indexed' AND c.embedding IS NULL
                    """
                )
                return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def get_chunks_for_document(self, document_id: int) -> list[ChunkRecord]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, document_id, chunk_index, text, source_ref, created_at FROM document_chunks WHERE document_id = %s ORDER BY chunk_index",
                    (document_id,),
                )
                rows = cur.fetchall()
            return [
                ChunkRecord(
                    id=r[0],
                    document_id=r[1],
                    chunk_index=r[2],
                    text=r[3],
                    source_ref=r[4],
                    created_at=r[5].isoformat() if r[5] else "",
                )
                for r in rows
            ]
        finally:
            conn.close()

    def search_chunks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                where = " OR ".join(["LOWER(text) LIKE %s ESCAPE '\\'"] * len(terms))
                params = [_like_pattern(term) for term in terms]
                cur.execute(
                    f"""
                    SELECT c.id, c.document_id, c.chunk_index, c.text, c.source_ref,
                           d.filename, d.path, d.file_type
                    FROM document_chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.status = 'indexed' AND ({where})
                    LIMIT 200
                    """,
                    params,
                )
                rows = cur.fetchall()
            ranked = [
                {
                    "id": r[0],
                    "document_id": r[1],
                    "chunk_index": r[2],
                    "text": r[3],
                    "source_ref": r[4],
                    "filename": r[5],
                    "path": r[6],
                    "file_type": r[7],
                }
                for r in rows
            ]
            return rank_chunks(ranked, terms, limit)
        finally:
            conn.close()

    # ---- Candidate profile ----

    def set_profile_field(
        self, key: str, value: Any, status: str = "needs_review", source: str | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(value, ensure_ascii=False)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO candidate_profile (key, value, status, source, updated_at)
                    VALUES (%s, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        status = EXCLUDED.status,
                        source = EXCLUDED.source,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (key, serialized, status, source, now),
                )
            conn.commit()
        finally:
            conn.close()

    def get_profile_field(self, key: str) -> Any | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value, status FROM candidate_profile WHERE key = %s", (key,))
                row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0]) if not isinstance(row[0], dict) else row[0]
            except (ValueError, TypeError):
                return row[0]
        finally:
            conn.close()

    def get_full_profile(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value, status, source, updated_at FROM candidate_profile ORDER BY key")
                rows = cur.fetchall()
            profile: dict[str, Any] = {}
            for r in rows:
                try:
                    profile[r[0]] = json.loads(r[1]) if not isinstance(r[1], dict) else r[1]
                except (ValueError, TypeError):
                    profile[r[0]] = r[1]
            return profile
        finally:
            conn.close()

    def clear_profile(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM candidate_profile")
                cur.execute("DELETE FROM profile_facts")
            conn.commit()
        finally:
            conn.close()

    # ---- Profile facts ----

    def add_profile_fact(
        self, category: str, fact: str, status: str = "needs_review", source: str | None = None
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profile_facts (category, fact, status, source, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (category, fact, status, source, now),
                )
                row = cur.fetchone()
                fact_id = row[0] if row else 0
            conn.commit()
            return int(fact_id)
        finally:
            conn.close()

    def list_profile_facts(self, category: str | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                if category:
                    cur.execute(
                        "SELECT id, category, fact, status, source, created_at FROM profile_facts WHERE category = %s ORDER BY created_at DESC",
                        (category,),
                    )
                else:
                    cur.execute(
                        "SELECT id, category, fact, status, source, created_at FROM profile_facts ORDER BY created_at DESC"
                    )
                rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "category": r[1],
                    "fact": r[2],
                    "status": r[3],
                    "source": r[4],
                    "created_at": r[5].isoformat() if r[5] else "",
                }
                for r in rows
            ]
        finally:
            conn.close()

    def set_fact_status(self, fact_id: int, status: str) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE profile_facts SET status = %s WHERE id = %s", (status, fact_id))
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()

    def remove_profile_fact(self, fact_id: int) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM profile_facts WHERE id = %s", (fact_id,))
                removed = cur.rowcount > 0
            conn.commit()
            return removed
        finally:
            conn.close()

    def clear_session_data(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM candidate_profile")
                cur.execute("DELETE FROM profile_facts")
            conn.commit()
        finally:
            conn.close()


class KnowledgeStore:
    """Unified store; the app uses PostgreSQL + pgvector. SQLite is for tests when explicitly disabled or as fallback."""

    def __init__(self, path: Path | None = None, database_url: str | None = None, use_postgresql: bool = True):
        self.fallback_warning: str | None = None
        if use_postgresql:
            if not database_url:
                if path is not None:
                    use_postgresql = False
                else:
                    from app.config import load_config

                    database_url = load_config().database_url
            if use_postgresql and database_url:
                try:
                    ensure_postgres_database(database_url)
                    self.use_postgresql = True
                    self._backend = _PostgresStore(database_url)
                    return
                except Exception as exc:
                    self.fallback_warning = (
                        f"PostgreSQL unavailable ({exc}). Using local SQLite storage."
                    )
                    use_postgresql = False
        self.use_postgresql = False
        self._backend = _SQLiteStore(path)

    def add_chunks(self, document_id: int, chunks: list[tuple[str, str | None]], embed_now: bool = True) -> None:
        self._backend.add_chunks(document_id, chunks)
        if embed_now:
            self._store_embeddings(document_id)

    def search_chunks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        # Fast path: Try indexed SQL keyword search first (<100ms)
        results = self._backend.search_chunks(query, limit)
        if len(results) >= 3:
            return results
        # Fall back to semantic search if keyword matches are sparse
        semantic = self._semantic_search(query, limit)
        if semantic:
            return semantic
        return results

    def _backfill_embeddings(self) -> None:
        if not hasattr(self._backend, "documents_missing_embeddings"):
            return
        for document_id in self._backend.documents_missing_embeddings():
            self._store_embeddings(document_id)

    def _store_embeddings(self, document_id: int) -> None:
        from app.config import load_config
        from app.knowledge.embeddings import embed_texts, vector_literal

        chunks = self._backend.get_chunks_for_document(document_id)
        vectors = embed_texts([chunk.text for chunk in chunks], load_config().ollama_url)
        if not vectors:
            return
        pairs = []
        for chunk, vector in zip(chunks, vectors):
            if chunk.id is not None:
                pairs.append((chunk.id, vector_literal(vector)))
        if pairs and hasattr(self._backend, "save_embeddings"):
            self._backend.save_embeddings(pairs)

    def _semantic_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        from app.config import load_config
        from app.knowledge.embeddings import MIN_SIMILARITY, cosine_similarity, embed_texts, parse_vector, vector_literal

        if not hasattr(self._backend, "list_embedded_chunks"):
            return []
        vectors = embed_texts([query], load_config().ollama_url)
        if not vectors:
            return []
        query_vector = vectors[0]
        if hasattr(self._backend, "vector_search"):
            pg_hits = self._backend.vector_search(vector_literal(query_vector), MIN_SIMILARITY, limit=limit)
            if pg_hits:
                return pg_hits
        scored = []
        for row in self._backend.list_embedded_chunks():
            stored = parse_vector(row.get("embedding"))
            if not stored:
                continue
            score = cosine_similarity(query_vector, stored)
            if score >= MIN_SIMILARITY:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, row in scored[:limit]:
            cleaned = {key: value for key, value in row.items() if key != "embedding"}
            cleaned["similarity"] = float(score)
            results.append(cleaned)
        return results

    def __getattr__(self, name):
        return getattr(self._backend, name)


def init_db(path: Path | None = None) -> Path:
    """Backward-compatible initializer: creates a SQLite store at the given path."""
    _SQLiteStore(path)
    return path or db_path()


def db_path() -> Path:
    override = os.environ.get("AI_INTERVIEW_COPILOT_CONFIG")
    if override:
        return Path(override).parent / DB_NAME
    root = Path(os.environ.get("APPDATA", Path.home())) / "AIInterviewCopilot"
    return root / DB_NAME


def fallback_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".user_data" / DB_NAME
