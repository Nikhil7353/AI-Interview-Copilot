"""One-off DB connectivity check (not part of the app)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config import config_path, fallback_config_path, load_config
from app.knowledge.store import KnowledgeStore


def main() -> int:
    cfg = load_config()
    print("=== Settings ===")
    for p in (config_path(), fallback_config_path()):
        print(f"  {p}  exists={p.exists()}")
    print(f"  use_postgresql={cfg.use_postgresql}")
    # Mask password in URL for display
    url = cfg.database_url
    if "://" in url and "@" in url:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            creds, hostpart = rest.rsplit("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                display_url = f"{prefix}://{user}:****@{hostpart}"
            else:
                display_url = url
        else:
            display_url = url
    else:
        display_url = url
    print(f"  database_url={display_url}")

    print("\n=== PostgreSQL (if enabled) ===")
    if cfg.use_postgresql and cfg.database_url:
        try:
            import psycopg2

            conn = psycopg2.connect(cfg.database_url)
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector');"
            )
            has_vector = cur.fetchone()[0]
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            tables = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()
            print("  Status: CONNECTED")
            print(f"  Server: {version[:80]}...")
            print(f"  pgvector extension: {'yes' if has_vector else 'no'}")
            print(f"  Tables ({len(tables)}): {', '.join(tables) or '(none)'}")
        except Exception as exc:
            print(f"  Status: FAILED — {exc}")
    else:
        print("  Skipped (PostgreSQL disabled in config)")

    print("\n=== KnowledgeStore (app wrapper) ===")
    try:
        store = KnowledgeStore(
            use_postgresql=cfg.use_postgresql,
            database_url=cfg.database_url,
        )
        backend = "PostgreSQL" if store.use_postgresql else "SQLite"
        docs = store.list_documents()
        print(f"  Backend: {backend}")
        print(f"  Status: OK (list_documents returned {len(docs)} document(s))")
    except Exception as exc:
        print(f"  Status: FAILED — {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
