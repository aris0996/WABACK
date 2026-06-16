import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app, g

from .config import DEFAULT_SETTINGS


def _sqlite_path(database_url):
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)
    parsed = urlparse(database_url)
    return parsed.path.lstrip("/") or "data/app.db"


def get_db():
    if "db" not in g:
        db_path = _sqlite_path(current_app.config["DATABASE_URL"])
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        db_path = _sqlite_path(app.config["DATABASE_URL"])
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = NORMAL")
        db.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
        db.commit()
        db.close()
    app.teardown_appcontext(close_db)


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def execute(sql, params=()):
    cur = get_db().execute(sql, params)
    get_db().commit()
    return cur


def get_setting(key, default=""):
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def get_settings():
    rows = query_all("SELECT key, value FROM settings ORDER BY key")
    return {row["key"]: row["value"] for row in rows}


SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_number TEXT NOT NULL UNIQUE,
    display_name TEXT,
    auto_reply_enabled INTEGER NOT NULL DEFAULT 1,
    ai_blocked INTEGER NOT NULL DEFAULT 0,
    last_memory_message_id INTEGER NOT NULL DEFAULT 0,
    new_message_count_since_memory INTEGER NOT NULL DEFAULT 0,
    memory_auto_generate_enabled INTEGER NOT NULL DEFAULT 1,
    memory_generate_interval INTEGER NOT NULL DEFAULT 20,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('in', 'out')),
    message TEXT NOT NULL,
    raw_payload TEXT,
    used_for_memory INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL,
    source_mode TEXT NOT NULL,
    from_message_id INTEGER NOT NULL DEFAULT 0,
    to_message_id INTEGER NOT NULL DEFAULT 0,
    memory_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL UNIQUE,
    memory_json TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contacts_wa_number ON contacts(wa_number);
CREATE INDEX IF NOT EXISTS idx_contacts_updated_at ON contacts(updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_contact_id_id ON messages(contact_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_contact_id_created_at ON messages(contact_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_used_for_memory ON messages(used_for_memory);
CREATE INDEX IF NOT EXISTS idx_memories_contact_id ON memories(contact_id);
CREATE INDEX IF NOT EXISTS idx_memory_candidates_contact_id ON memory_candidates(contact_id);
CREATE INDEX IF NOT EXISTS idx_system_logs_level_created_at ON system_logs(level, created_at);
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at);
"""
