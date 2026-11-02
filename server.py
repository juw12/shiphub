"""shiphub: a Pinterest-style board of app ideas with threads, builders and forks.

Runs on the Python 3.10+ standard library with SQLite. Postgres is optional
(set DATABASE_URL and `pip install "psycopg[binary]"`).

    python server.py                       # http://127.0.0.1:8000, opens your browser
    python server.py --host 0.0.0.0        # share on your local network
    python server.py --reset               # wipe the database and re-seed demo data

Configuration comes from environment variables or a config.env file next to
this script (see config.example.env).
"""
from __future__ import annotations

import argparse
import base64
import functools
import gzip
import hashlib
import hmac
import json
import os
import queue
import random
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ROOT / "config.env")


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    """Runtime configuration. Everything can be set via env vars or config.env."""

    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("SHIPHUB_DATA_DIR") or ROOT / "data")
        self.db_path = self.data_dir / "shiphub.db"
        self.database_url = os.environ.get("DATABASE_URL", "").strip()
        self.public_url = (
            os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or ""
        ).strip().rstrip("/")
        self.github_client_id = os.environ.get("GITHUB_CLIENT_ID", "").strip()
        self.github_client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
        self.github_oauth_url = os.environ.get("GITHUB_OAUTH_URL", "https://github.com").rstrip("/")
        self.github_api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        self.demo = env_flag("SHIPHUB_DEMO", True)
        self.seed = env_flag("SHIPHUB_SEED", True)
        self.trust_proxy = env_flag("TRUST_PROXY", False)
        self.rate_limits = env_flag("SHIPHUB_RATE_LIMITS", True)
        self.admins = {
            name.strip().lower()
            for name in os.environ.get("SHIPHUB_ADMINS", "").split(",")
            if name.strip()
        }
        try:
            upload_mb = float(os.environ.get("SHIPHUB_MAX_UPLOAD_MB", "5"))
        except ValueError:
            upload_mb = 5.0
        self.max_upload_bytes = int(max(0.1, upload_mb) * 1024 * 1024)

    @property
    def postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)


SETTINGS = Settings()

SESSION_COOKIE = "shiphub_sid"
OAUTH_COOKIE = "shiphub_oauth"
SESSION_SECONDS = 30 * 24 * 3600
PBKDF2_ITERATIONS = 200_000
MAX_BODY_BYTES = 64 * 1024
COVER_STYLES = 10
BUILD_STATUSES = ("building", "shipped")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
URL_RE = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)
UPLOAD_PATH_RE = re.compile(r"^/uploads/([A-Za-z0-9_-]{16,64})\.(png|jpg|gif|webp)$")
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
UPLOADS_PER_HOUR = 40
TAG_CLEAN_RE = re.compile(r"[^a-z0-9+.\-]")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https: http:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id {pk},
    username TEXT NOT NULL UNIQUE{nocase},
    display_name TEXT NOT NULL,
    bio TEXT NOT NULL DEFAULT '',
    avatar_hue INTEGER NOT NULL DEFAULT 200,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    github_id TEXT,
    github_login TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    created_at {ts} NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at {ts} NOT NULL
);
CREATE TABLE IF NOT EXISTS ideas (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    pitch TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    stack TEXT NOT NULL DEFAULT '',
    scope INTEGER NOT NULL DEFAULT 0,
    cover_style INTEGER NOT NULL DEFAULT 0,
    cover_image TEXT NOT NULL DEFAULT '',
    forked_from INTEGER REFERENCES ideas(id),
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at {ts} NOT NULL,
    updated_at {ts} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ideas_user ON ideas(user_id);
CREATE INDEX IF NOT EXISTS idx_ideas_fork ON ideas(forked_from);
CREATE TABLE IF NOT EXISTS idea_tags (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    pos INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (idea_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_idea_tags_tag ON idea_tags(tag);
CREATE TABLE IF NOT EXISTS idea_votes (
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at {ts} NOT NULL,
    PRIMARY KEY (idea_id, user_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id {pk},
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    parent_id INTEGER REFERENCES comments(id),
    body TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at {ts} NOT NULL,
    edited_at {ts}
);
CREATE INDEX IF NOT EXISTS idx_comments_idea ON comments(idea_id);
CREATE TABLE IF NOT EXISTS comment_votes (
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (comment_id, user_id)
);
CREATE TABLE IF NOT EXISTS boards (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at {ts} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_boards_user ON boards(user_id);
CREATE TABLE IF NOT EXISTS board_items (
    board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    created_at {ts} NOT NULL,
    PRIMARY KEY (board_id, idea_id)
);
CREATE TABLE IF NOT EXISTS builds (
    id {pk},
    idea_id INTEGER NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'building',
    repo_url TEXT NOT NULL DEFAULT '',
    demo_url TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at {ts} NOT NULL,
    updated_at {ts} NOT NULL,
    UNIQUE (idea_id, user_id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    idea_id INTEGER REFERENCES ideas(id) ON DELETE CASCADE,
    comment_id INTEGER,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at {ts} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
CREATE TABLE IF NOT EXISTS uploads (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    data {blob} NOT NULL,
    created_at {ts} NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_user ON uploads(user_id, created_at);
"""

# Columns added after the first release; older SQLite files get them on startup.
MIGRATIONS = [
    ("users", "github_id", "TEXT"),
    ("users", "github_login", "TEXT NOT NULL DEFAULT ''"),
    ("users", "avatar_url", "TEXT NOT NULL DEFAULT ''"),
    ("idea_tags", "pos", "INTEGER NOT NULL DEFAULT 0"),
]

POST_MIGRATION_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github ON users (github_id);
CREATE INDEX IF NOT EXISTS idx_ideas_created ON ideas (created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id);
"""

DIALECT_TOKENS = {
    "sqlite": {"{pk}": "INTEGER PRIMARY KEY", "{ts}": "REAL", "{blob}": "BLOB", "{nocase}": " COLLATE NOCASE"},
    "postgres": {"{pk}": "SERIAL PRIMARY KEY", "{ts}": "DOUBLE PRECISION", "{blob}": "BYTEA", "{nocase}": ""},
}

PG_FUNCTIONS = """
CREATE OR REPLACE FUNCTION hot_score(votes BIGINT, comments BIGINT, builds BIGINT, created_at DOUBLE PRECISION)
RETURNS DOUBLE PRECISION AS $$
    SELECT (1 + COALESCE(votes, 0) + 2 * COALESCE(comments, 0) + 4 * COALESCE(builds, 0))::DOUBLE PRECISION
           / power(GREATEST(0, (EXTRACT(EPOCH FROM clock_timestamp()) - COALESCE(created_at, 0)) / 3600) + 2, 1.4)
$$ LANGUAGE SQL VOLATILE;
"""


def schema_for(dialect: str) -> str:
    text = SCHEMA
    for token, value in DIALECT_TOKENS[dialect].items():
        text = text.replace(token, value)
    return text



# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #

def hot_score(votes, comments, builds, created_at):
    """Votes, discussion and builders lift an idea; age pulls it down."""
    age_hours = max(0.0, (time.time() - (created_at or 0)) / 3600)
    engagement = 1 + (votes or 0) + 2 * (comments or 0) + 4 * (builds or 0)
    return engagement / (age_hours + 2) ** 1.4


class Database:
    """Thin wrapper so the same SQL runs on SQLite and Postgres.

    Queries are written SQLite-style (`?` or `:name` placeholders, instr()).
    For Postgres they are rewritten once and cached.
    """

    def __init__(self, conn, dialect: str, pool=None):
        self.conn = conn
        self.dialect = dialect
        self.pool = pool

    @property
    def postgres(self) -> bool:
        return self.dialect == "postgres"

    def _sql(self, sql: str) -> str:
        return to_postgres(sql) if self.postgres else sql

    def execute(self, sql: str, params=()):
        return self.conn.execute(self._sql(sql), params)

    def executemany(self, sql: str, rows) -> None:
        rows = list(rows)
        if not rows:
            return
        if self.postgres:
            with self.conn.cursor() as cursor:
                cursor.executemany(self._sql(sql), rows)
        else:
            self.conn.executemany(sql, rows)

    def insert(self, sql: str, params=()) -> int:
        """Run an INSERT and return the new row id."""
        if self.postgres:
            return self.conn.execute(self._sql(sql) + " RETURNING id", params).fetchone()[0]
        return self.conn.execute(sql, params).lastrowid

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        if self.pool is not None:
            self.pool.release(self.conn)
        else:
            self.conn.close()


_PG_TOKEN_RE = re.compile(r"'(?:[^']|'')*'|\?|(?<![:\w]):([A-Za-z_]\w*)|%|\binstr\(", re.IGNORECASE)


@functools.lru_cache(maxsize=512)
def to_postgres(sql: str) -> str:
    def rewrite(match):
        token = match.group(0)
        if token.startswith("'"):
            return token.replace("%", "%%")
        if token == "?":
            return "%s"
        if token == "%":
            return "%%"
        if token.lower() == "instr(":
            return "strpos("
        return f"%({match.group(1)})s"

    return _PG_TOKEN_RE.sub(rewrite, sql)


class PgRow(tuple):
    """Row that works like sqlite3.Row: index or column-name access, keys()."""

    def __new__(cls, values, names, index):
        row = super().__new__(cls, values)
        row._names = names
        row._index = index
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


def pg_row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    index = {name: position for position, name in enumerate(names)}

    def make_row(values):
        return PgRow(values, names, index)

    return make_row


class PgPool:
    def __init__(self, url: str, size: int = 10):
        import psycopg  # noqa: F401 - imported lazily so SQLite users need nothing

        self.url = url
        self.idle: queue.LifoQueue = queue.LifoQueue(maxsize=size)

    def acquire(self):
        import psycopg

        while True:
            try:
                conn = self.idle.get_nowait()
            except queue.Empty:
                return psycopg.connect(self.url, row_factory=pg_row_factory, connect_timeout=10)
            if not conn.closed and not conn.broken:
                return conn

    def release(self, conn) -> None:
        if conn.closed or conn.broken:
            return
        try:
            conn.rollback()
            self.idle.put_nowait(conn)
        except Exception:  # noqa: BLE001 - pool full or connection unusable
            conn.close()


PG_POOL: PgPool | None = None


def connect() -> Database:
    if SETTINGS.postgres:
        global PG_POOL
        if PG_POOL is None:
            PG_POOL = PgPool(SETTINGS.database_url)
        return Database(PG_POOL.acquire(), "postgres", PG_POOL)
    conn = sqlite3.connect(SETTINGS.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.create_function("hot_score", 4, hot_score)
    return Database(conn, "sqlite")


def column_exists(db: Database, table: str, column: str) -> bool:
    if db.postgres:
        row = db.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        return row is not None
    return any(row["name"] == column for row in db.execute(f"PRAGMA table_info({table})"))


def init_db(reset: bool = False) -> None:
    if SETTINGS.postgres:
        db = connect()
        try:
            if reset:
                db.conn.execute(
                    "DROP TABLE IF EXISTS uploads, notifications, builds, board_items, boards, "
                    "comment_votes, comments, idea_votes, idea_tags, ideas, sessions, users CASCADE"
                )
            db.conn.execute(schema_for("postgres"))
            db.conn.execute(PG_FUNCTIONS)
            for table, column, ddl in MIGRATIONS:
                db.conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
            db.conn.execute(POST_MIGRATION_SQL)
            if SETTINGS.seed and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                seed(db)
            db.commit()
        finally:
            db.close()
        return

    db_path = SETTINGS.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
    db = connect()
    try:
        db.execute("PRAGMA journal_mode = WAL")
        db.conn.executescript(schema_for("sqlite"))
        for table, column, ddl in MIGRATIONS:
            if not column_exists(db, table, column):
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        db.conn.executescript(POST_MIGRATION_SQL)
        if SETTINGS.seed and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed(db)
        db.commit()
    finally:
        db.close()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return digest.hex(), salt


def verify_password(password: str, digest: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, digest)


def notify(db, user_id, actor_id, kind, idea_id, comment_id=None):
    if not user_id or user_id == actor_id:
        return
    db.execute(
        "INSERT INTO notifications (user_id, actor_id, kind, idea_id, comment_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, actor_id, kind, idea_id, comment_id, time.time()),
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def text_field(data, key, label, *, max_len, min_len=0):
    value = data.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{label} must be text")
    value = value.strip()
    if min_len and not value:
        raise ApiError(400, f"{label} is required")
    if len(value) < min_len:
        raise ApiError(400, f"{label} must be at least {min_len} characters")
    if len(value) > max_len:
        raise ApiError(400, f"{label} must be at most {max_len} characters")
    return value


def int_field(data, key, low, high, default):
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ApiError(400, f"Invalid {key}")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"Invalid {key}") from None
    if not low <= number <= high:
        raise ApiError(400, f"Invalid {key}")
    return number


def url_field(data, key, label):
    value = text_field(data, key, label, max_len=300)
    if value and not URL_RE.match(value):
        raise ApiError(400, f"{label} must be a full http(s) link")
    return value


def image_field(data, key, label):
    """An http(s) image link or a path returned by /api/uploads."""
    value = text_field(data, key, label, max_len=300)
    if value and not (URL_RE.match(value) or UPLOAD_PATH_RE.match(value)):
        raise ApiError(400, f"{label} must be an uploaded image or a full http(s) link")
    return value


def is_admin(user) -> bool:
    return bool(user) and user["username"].lower() in SETTINGS.admins


def normalize_tags(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        raise ApiError(400, "Tags must be a list")
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = TAG_CLEAN_RE.sub("", item.strip().lower().lstrip("#").replace(" ", "-"))[:24]
        if tag and tag not in tags:
            tags.append(tag)
    if len(tags) > 6:
        raise ApiError(400, "Use at most 6 tags")
    return tags


def validate_idea(data) -> dict:
    return {
        "title": text_field(data, "title", "Title", min_len=3, max_len=80),
        "pitch": text_field(data, "pitch", "Pitch", min_len=10, max_len=200),
        "body": text_field(data, "body", "Details", max_len=5000),
        "stack": text_field(data, "stack", "Stack", max_len=80),
        "scope": int_field(data, "scope", 0, 2, default=0),
        "cover_style": int_field(data, "cover_style", 0, COVER_STYLES - 1, default=0),
        "cover_image": image_field(data, "cover_image", "Cover image"),
        "tags": normalize_tags(data.get("tags")),
    }


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def user_public(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "bio": row["bio"],
        "avatar_hue": row["avatar_hue"],
        "avatar_url": row["avatar_url"] or "",
        "github_login": row["github_login"] or "",
        "created_at": row["created_at"],
    }


def user_private(row) -> dict:
    """What the signed-in user sees about themselves."""
    data = user_public(row)
    data["has_password"] = bool(row["password_hash"])
    data["is_admin"] = is_admin(row)
    return data


def author_of(row, prefix="") -> dict:
    keys = row.keys()
    return {
        "id": row[f"{prefix}user_id"] if f"{prefix}user_id" in keys else None,
        "username": row[f"{prefix}username"],
        "display_name": row[f"{prefix}display_name"],
        "avatar_hue": row[f"{prefix}avatar_hue"],
        "avatar_url": (row[f"{prefix}avatar_url"] or "") if f"{prefix}avatar_url" in keys else "",
    }


IDEA_SELECT = """
SELECT i.id, i.user_id, i.title, i.pitch, i.body, i.stack, i.scope, i.cover_style,
       i.cover_image, i.forked_from, i.created_at, i.updated_at,
       u.username, u.display_name, u.avatar_hue, u.avatar_url,
       (SELECT COUNT(*) FROM idea_votes v WHERE v.idea_id = i.id) AS votes,
       (SELECT COUNT(*) FROM comments c WHERE c.idea_id = i.id AND c.deleted = 0) AS comment_count,
       (SELECT COUNT(*) FROM builds b WHERE b.idea_id = i.id) AS builder_count,
       (SELECT COUNT(*) FROM builds b WHERE b.idea_id = i.id AND b.status = 'shipped') AS shipped_count,
       (SELECT COUNT(*) FROM ideas f WHERE f.forked_from = i.id AND f.deleted = 0) AS fork_count,
       (SELECT COUNT(*) FROM board_items bi WHERE bi.idea_id = i.id) AS save_count,
       EXISTS (SELECT 1 FROM idea_votes v WHERE v.idea_id = i.id AND v.user_id = :viewer) AS voted,
       EXISTS (SELECT 1 FROM board_items bi JOIN boards bo ON bo.id = bi.board_id
               WHERE bi.idea_id = i.id AND bo.user_id = :viewer) AS saved
FROM ideas i
JOIN users u ON u.id = i.user_id
WHERE i.deleted = 0
"""

ORDER_SQL = {
    "hot": "hot_score(votes, comment_count, builder_count, created_at) DESC, id DESC",
    "new": "created_at DESC, id DESC",
    "top": "votes DESC, comment_count DESC, id DESC",
    "discussed": "comment_count DESC, votes DESC, id DESC",
    "saved": "(SELECT MAX(bi.created_at) FROM board_items bi WHERE bi.board_id = :board AND bi.idea_id = x.id) DESC",
}

STATUS_SQL = {
    "open": "WHERE builder_count = 0",
    "building": "WHERE builder_count > 0 AND shipped_count = 0",
    "shipped": "WHERE shipped_count > 0",
}


def tags_for(db, ids) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {idea_id: [] for idea_id in ids}
    if not ids:
        return result
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT idea_id, tag FROM idea_tags WHERE idea_id IN ({marks}) "
        f"ORDER BY pos{'' if db.postgres else ', rowid'}",
        list(ids),
    )
    for idea_id, tag in rows:
        result[idea_id].append(tag)
    return result


def serialize_idea(row, tags, with_body) -> dict:
    if row["shipped_count"]:
        status = "shipped"
    elif row["builder_count"]:
        status = "building"
    else:
        status = "open"
    return {
        "id": row["id"],
        "title": row["title"],
        "pitch": row["pitch"],
        "body": row["body"] if with_body else None,
        "stack": row["stack"],
        "scope": row["scope"],
        "cover_style": row["cover_style"],
        "cover_image": row["cover_image"],
        "forked_from": row["forked_from"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "author": author_of(row),
        "tags": tags,
        "votes": row["votes"],
        "comment_count": row["comment_count"],
        "builder_count": row["builder_count"],
        "shipped_count": row["shipped_count"],
        "fork_count": row["fork_count"],
        "save_count": row["save_count"],
        "voted": bool(row["voted"]),
        "saved": bool(row["saved"]),
        "status": status,
    }


def query_ideas(db, viewer_id, *, where="", outer="", params=None, order="hot",
                limit=30, offset=0, with_body=False):
    values = dict(params or {})
    values.update(viewer=viewer_id, limit=limit + 1, offset=offset)
    values.setdefault("board", 0)
    sql = (
        f"SELECT * FROM ({IDEA_SELECT} {where}) AS x {outer} "
        f"ORDER BY {ORDER_SQL.get(order, ORDER_SQL['hot'])} LIMIT :limit OFFSET :offset"
    )
    rows = db.execute(sql, values).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    tag_map = tags_for(db, [row["id"] for row in rows])
    return [serialize_idea(row, tag_map[row["id"]], with_body) for row in rows], has_more


def load_idea_owner(db, idea_id):
    row = db.execute("SELECT id, user_id, title FROM ideas WHERE id = ? AND deleted = 0", (idea_id,)).fetchone()
    if not row:
        raise ApiError(404, "This idea doesn't exist or was deleted")
    return row


def idea_detail(db, idea_id, viewer_id) -> dict:
    items, _ = query_ideas(
        db,
        viewer_id,
        where="AND i.id = :id",
        params={"id": idea_id},
        limit=1,
        with_body=True,
    )
    if not items:
        raise ApiError(404, "This idea doesn't exist or was deleted")
    idea = items[0]

    comments = []
    rows = db.execute(
        """
        SELECT c.id, c.parent_id, c.body, c.deleted, c.created_at, c.edited_at, c.user_id,
               u.username, u.display_name, u.avatar_hue, u.avatar_url,
               (SELECT COUNT(*) FROM comment_votes cv WHERE cv.comment_id = c.id) AS votes,
               EXISTS (SELECT 1 FROM comment_votes cv
                       WHERE cv.comment_id = c.id AND cv.user_id = :viewer) AS voted
        FROM comments c JOIN users u ON u.id = c.user_id
        WHERE c.idea_id = :id
        ORDER BY c.created_at
        """,
        {"id": idea_id, "viewer": viewer_id},
    )
    for row in rows:
        deleted = bool(row["deleted"])
        comments.append({
            "id": row["id"],
            "parent_id": row["parent_id"],
            "body": "" if deleted else row["body"],
            "deleted": deleted,
            "created_at": row["created_at"],
            "edited_at": row["edited_at"],
            "votes": row["votes"],
            "voted": bool(row["voted"]),
            "author": None if deleted else author_of(row),
        })

    builds = []
    rows = db.execute(
        """
        SELECT b.id, b.status, b.repo_url, b.demo_url, b.note, b.created_at, b.updated_at,
               b.user_id, u.username, u.display_name, u.avatar_hue, u.avatar_url
        FROM builds b JOIN users u ON u.id = b.user_id
        WHERE b.idea_id = ?
        ORDER BY (b.status = 'shipped') DESC, b.updated_at DESC
        """,
        (idea_id,),
    )
    for row in rows:
        builds.append({
            "id": row["id"],
            "status": row["status"],
            "repo_url": row["repo_url"],
            "demo_url": row["demo_url"],
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "user": author_of(row),
            "mine": row["user_id"] == viewer_id,
        })

    forked_from = None
    if idea["forked_from"]:
        row = db.execute(
            "SELECT i.id, i.title, u.username FROM ideas i JOIN users u ON u.id = i.user_id "
            "WHERE i.id = ? AND i.deleted = 0",
            (idea["forked_from"],),
        ).fetchone()
        if row:
            forked_from = {"id": row["id"], "title": row["title"], "username": row["username"]}

    forks = []
    rows = db.execute(
        """
        SELECT i.id, i.title, i.user_id, u.username, u.display_name, u.avatar_hue, u.avatar_url
        FROM ideas i JOIN users u ON u.id = i.user_id
        WHERE i.forked_from = ? AND i.deleted = 0
        ORDER BY i.created_at DESC LIMIT 12
        """,
        (idea_id,),
    )
    for row in rows:
        forks.append({"id": row["id"], "title": row["title"], "author": author_of(row)})

    return {
        "idea": idea,
        "comments": comments,
        "builds": builds,
        "forked_from": forked_from,
        "forks": forks,
    }


def comment_owner(db, comment_id):
    row = db.execute(
        "SELECT c.id, c.user_id, c.idea_id, c.deleted FROM comments c "
        "JOIN ideas i ON i.id = c.idea_id WHERE c.id = ? AND i.deleted = 0",
        (comment_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "Comment not found")
    return row


def board_row(db, board_id):
    row = db.execute(
        """
        SELECT b.*, u.username, u.display_name, u.avatar_hue, u.avatar_url,
               (SELECT COUNT(*) FROM board_items bi JOIN ideas i ON i.id = bi.idea_id
                WHERE bi.board_id = b.id AND i.deleted = 0) AS item_count
        FROM boards b JOIN users u ON u.id = b.user_id
        WHERE b.id = ?
        """,
        (board_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "Board not found")
    return row


def board_previews(db, board_id):
    rows = db.execute(
        """
        SELECT i.id, i.title, i.pitch, i.cover_style, i.cover_image
        FROM board_items bi JOIN ideas i ON i.id = bi.idea_id
        WHERE bi.board_id = ? AND i.deleted = 0
        ORDER BY bi.created_at DESC LIMIT 3
        """,
        (board_id,),
    )
    return [dict(row) for row in rows]


def serialize_board(db, row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "item_count": row["item_count"],
        "owner": author_of(row),
        "previews": board_previews(db, row["id"]),
    }


def user_has_saved(db, user_id, idea_id) -> bool:
    row = db.execute(
        "SELECT 1 FROM board_items bi JOIN boards b ON b.id = bi.board_id "
        "WHERE b.user_id = ? AND bi.idea_id = ? LIMIT 1",
        (user_id, idea_id),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

ROUTES: list[tuple[str, re.Pattern, object, bool, bool]] = []


def route(method: str, path: str, auth: bool = False, raw: bool = False):
    """Register an API handler. raw=True receives the request bytes instead of JSON."""
    pattern = re.compile("^" + re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", path) + "$")

    def decorator(func):
        ROUTES.append((method, pattern, func, auth, raw))
        return func

    return decorator


class Ctx:
    def __init__(self, db, user, query, params, body, *, raw=None, secure=False):
        self.db = db
        self.user = user
        self.query = query
        self.params = params
        self.body = body
        self.raw = raw
        self.secure = secure
        self.set_cookies: list[str] = []

    @property
    def viewer_id(self) -> int:
        return self.user["id"] if self.user else 0

    def q(self, key, default=""):
        values = self.query.get(key)
        return values[0] if values else default

    def q_int(self, key, default, low, high):
        try:
            value = int(self.q(key, default))
        except ValueError:
            return default
        return max(low, min(high, value))

    def param_id(self, key="id") -> int:
        try:
            return int(self.params[key])
        except (KeyError, ValueError):
            raise ApiError(404, "Not found") from None

    def require_user(self):
        if not self.user:
            raise ApiError(401, "Log in to do that")
        return self.user


def session_cookie(token: str, max_age: int, secure: bool = False) -> str:
    flags = "; Secure" if secure else ""
    return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{flags}"


def create_session(db, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, now + SESSION_SECONDS),
    )
    if random.random() < 0.05:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return token


def start_session(ctx: Ctx, user_id: int) -> None:
    token = create_session(ctx.db, user_id)
    ctx.set_cookies.append(session_cookie(token, SESSION_SECONDS, ctx.secure))


def unread_count(db, user_id) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()[0]


# ----- Auth ---------------------------------------------------------------- #

@route("POST", "/api/auth/signup")
def signup(ctx: Ctx):
    username = text_field(ctx.body, "username", "Username", min_len=3, max_len=20)
    if not USERNAME_RE.match(username):
        raise ApiError(400, "Username can only use letters, numbers and underscores")
    password = ctx.body.get("password") or ""
    if not isinstance(password, str) or len(password) < 8:
        raise ApiError(400, "Password must be at least 8 characters")
    if len(password) > 128:
        raise ApiError(400, "Password is too long")
    display_name = text_field(ctx.body, "display_name", "Display name", max_len=40) or username
    if ctx.db.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (username,)).fetchone():
        raise ApiError(409, "That username is taken")
    digest, salt = hash_password(password)
    user_id = ctx.db.insert(
        "INSERT INTO users (username, display_name, avatar_hue, password_hash, password_salt, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, display_name, random.randint(0, 359), digest, salt, time.time()),
    )
    start_session(ctx, user_id)
    row = ctx.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"user": user_private(row), "unread": 0}


@route("POST", "/api/auth/login")
def login(ctx: Ctx):
    username = text_field(ctx.body, "username", "Username", min_len=1, max_len=40)
    password = ctx.body.get("password") or ""
    row = ctx.db.execute("SELECT * FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
    if row and not row["password_hash"]:
        raise ApiError(401, "This account signs in with GitHub")
    if not row or not isinstance(password, str) or not verify_password(
        password, row["password_hash"], row["password_salt"]
    ):
        raise ApiError(401, "Wrong username or password")
    start_session(ctx, row["id"])
    return {"user": user_private(row), "unread": unread_count(ctx.db, row["id"])}


@route("POST", "/api/auth/logout")
def logout(ctx: Ctx):
    token = ctx.params.get("_session_token")
    if token:
        ctx.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    ctx.set_cookies.append(session_cookie("", 0, ctx.secure))
    return {"ok": True}


@route("GET", "/api/me")
def me(ctx: Ctx):
    if not ctx.user:
        return {"user": None, "unread": 0}
    return {"user": user_private(ctx.user), "unread": unread_count(ctx.db, ctx.user["id"])}


@route("PATCH", "/api/me", auth=True)
def update_me(ctx: Ctx):
    display_name = text_field(ctx.body, "display_name", "Display name", min_len=1, max_len=40)
    bio = text_field(ctx.body, "bio", "Bio", max_len=280)
    avatar_url = ctx.user["avatar_url"] or ""
    if "avatar_url" in ctx.body:
        avatar_url = image_field(ctx.body, "avatar_url", "Avatar")
    ctx.db.execute(
        "UPDATE users SET display_name = ?, bio = ?, avatar_url = ? WHERE id = ?",
        (display_name, bio, avatar_url, ctx.user["id"]),
    )
    row = ctx.db.execute("SELECT * FROM users WHERE id = ?", (ctx.user["id"],)).fetchone()
    return {"user": user_private(row)}


@route("GET", "/api/config")
def client_config(ctx: Ctx):
    return {
        "github": SETTINGS.github_enabled,
        "demo": SETTINGS.demo,
        "max_upload_bytes": SETTINGS.max_upload_bytes,
    }


# ----- Uploads -------------------------------------------------------------- #

def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@route("POST", "/api/uploads", auth=True, raw=True)
def upload_image(ctx: Ctx):
    data = ctx.raw or b""
    if not data:
        raise ApiError(400, "The upload was empty")
    mime = sniff_image(data)
    if not mime:
        raise ApiError(415, "Only PNG, JPEG, GIF or WebP images can be uploaded")
    recent = ctx.db.execute(
        "SELECT COUNT(*) FROM uploads WHERE user_id = ? AND created_at > ?",
        (ctx.user["id"], time.time() - 3600),
    ).fetchone()[0]
    if recent >= UPLOADS_PER_HOUR:
        raise ApiError(429, "You've uploaded a lot of images. Try again in a little while.")
    token = secrets.token_urlsafe(18)
    ctx.db.insert(
        "INSERT INTO uploads (user_id, token, mime, size, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (ctx.user["id"], token, mime, len(data), data, time.time()),
    )
    return {"url": f"/uploads/{token}.{IMAGE_TYPES[mime]}", "size": len(data), "mime": mime}


# ----- Ideas ---------------------------------------------------------------- #

@route("GET", "/api/ideas")
def list_ideas(ctx: Ctx):
    sort = ctx.q("sort", "hot")
    if sort not in ORDER_SQL:
        sort = "hot"
    limit = ctx.q_int("limit", 30, 1, 60)
    offset = ctx.q_int("offset", 0, 0, 1_000_000)
    where: list[str] = []
    params: dict = {}

    tag = ctx.q("tag").strip().lower()
    if tag:
        where.append("AND EXISTS (SELECT 1 FROM idea_tags t WHERE t.idea_id = i.id AND t.tag = :tag)")
        params["tag"] = tag

    search = ctx.q("q").strip().lower()[:100]
    if search:
        where.append(
            "AND (instr(lower(i.title || ' ' || i.pitch || ' ' || i.body || ' ' || i.stack), :q) > 0 "
            "OR instr(lower(u.username || ' ' || u.display_name), :q) > 0 "
            "OR EXISTS (SELECT 1 FROM idea_tags t WHERE t.idea_id = i.id AND instr(t.tag, :q) > 0))"
        )
        params["q"] = search

    author = ctx.q("author").strip()
    if author:
        where.append("AND lower(u.username) = lower(:author)")
        params["author"] = author

    builder = ctx.q("builder").strip()
    if builder:
        where.append(
            "AND EXISTS (SELECT 1 FROM builds b JOIN users bu ON bu.id = b.user_id "
            "WHERE b.idea_id = i.id AND lower(bu.username) = lower(:builder))"
        )
        params["builder"] = builder

    board_id = ctx.q_int("board", 0, 0, 10**12)
    if board_id:
        board_row(ctx.db, board_id)
        where.append("AND EXISTS (SELECT 1 FROM board_items bi WHERE bi.idea_id = i.id AND bi.board_id = :board)")
        params["board"] = board_id
    elif sort == "saved":
        sort = "new"

    related = ctx.q_int("related", 0, 0, 10**12)
    if related:
        where.append(
            "AND i.id != :related AND EXISTS (SELECT 1 FROM idea_tags t WHERE t.idea_id = i.id "
            "AND t.tag IN (SELECT tag FROM idea_tags WHERE idea_id = :related))"
        )
        params["related"] = related

    items, has_more = query_ideas(
        ctx.db,
        ctx.viewer_id,
        where=" ".join(where),
        outer=STATUS_SQL.get(ctx.q("status"), ""),
        params=params,
        order=sort,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "has_more": has_more}


@route("POST", "/api/ideas", auth=True)
def create_idea(ctx: Ctx):
    fields = validate_idea(ctx.body)
    forked_from = ctx.body.get("forked_from")
    parent = None
    if forked_from:
        parent = load_idea_owner(ctx.db, int_field(ctx.body, "forked_from", 1, 10**12, None))
    now = time.time()
    idea_id = ctx.db.insert(
        "INSERT INTO ideas (user_id, title, pitch, body, stack, scope, cover_style, cover_image, "
        "forked_from, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ctx.user["id"], fields["title"], fields["pitch"], fields["body"], fields["stack"],
            fields["scope"], fields["cover_style"], fields["cover_image"],
            parent["id"] if parent else None, now, now,
        ),
    )
    ctx.db.executemany(
        "INSERT INTO idea_tags (idea_id, tag, pos) VALUES (?, ?, ?)",
        [(idea_id, tag, pos) for pos, tag in enumerate(fields["tags"])],
    )
    ctx.db.execute(
        "INSERT INTO idea_votes (idea_id, user_id, created_at) VALUES (?, ?, ?)",
        (idea_id, ctx.user["id"], now),
    )
    if parent:
        notify(ctx.db, parent["user_id"], ctx.user["id"], "fork", idea_id)
    return idea_detail(ctx.db, idea_id, ctx.viewer_id)


@route("GET", "/api/ideas/<id>")
def get_idea(ctx: Ctx):
    return idea_detail(ctx.db, ctx.param_id(), ctx.viewer_id)


@route("PATCH", "/api/ideas/<id>", auth=True)
def update_idea(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    if idea["user_id"] != ctx.user["id"]:
        raise ApiError(403, "Only the author can edit this idea")
    fields = validate_idea(ctx.body)
    ctx.db.execute(
        "UPDATE ideas SET title = ?, pitch = ?, body = ?, stack = ?, scope = ?, cover_style = ?, "
        "cover_image = ?, updated_at = ? WHERE id = ?",
        (
            fields["title"], fields["pitch"], fields["body"], fields["stack"], fields["scope"],
            fields["cover_style"], fields["cover_image"], time.time(), idea["id"],
        ),
    )
    ctx.db.execute("DELETE FROM idea_tags WHERE idea_id = ?", (idea["id"],))
    ctx.db.executemany(
        "INSERT INTO idea_tags (idea_id, tag, pos) VALUES (?, ?, ?)",
        [(idea["id"], tag, pos) for pos, tag in enumerate(fields["tags"])],
    )
    return idea_detail(ctx.db, idea["id"], ctx.viewer_id)


@route("DELETE", "/api/ideas/<id>", auth=True)
def delete_idea(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    if idea["user_id"] != ctx.user["id"] and not is_admin(ctx.user):
        raise ApiError(403, "Only the author can delete this idea")
    ctx.db.execute("UPDATE ideas SET deleted = 1, updated_at = ? WHERE id = ?", (time.time(), idea["id"]))
    return {"ok": True}


@route("POST", "/api/ideas/<id>/vote", auth=True)
def vote_idea(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    key = (idea["id"], ctx.user["id"])
    existing = ctx.db.execute("SELECT 1 FROM idea_votes WHERE idea_id = ? AND user_id = ?", key).fetchone()
    if existing:
        ctx.db.execute("DELETE FROM idea_votes WHERE idea_id = ? AND user_id = ?", key)
    else:
        ctx.db.execute("INSERT INTO idea_votes (idea_id, user_id, created_at) VALUES (?, ?, ?)", (*key, time.time()))
    votes = ctx.db.execute("SELECT COUNT(*) FROM idea_votes WHERE idea_id = ?", (idea["id"],)).fetchone()[0]
    return {"voted": not existing, "votes": votes}


# ----- Comments ------------------------------------------------------------- #

@route("POST", "/api/ideas/<id>/comments", auth=True)
def create_comment(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    body = text_field(ctx.body, "body", "Comment", min_len=1, max_len=4000)
    parent = None
    if ctx.body.get("parent_id"):
        parent_id = int_field(ctx.body, "parent_id", 1, 10**12, None)
        parent = ctx.db.execute(
            "SELECT id, user_id, deleted FROM comments WHERE id = ? AND idea_id = ?",
            (parent_id, idea["id"]),
        ).fetchone()
        if not parent or parent["deleted"]:
            raise ApiError(400, "You can't reply to that comment")
    comment_id = ctx.db.insert(
        "INSERT INTO comments (idea_id, user_id, parent_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (idea["id"], ctx.user["id"], parent["id"] if parent else None, body, time.time()),
    )
    ctx.db.execute("INSERT INTO comment_votes (comment_id, user_id) VALUES (?, ?)", (comment_id, ctx.user["id"]))
    if parent:
        notify(ctx.db, parent["user_id"], ctx.user["id"], "reply", idea["id"], comment_id)
    if not parent or parent["user_id"] != idea["user_id"]:
        notify(ctx.db, idea["user_id"], ctx.user["id"], "comment", idea["id"], comment_id)
    return {"id": comment_id}


@route("PATCH", "/api/comments/<id>", auth=True)
def edit_comment(ctx: Ctx):
    comment = comment_owner(ctx.db, ctx.param_id())
    if comment["user_id"] != ctx.user["id"] or comment["deleted"]:
        raise ApiError(403, "You can only edit your own comments")
    body = text_field(ctx.body, "body", "Comment", min_len=1, max_len=4000)
    ctx.db.execute("UPDATE comments SET body = ?, edited_at = ? WHERE id = ?", (body, time.time(), comment["id"]))
    return {"ok": True}


@route("DELETE", "/api/comments/<id>", auth=True)
def delete_comment(ctx: Ctx):
    comment = comment_owner(ctx.db, ctx.param_id())
    if comment["user_id"] != ctx.user["id"] and not is_admin(ctx.user):
        raise ApiError(403, "You can only delete your own comments")
    ctx.db.execute("UPDATE comments SET deleted = 1, body = '' WHERE id = ?", (comment["id"],))
    return {"ok": True}


@route("POST", "/api/comments/<id>/vote", auth=True)
def vote_comment(ctx: Ctx):
    comment = comment_owner(ctx.db, ctx.param_id())
    if comment["deleted"]:
        raise ApiError(400, "That comment was deleted")
    key = (comment["id"], ctx.user["id"])
    existing = ctx.db.execute(
        "SELECT 1 FROM comment_votes WHERE comment_id = ? AND user_id = ?", key
    ).fetchone()
    if existing:
        ctx.db.execute("DELETE FROM comment_votes WHERE comment_id = ? AND user_id = ?", key)
    else:
        ctx.db.execute("INSERT INTO comment_votes (comment_id, user_id) VALUES (?, ?)", key)
    votes = ctx.db.execute(
        "SELECT COUNT(*) FROM comment_votes WHERE comment_id = ?", (comment["id"],)
    ).fetchone()[0]
    return {"voted": not existing, "votes": votes}


# ----- Builds ---------------------------------------------------------------- #

@route("POST", "/api/ideas/<id>/build", auth=True)
def upsert_build(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    status = ctx.body.get("status", "building")
    if status not in BUILD_STATUSES:
        raise ApiError(400, "Status must be building or shipped")
    repo_url = url_field(ctx.body, "repo_url", "Repository link")
    demo_url = url_field(ctx.body, "demo_url", "Demo link")
    note = text_field(ctx.body, "note", "Note", max_len=280)
    now = time.time()
    existing = ctx.db.execute(
        "SELECT id, status FROM builds WHERE idea_id = ? AND user_id = ?",
        (idea["id"], ctx.user["id"]),
    ).fetchone()
    if existing:
        ctx.db.execute(
            "UPDATE builds SET status = ?, repo_url = ?, demo_url = ?, note = ?, updated_at = ? WHERE id = ?",
            (status, repo_url, demo_url, note, now, existing["id"]),
        )
    else:
        ctx.db.execute(
            "INSERT INTO builds (idea_id, user_id, status, repo_url, demo_url, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (idea["id"], ctx.user["id"], status, repo_url, demo_url, note, now, now),
        )
    if not existing or existing["status"] != status:
        notify(ctx.db, idea["user_id"], ctx.user["id"], "shipped" if status == "shipped" else "build", idea["id"])
    return {"ok": True}


@route("DELETE", "/api/ideas/<id>/build", auth=True)
def delete_build(ctx: Ctx):
    idea = load_idea_owner(ctx.db, ctx.param_id())
    ctx.db.execute("DELETE FROM builds WHERE idea_id = ? AND user_id = ?", (idea["id"], ctx.user["id"]))
    return {"ok": True}


# ----- Boards ---------------------------------------------------------------- #

@route("GET", "/api/boards")
def list_boards(ctx: Ctx):
    username = ctx.q("user").strip()
    if username:
        owner = ctx.db.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
        if not owner:
            raise ApiError(404, "User not found")
        owner_id = owner["id"]
    else:
        owner_id = ctx.require_user()["id"]
    idea_id = ctx.q_int("idea", 0, 0, 10**12)
    rows = ctx.db.execute(
        """
        SELECT b.*, u.username, u.display_name, u.avatar_hue, u.avatar_url,
               (SELECT COUNT(*) FROM board_items bi JOIN ideas i ON i.id = bi.idea_id
                WHERE bi.board_id = b.id AND i.deleted = 0) AS item_count,
               EXISTS (SELECT 1 FROM board_items bi WHERE bi.board_id = b.id AND bi.idea_id = :idea) AS contains,
               COALESCE((SELECT MAX(bi.created_at) FROM board_items bi WHERE bi.board_id = b.id), b.created_at) AS touched
        FROM boards b JOIN users u ON u.id = b.user_id
        WHERE b.user_id = :owner
        ORDER BY touched DESC
        """,
        {"owner": owner_id, "idea": idea_id},
    ).fetchall()
    boards = []
    for row in rows:
        board = serialize_board(ctx.db, row)
        board["contains"] = bool(row["contains"])
        boards.append(board)
    return {"boards": boards}


@route("POST", "/api/boards", auth=True)
def create_board(ctx: Ctx):
    name = text_field(ctx.body, "name", "Board name", min_len=1, max_len=40)
    description = text_field(ctx.body, "description", "Description", max_len=200)
    duplicate = ctx.db.execute(
        "SELECT 1 FROM boards WHERE user_id = ? AND lower(name) = lower(?)",
        (ctx.user["id"], name),
    ).fetchone()
    if duplicate:
        raise ApiError(409, "You already have a board with that name")
    now = time.time()
    board_id = ctx.db.insert(
        "INSERT INTO boards (user_id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (ctx.user["id"], name, description, now),
    )
    if ctx.body.get("idea_id"):
        idea = load_idea_owner(ctx.db, int_field(ctx.body, "idea_id", 1, 10**12, None))
        ctx.db.execute(
            "INSERT INTO board_items (board_id, idea_id, created_at) VALUES (?, ?, ?)",
            (board_id, idea["id"], now),
        )
    return {"board": serialize_board(ctx.db, board_row(ctx.db, board_id))}


@route("GET", "/api/boards/<id>")
def get_board(ctx: Ctx):
    return {"board": serialize_board(ctx.db, board_row(ctx.db, ctx.param_id()))}


def owned_board(ctx: Ctx):
    row = board_row(ctx.db, ctx.param_id())
    if row["user_id"] != ctx.user["id"]:
        raise ApiError(403, "That's not your board")
    return row


@route("PATCH", "/api/boards/<id>", auth=True)
def update_board(ctx: Ctx):
    row = owned_board(ctx)
    name = text_field(ctx.body, "name", "Board name", min_len=1, max_len=40)
    description = text_field(ctx.body, "description", "Description", max_len=200)
    ctx.db.execute("UPDATE boards SET name = ?, description = ? WHERE id = ?", (name, description, row["id"]))
    return {"board": serialize_board(ctx.db, board_row(ctx.db, row["id"]))}


@route("DELETE", "/api/boards/<id>", auth=True)
def delete_board(ctx: Ctx):
    row = owned_board(ctx)
    ctx.db.execute("DELETE FROM boards WHERE id = ?", (row["id"],))
    return {"ok": True}


@route("POST", "/api/boards/<id>/items", auth=True)
def toggle_board_item(ctx: Ctx):
    row = owned_board(ctx)
    idea = load_idea_owner(ctx.db, int_field(ctx.body, "idea_id", 1, 10**12, None))
    key = (row["id"], idea["id"])
    existing = ctx.db.execute("SELECT 1 FROM board_items WHERE board_id = ? AND idea_id = ?", key).fetchone()
    if existing:
        ctx.db.execute("DELETE FROM board_items WHERE board_id = ? AND idea_id = ?", key)
    else:
        ctx.db.execute(
            "INSERT INTO board_items (board_id, idea_id, created_at) VALUES (?, ?, ?)",
            (*key, time.time()),
        )
    return {"contains": not existing, "saved": user_has_saved(ctx.db, ctx.user["id"], idea["id"])}


# ----- Users, tags, notifications, misc ------------------------------------- #

@route("GET", "/api/users/<username>")
def get_user(ctx: Ctx):
    row = ctx.db.execute(
        "SELECT * FROM users WHERE lower(username) = lower(?)", (ctx.params["username"],)
    ).fetchone()
    if not row:
        raise ApiError(404, "User not found")
    stats = ctx.db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM ideas WHERE user_id = :u AND deleted = 0) AS ideas,
          (SELECT COUNT(*) FROM idea_votes v JOIN ideas i ON i.id = v.idea_id
           WHERE i.user_id = :u AND i.deleted = 0 AND v.user_id != :u) AS upvotes,
          (SELECT COUNT(*) FROM builds b JOIN ideas i ON i.id = b.idea_id
           WHERE b.user_id = :u AND i.deleted = 0 AND b.status = 'building') AS building,
          (SELECT COUNT(*) FROM builds b JOIN ideas i ON i.id = b.idea_id
           WHERE b.user_id = :u AND i.deleted = 0 AND b.status = 'shipped') AS shipped,
          (SELECT COUNT(*) FROM boards WHERE user_id = :u) AS boards
        """,
        {"u": row["id"]},
    ).fetchone()
    return {"user": user_public(row), "stats": dict(stats)}


@route("GET", "/api/tags")
def list_tags(ctx: Ctx):
    rows = ctx.db.execute(
        "SELECT t.tag, COUNT(*) AS n FROM idea_tags t JOIN ideas i ON i.id = t.idea_id "
        "WHERE i.deleted = 0 GROUP BY t.tag ORDER BY n DESC, t.tag LIMIT 40"
    )
    return {"tags": [{"tag": tag, "count": count} for tag, count in rows]}


@route("GET", "/api/stats")
def site_stats(ctx: Ctx):
    row = ctx.db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM ideas WHERE deleted = 0) AS ideas,
          (SELECT COUNT(*) FROM builds b JOIN ideas i ON i.id = b.idea_id WHERE i.deleted = 0) AS builds,
          (SELECT COUNT(*) FROM builds b JOIN ideas i ON i.id = b.idea_id
           WHERE i.deleted = 0 AND b.status = 'shipped') AS shipped,
          (SELECT COUNT(*) FROM users) AS makers
        """
    ).fetchone()
    return dict(row)


@route("GET", "/api/random")
def random_idea(ctx: Ctx):
    row = ctx.db.execute("SELECT id FROM ideas WHERE deleted = 0 ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        raise ApiError(404, "No ideas yet")
    return {"id": row["id"]}


@route("GET", "/api/notifications", auth=True)
def list_notifications(ctx: Ctx):
    rows = ctx.db.execute(
        """
        SELECT n.id, n.kind, n.idea_id, n.comment_id, n.is_read, n.created_at,
               a.id AS user_id, a.username, a.display_name, a.avatar_hue, a.avatar_url, i.title AS idea_title
        FROM notifications n
        JOIN users a ON a.id = n.actor_id
        LEFT JOIN ideas i ON i.id = n.idea_id
        WHERE n.user_id = ? AND (i.id IS NULL OR i.deleted = 0)
        ORDER BY n.created_at DESC LIMIT 40
        """,
        (ctx.user["id"],),
    )
    items = [
        {
            "id": row["id"],
            "kind": row["kind"],
            "idea_id": row["idea_id"],
            "idea_title": row["idea_title"],
            "is_read": bool(row["is_read"]),
            "created_at": row["created_at"],
            "actor": author_of(row),
        }
        for row in rows
    ]
    return {"items": items}


@route("POST", "/api/notifications/read", auth=True)
def read_notifications(ctx: Ctx):
    ctx.db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (ctx.user["id"],))
    return {"ok": True}


# --------------------------------------------------------------------------- #
# GitHub sign-in
# --------------------------------------------------------------------------- #

class OAuthError(Exception):
    pass


GITHUB_AVATAR_PREFIX = "https://avatars.githubusercontent.com/"


def http_json(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: float = 10):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    host = (urlparse(url).hostname or "").lower()
    handlers = [urllib.request.ProxyHandler({})] if host in ("127.0.0.1", "localhost", "::1") else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise OAuthError(f"GitHub returned an error ({error.code})") from None


def github_exchange_code(code: str, redirect_uri: str) -> str:
    payload = urlencode({
        "client_id": SETTINGS.github_client_id,
        "client_secret": SETTINGS.github_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("ascii")
    data = http_json(
        f"{SETTINGS.github_oauth_url}/login/oauth/access_token",
        data=payload,
        headers={"Accept": "application/json", "User-Agent": "shiphub"},
    )
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        message = data.get("error_description") if isinstance(data, dict) else None
        raise OAuthError(message or "GitHub didn't return an access token")
    return token


def github_fetch_user(token: str) -> dict:
    profile = http_json(
        f"{SETTINGS.github_api_url}/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "shiphub",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if not isinstance(profile, dict) or not profile.get("id") or not profile.get("login"):
        raise OAuthError("GitHub didn't return a profile")
    return profile


def unique_username(db, login: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", login).strip("_")[:20] or "maker"
    if len(base) < 3:
        base = f"{base}_gh"
    candidate = base
    number = 1
    while db.execute("SELECT 1 FROM users WHERE lower(username) = lower(?)", (candidate,)).fetchone():
        number += 1
        suffix = str(number)
        candidate = base[: 20 - len(suffix)] + suffix
    return candidate


def github_sign_in(db, profile: dict, current_user) -> tuple[int, str]:
    """Log in, sign up, or link the GitHub account. Returns (user_id, outcome)."""
    github_id = str(profile["id"])
    login = str(profile["login"])[:39]
    avatar = str(profile.get("avatar_url") or "")
    if not URL_RE.match(avatar):
        avatar = ""
    existing = db.execute("SELECT * FROM users WHERE github_id = ?", (github_id,)).fetchone()

    def refreshed_avatar(row) -> str:
        current = row["avatar_url"] or ""
        if not current or current.startswith(GITHUB_AVATAR_PREFIX):
            return avatar or current
        return current

    if current_user:
        if existing and existing["id"] != current_user["id"]:
            raise OAuthError(f"That GitHub account is already connected to @{existing['username']}")
        db.execute(
            "UPDATE users SET github_id = ?, github_login = ?, avatar_url = ? WHERE id = ?",
            (github_id, login, refreshed_avatar(current_user), current_user["id"]),
        )
        return current_user["id"], "linked"

    if existing:
        db.execute(
            "UPDATE users SET github_login = ?, avatar_url = ? WHERE id = ?",
            (login, refreshed_avatar(existing), existing["id"]),
        )
        return existing["id"], "login"

    display_name = str(profile.get("name") or login).strip()[:40] or login
    bio = str(profile.get("bio") or "").strip()[:280]
    user_id = db.insert(
        "INSERT INTO users (username, display_name, bio, avatar_hue, avatar_url, password_hash, "
        "password_salt, github_id, github_login, created_at) VALUES (?, ?, ?, ?, ?, '', '', ?, ?, ?)",
        (unique_username(db, login), display_name, bio, random.randint(0, 359), avatar, github_id, login, time.time()),
    )
    return user_id, "signup"


def safe_next(value: str) -> str:
    """Only allow in-app hash routes as a post-login destination."""
    if isinstance(value, str) and value.startswith("#/") and len(value) <= 200 and "\n" not in value:
        return value
    return "#/"


def oauth_cookie(value: str, max_age: int, secure: bool) -> str:
    flags = "; Secure" if secure else ""
    return f"{OAUTH_COOKIE}={value}; Path=/auth/github; HttpOnly; SameSite=Lax; Max-Age={max_age}{flags}"


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Sliding-window counters kept in memory (per process)."""

    def __init__(self) -> None:
        self.hits: dict[tuple, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: tuple, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self.lock:
            bucket = self.hits.setdefault(key, deque())
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if len(self.hits) > 20000:
                for stale in [k for k, v in self.hits.items() if not v]:
                    del self.hits[stale]
            return True


RATE_LIMITER = RateLimiter()
RATE_RULES = {
    "auth": (20, 300),     # log in / sign up / GitHub: 20 per 5 minutes per IP
    "write": (90, 60),     # any write: 90 per minute per IP
}


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

STATIC_CACHE: dict[Path, tuple] = {}
COMPRESSIBLE = {".html", ".js", ".css", ".svg", ".json", ".webmanifest"}


class Handler(BaseHTTPRequestHandler):
    server_version = "shiphub/1.1"
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def log_request(self, code="-", size="-"):
        if self.path.startswith(("/api/", "/auth/")) and str(code) not in ("200", "302"):
            sys.stderr.write(f"  {self.command} {self.path.split('?')[0]} -> {code}\n")

    # ----- request info ----- #

    def client_ip(self) -> str:
        if SETTINGS.trust_proxy:
            for header in ("Fly-Client-IP", "CF-Connecting-IP", "X-Real-IP"):
                value = self.headers.get(header)
                if value:
                    return value.strip()
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def is_https(self) -> bool:
        if SETTINGS.public_url.startswith("https://"):
            return True
        proto = self.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
        return proto == "https"

    def base_url(self) -> str:
        if SETTINGS.public_url:
            return SETTINGS.public_url
        scheme = "https" if self.is_https() else "http"
        return f"{scheme}://{self.headers.get('Host', 'localhost')}"

    def cookie(self, name: str) -> str | None:
        for part in self.headers.get("Cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name and value:
                return value
        return None

    def session_token(self) -> str | None:
        return self.cookie(SESSION_COOKIE)

    def current_user(self, db, token):
        if not token:
            return None
        return db.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, time.time()),
        ).fetchone()

    def rate_ok(self, bucket: str) -> bool:
        if not SETTINGS.rate_limits:
            return True
        limit, window = RATE_RULES[bucket]
        return RATE_LIMITER.allow((bucket, self.client_ip()), limit, window)

    def check_rate(self, bucket: str) -> None:
        if not self.rate_ok(bucket):
            raise ApiError(429, "Slow down a little. Too many requests, try again in a minute.")

    # ----- routing ----- #

    def dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            self.handle_api(method, parsed)
            return
        if method != "GET":
            self.drain_body()
            self.send_json(405, {"error": "Method not allowed"})
            return
        if path == "/healthz":
            self.health_check()
        elif path == "/auth/github":
            self.github_start(parsed)
        elif path == "/auth/github/callback":
            self.github_callback(parsed)
        elif path.startswith("/uploads/"):
            self.serve_upload(path)
        else:
            self.serve_static(path)

    # ----- API ----- #

    def drain_body(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if 0 < length <= SETTINGS.max_upload_bytes:
            self.rfile.read(length)
        elif length:
            self.close_connection = True

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, "Request is too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Invalid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object")
        return data

    def read_raw(self) -> bytes:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self.close_connection = True
            raise ApiError(411, "Missing Content-Length")
        length = int(length_header or 0)
        if length > SETTINGS.max_upload_bytes:
            self.close_connection = True
            limit_mb = SETTINGS.max_upload_bytes / (1024 * 1024)
            raise ApiError(413, f"Images can be at most {limit_mb:g} MB")
        return self.rfile.read(length) if length else b""

    def check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ApiError(403, "Cross-origin request blocked")

    def check_same_origin(self) -> None:
        # Cross-site forms cannot send application/json without a CORS preflight,
        # and we never answer preflights, so this blocks CSRF.
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            raise ApiError(415, "Expected application/json")
        self.check_origin()

    def check_upload_request(self) -> None:
        # A custom header also forces a CORS preflight for cross-site callers.
        if self.headers.get("X-Shiphub-Upload") != "1":
            raise ApiError(400, "Missing upload header")
        self.check_origin()

    def handle_api(self, method: str, parsed) -> None:
        for route_method, pattern, func, auth_required, raw in ROUTES:
            if route_method != method:
                continue
            match = pattern.match(parsed.path)
            if match:
                break
        else:
            self.drain_body()
            self.send_json(404, {"error": "Not found"})
            return

        db = None
        try:
            body: dict = {}
            raw_body = None
            if method != "GET":
                if raw:
                    raw_body = self.read_raw()
                    self.check_upload_request()
                else:
                    body = self.read_json()
                    self.check_same_origin()
                self.check_rate("write")
                if parsed.path in ("/api/auth/login", "/api/auth/signup"):
                    self.check_rate("auth")
            db = connect()
            token = self.session_token()
            params = match.groupdict()
            params["_session_token"] = token
            ctx = Ctx(
                db,
                self.current_user(db, token),
                parse_qs(parsed.query),
                params,
                body,
                raw=raw_body,
                secure=self.is_https(),
            )
            if auth_required:
                ctx.require_user()
            result = func(ctx)
            db.commit()
            self.send_json(200, result, ctx.set_cookies)
        except ApiError as error:
            if db is not None:
                db.rollback()
            self.send_json(error.status, {"error": error.message})
        except Exception:  # noqa: BLE001 - last-resort guard so the server stays up
            if db is not None:
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on the server"})
        finally:
            if db is not None:
                db.close()

    def send_json(self, status: int, data, cookies=()) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location: str, cookies=()) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def health_check(self) -> None:
        db = None
        try:
            db = connect()
            db.execute("SELECT 1").fetchone()
            self.send_json(200, {"ok": True, "database": "postgres" if SETTINGS.postgres else "sqlite"})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.send_json(503, {"ok": False})
        finally:
            if db is not None:
                db.close()

    # ----- GitHub OAuth ----- #

    def github_start(self, parsed) -> None:
        query = parse_qs(parsed.query)
        next_hash = safe_next(query.get("next", ["#/"])[0])
        if not SETTINGS.github_enabled:
            self.redirect("/?" + urlencode({"auth_error": "GitHub sign-in isn't set up on this server"}) + next_hash)
            return
        if not self.rate_ok("auth"):
            self.redirect("/?" + urlencode({"auth_error": "Too many sign-in attempts. Try again in a few minutes."}) + next_hash)
            return
        state = secrets.token_urlsafe(24)
        encoded_next = base64.urlsafe_b64encode(next_hash.encode("utf-8")).decode("ascii").rstrip("=")
        params = {
            "client_id": SETTINGS.github_client_id,
            "redirect_uri": f"{self.base_url()}/auth/github/callback",
            "scope": "read:user",
            "state": state,
            "allow_signup": "true",
        }
        self.redirect(
            f"{SETTINGS.github_oauth_url}/login/oauth/authorize?{urlencode(params)}",
            [oauth_cookie(f"{state}.{encoded_next}", 600, self.is_https())],
        )

    def github_callback(self, parsed) -> None:
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        secure = self.is_https()
        clear_cookie = oauth_cookie("", 0, secure)
        stored_state, _, encoded_next = (self.cookie(OAUTH_COOKIE) or "").partition(".")
        try:
            padded = encoded_next + "=" * (-len(encoded_next) % 4)
            next_hash = safe_next(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            next_hash = "#/"

        def fail(message: str) -> None:
            self.redirect("/?" + urlencode({"auth_error": message}) + next_hash, [clear_cookie])

        if query.get("error"):
            fail("GitHub sign-in was cancelled")
            return
        code = query.get("code", "")
        state = query.get("state", "")
        if not SETTINGS.github_enabled:
            fail("GitHub sign-in isn't set up on this server")
            return
        if not code or not state or not stored_state or not hmac.compare_digest(state, stored_state):
            fail("That GitHub sign-in link expired. Please try again.")
            return
        try:
            access_token = github_exchange_code(code, f"{self.base_url()}/auth/github/callback")
            profile = github_fetch_user(access_token)
        except OAuthError as error:
            fail(str(error))
            return
        except (urllib.error.URLError, OSError, ValueError):
            fail("Couldn't reach GitHub. Please try again.")
            return

        db = connect()
        try:
            current = self.current_user(db, self.session_token())
            user_id, outcome = github_sign_in(db, profile, current)
            session = None if outcome == "linked" else create_session(db, user_id)
            db.commit()
        except OAuthError as error:
            db.rollback()
            fail(str(error))
            return
        except Exception:  # noqa: BLE001
            db.rollback()
            traceback.print_exc()
            fail("Something went wrong signing in with GitHub")
            return
        finally:
            db.close()

        cookies = [clear_cookie]
        if session:
            cookies.append(session_cookie(session, SESSION_SECONDS, secure))
        self.redirect("/?" + urlencode({"auth": outcome}) + next_hash, cookies)

    # ----- Uploaded images ----- #

    def serve_upload(self, path: str) -> None:
        match = UPLOAD_PATH_RE.match(path)
        if not match:
            self.send_error(404)
            return
        db = connect()
        try:
            row = db.execute("SELECT mime, data FROM uploads WHERE token = ?", (match.group(1),)).fetchone()
        finally:
            db.close()
        if not row or IMAGE_TYPES.get(row["mime"]) != match.group(2):
            self.send_error(404)
            return
        etag = f'"{match.group(1)}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            return
        data = bytes(row["data"])
        self.send_response(200)
        self.send_header("Content-Type", row["mime"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("ETag", etag)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        self.wfile.write(data)

    # ----- Static files ----- #

    def serve_static(self, path: str) -> None:
        if path.startswith("/static/"):
            target = (STATIC_DIR / path[len("/static/"):]).resolve()
            if STATIC_DIR not in target.parents or not target.is_file():
                self.send_error(404)
                return
        else:
            target = STATIC_DIR / "index.html"

        mtime = target.stat().st_mtime_ns
        entry = STATIC_CACHE.get(target)
        if entry is None or entry[0] != mtime:
            data = target.read_bytes()
            compressed = None
            if target.suffix in COMPRESSIBLE and len(data) > 1024:
                compressed = gzip.compress(data, compresslevel=6)
            etag = '"' + hashlib.sha1(data).hexdigest()[:20] + '"'
            entry = (mtime, data, compressed, etag)
            STATIC_CACHE[target] = entry
        _, data, compressed, etag = entry

        is_html = target.suffix == ".html"
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        use_gzip = compressed is not None and "gzip" in self.headers.get("Accept-Encoding", "")
        body = compressed if use_gzip else data
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Content-Type-Options", "nosniff")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        if is_html:
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.end_headers()
        self.wfile.write(body)


# --------------------------------------------------------------------------- #
# Demo data
# --------------------------------------------------------------------------- #

SEED_USERS = [
    ("maya", "Maya Chen", "Frontend dev. I ship tiny tools on weekends.", 12),
    ("devon", "Devon Brooks", "Indie hacker, 3 failed startups and counting.", 200),
    ("kai", "Kai Nakamura", "ML engineer who loves silly side projects.", 160),
    ("ari", "Ari Levi", "Design engineer. Pixels, motion, and CSS crimes.", 280),
    ("sol", "Sol Ortega", "Full-stack. Local-first everything.", 30),
    ("nina", "Nina Petrova", "Product person learning to code with AI.", 320),
    ("theo", "Theo Martin", "Mobile dev (Swift + Kotlin).", 95),
    ("priya", "Priya Raman", "Data viz + generative art.", 340),
    ("leo", "Leo Fischer", "DevOps by day, game jams by night.", 50),
    ("zara", "Zara Ahmed", "Student. Building my portfolio one idea at a time.", 180),
    ("omar", "Omar Haddad", "Backend nerd. Postgres is my love language.", 240),
    ("demo", "Demo Maker", "The demo account. Click around, nothing here is precious.", 0),
]

# (author, title, pitch, tags, stack, scope, cover, popularity, hours_ago, features, twist)
SEED_IDEAS = [
    ("maya", "Fridge Roulette", "Snap your fridge, get three recipes that use what's about to expire.",
     ["ai", "food", "mobile"], "Expo · Vision API · Supabase", 0, 4, 9, 5,
     ["Photo → ingredient detection", "Expiry-aware recipe ranking", "\"Zero shopping\" mode"],
     "Weekly stats on how much food you rescued."),
    ("sol", "Commit Garden", "Your GitHub contributions grow a pixel-art garden. Skip days and it wilts.",
     ["github", "game", "devtools"], "Next.js · GitHub GraphQL · Canvas", 0, 2, 11, 30,
     ["OAuth with GitHub", "Daily garden render from contributions", "Shareable PNG for your README"],
     "Rare plants unlock for streaks and first PRs to new repos."),
    ("ari", "Ambient Co-working Rooms", "Silent, camera-off rooms with a shared lo-fi track and a synced pomodoro.",
     ["productivity", "realtime", "social"], "SvelteKit · WebRTC · Redis", 1, 1, 6, 48,
     ["Join a room with one click", "Synced 25/5 timer for everyone", "Shared playlist, no chat by default"],
     "Your \"focus streak\" shows as a little flame next to your avatar."),
    ("devon", "Receipt Splitter", "Photograph a restaurant receipt, tap who had what, send everyone a pay link.",
     ["ai", "finance", "mobile"], "React Native · OCR · Stripe links", 1, 6, 8, 12,
     ["OCR line items", "Drag items onto people", "Tax and tip split proportionally"],
     "Works without anyone else installing the app."),
    ("priya", "Dead Link Museum", "Paste a URL and scroll through every Wayback snapshot as a timeline.",
     ["web", "nostalgia", "tools"], "Vanilla JS · archive.org API", 0, 9, 5, 70,
     ["Timeline scrubber of snapshots", "Side-by-side diff of two years", "Export a GIF of a site's evolution"],
     "Curated \"exhibits\" of famous sites' first versions."),
    ("theo", "Plant Doctor", "Photograph a sad leaf, get a diagnosis and a care schedule with reminders.",
     ["ai", "home", "mobile"], "Flutter · vision model", 1, 8, 5, 90,
     ["Leaf photo diagnosis", "Watering reminders per plant", "Light meter using the camera"],
     "Plant \"health\" graph over months."),
    ("nina", "One-Line Journal", "One sentence a day. On each date, see what you wrote 1, 2 and 5 years ago.",
     ["wellness", "minimal", "pwa"], "PWA · IndexedDB", 0, 3, 10, 120,
     ["One text box, one sentence", "\"On this day\" memories", "Offline-first and private"],
     "Optional end-to-end encrypted sync as the paid tier."),
    ("kai", "Landing Page Roaster", "Drop a URL, get a brutal roast plus concrete fixes for copy, contrast and CTA.",
     ["ai", "devtools", "marketing"], "Next.js · Playwright · LLM", 0, 7, 12, 8,
     ["Full-page screenshot + DOM audit", "Roast in 5 bullet points", "Rewritten hero copy suggestions"],
     "A \"before/after\" share card people will post."),
    ("omar", "Neighborhood Tool Library", "Lend your drill, borrow a ladder. A map of what your neighbors own.",
     ["social", "local", "sustainability"], "Supabase · Mapbox", 2, 8, 4, 200,
     ["List tools with photos", "Request + approve borrowing", "Trust score from returns"],
     "Building-level groups for apartments."),
    ("theo", "Gym Ghost", "Race your past self: a live overlay of last session's sets and weights.",
     ["fitness", "mobile"], "SwiftUI · HealthKit", 1, 5, 6, 36,
     ["Log sets fast with big buttons", "Ghost shows last session's numbers", "Progress graphs per lift"],
     "Apple Watch haptic when you beat your ghost."),
    ("leo", "Meeting Cost Ticker", "A browser extension that shows money burned live during any calendar meeting.",
     ["productivity", "extension", "fun"], "Chrome MV3 · Calendar API", 0, 7, 9, 60,
     ["Reads attendee count from the calendar", "Average salary presets by role", "Live ticker overlay"],
     "Monthly \"meeting tax\" report for your team."),
    ("priya", "City Soundscapes", "Generative ambient music made from live weather and transit data of any city.",
     ["music", "generative", "web"], "Tone.js · open data APIs", 1, 1, 5, 15,
     ["Pick a city on a globe", "Rain = pads, trains = percussion", "Record a 60s clip"],
     "Pair two cities and hear them duet."),
    ("kai", "Codebase Atlas", "Point it at a repo and get an interactive map of modules with plain-English summaries.",
     ["ai", "devtools"], "Python · tree-sitter · LLM · D3", 2, 5, 11, 26,
     ["Parse repo into a module graph", "Summaries per file and folder", "\"Where is X handled?\" search"],
     "Onboarding tours generated from the graph."),
    ("zara", "Chore Quests", "Chores become RPG quests. Parents approve, kids earn XP and real rewards.",
     ["family", "game"], "React · Firebase", 1, 3, 4, 140,
     ["Quest board per kid", "Photo proof + parent approval", "XP, levels, and a reward shop"],
     "Boss battles for the big weekend clean."),
    ("devon", "Subscription Graveyard", "Scan your inbox for every subscription and get one-tap cancel links.",
     ["finance", "ai", "email"], "Gmail API · LLM parsing", 1, 9, 8, 44,
     ["Detect recurring charges from receipts", "Monthly total and trend", "Cancel link finder"],
     "A tombstone for every subscription you kill."),
    ("nina", "Lockscreen Lessons", "A wallpaper that changes daily and teaches you one tiny thing.",
     ["learning", "mobile", "minimal"], "Shortcuts · image generation", 0, 6, 3, 18,
     ["Pick topics: words, history, math", "Auto-set wallpaper daily", "Tap to learn more"],
     "Spaced repetition: missed facts come back."),
    ("leo", "API Mood Ring", "A status widget that turns your API latency into a mood-ring color.",
     ["devtools", "fun", "web"], "Cloudflare Workers · SVG", 0, 0, 4, 80,
     ["Ping endpoints every minute", "Color gradient by p95 latency", "Embeddable SVG badge"],
     "Slack bot that changes its avatar color."),
    ("maya", "PR Haiku", "A GitHub Action that summarizes every pull request as a haiku.",
     ["github", "ai", "fun"], "GitHub Actions · LLM", 0, 3, 7, 22,
     ["Reads the diff and title", "Posts a haiku comment", "Config for tone and language"],
     "Monthly \"poetry anthology\" of your repo."),
    ("ari", "Dotfiles Gallery", "Pinterest for terminal setups: screenshots plus one-click dotfile installs.",
     ["devtools", "community", "cli"], "Astro · GitHub OAuth", 1, 9, 9, 33,
     ["Post a screenshot + dotfiles repo", "Tag by shell, terminal, theme", "Install script generator"],
     "\"Steal this look\" diff against your current config."),
    ("sol", "Tab Garden", "Every tab you close grows a tree. Hoard 40 tabs and the forest wilts.",
     ["extension", "productivity", "game"], "Chrome MV3 · Canvas", 0, 2, 6, 10,
     ["Counts open tabs", "Forest grows as you close tabs", "Weekly forest snapshot"],
     "Friends' forests side by side."),
    ("sol", "Local-First Kanban", "A kanban board that works offline and syncs peer-to-peer. No server, no account.",
     ["productivity", "local-first", "realtime"], "Yjs · WebRTC · React", 2, 5, 7, 160,
     ["CRDT-backed boards", "Share via QR code link", "Works fully offline"],
     "Optional relay for when peers aren't online together."),
    ("zara", "Voice Memo to Tasks", "Ramble into your phone and get a clean task list with due dates.",
     ["ai", "productivity", "mobile"], "Expo · Whisper · LLM", 0, 4, 8, 3,
     ["Record or share a voice memo", "Extract tasks + dates", "Export to your todo app"],
     "Detects \"waiting on someone\" tasks and nudges later."),
    ("omar", "Cron Explainer", "Paste a cron expression, get plain English plus the next 10 run times.",
     ["devtools", "tools", "web"], "Vanilla JS", 0, 0, 6, 100,
     ["Parse standard + Quartz cron", "Next 10 runs in your timezone", "Build cron from English"],
     "VS Code extension that explains cron on hover."),
    ("devon", "Side-Project Graveyard", "Post your abandoned projects so someone else can adopt and revive them.",
     ["community", "devtools", "social"], "Next.js · Postgres", 1, 9, 10, 2,
     ["List a project with repo + why it died", "\"Adopt\" button transfers context", "Revival stories feed"],
     "Original author gets a credit badge when it ships."),
    ("demo", "vibeHQ: social HQ for vibe coders",
     "Monitor and command your AI coding agents from your phone, ship in public, climb a verified ladder, chat and sell.",
     ["ai", "social", "devtools"], "Python stdlib · SQLite · SSE · Stripe Connect · Web Push", 2, 3, 10, 1,
     ["Device bridge: see running agents (Claude Code, Codex, Cursor, Ollama...) and send them tasks",
      "Feed of ships, tips and news with GitHub-verified ships",
      "XP ladder (global / country / friends), friends + realtime chat",
      "Marketplace with Stripe Connect payouts, installable phone app with push"],
     "Remote commands need a separate PIN and can require on-device approval, so a stolen login can't run code."),
]

# idea index -> list of (author, text, hours_ago, replies)
SEED_COMMENTS = {
    0: [
        ("kai", "Add a **zero shopping** toggle: only recipes you can make with exactly what's there.", 4, [
            ("maya", "Yes! And a pantry-staples checklist (salt, oil, flour) so it doesn't assume too much.", 3, []),
        ]),
        ("sol", "Barcode scan for expiry dates would make this way stickier than photos alone.", 2, []),
    ],
    1: [
        ("ari", "A shareable garden PNG for your README would be free marketing.", 20, [
            ("sol", "Already on the list. Thinking an SVG endpoint like `/garden/username.svg`.", 18, []),
            ("leo", "Make the plants seasonal so the README changes over the year.", 15, []),
        ]),
        ("zara", "Would love this for my portfolio. Is anyone building it?", 10, []),
    ],
    3: [
        ("nina", "Tip and tax auto-split proportionally please. That's the part everyone fights about.", 10, []),
    ],
    6: [
        ("nina", "Offline-first is a must, journals feel private.", 100, [
            ("kai", "E2E encrypted sync as the paid tier?", 90, [
                ("nina", "Exactly what I was thinking. Free = local only.", 88, []),
            ]),
        ]),
    ],
    7: [
        ("devon", "I'd pay for this. Bonus: a Lighthouse score next to the roast.", 6, []),
        ("priya", "Let me choose the roast intensity: gentle, honest, savage.", 5, [
            ("kai", "Shipped the intensity slider in v0.2 :)", 2, []),
        ]),
    ],
    10: [
        ("omar", "Add a \"this could have been an email\" button that drafts the email.", 50, []),
    ],
    12: [
        ("theo", "Would be amazing for onboarding juniors. Could it generate a reading order?", 20, []),
    ],
    18: [
        ("leo", "Needs a filter by font. I pick setups 90% on font.", 30, []),
    ],
    23: [
        ("zara", "I have three of these. Would totally post them.", 1, []),
    ],
}

# idea index -> list of (builder, status, note[, repo_url, demo_url])
SEED_BUILDS = {
    1: [("devon", "shipped", "Live with SVG README badge."), ("sol", "building", "Working on seasons + rare plants.")],
    7: [("kai", "shipped", "v0.2 has roast intensity levels.")],
    10: [("nina", "building", "My first Chrome extension, learning MV3 as I go.")],
    17: [("maya", "shipped", "Runs on my team's repos. Haikus are surprisingly good.")],
    22: [("ari", "shipped", "Single HTML file, no deps."), ("demo", "building", "")],
    12: [("omar", "building", "Python + tree-sitter backend done, UI next.")],
    24: [("demo", "building", "Feed, ladder, agents, chat, market, Stripe, GitHub verify, push and security hardening done. Next: deploy + first testers.",
          "https://github.com/juw12/shiphub/tree/main/vibehq", "")],
}

SEED_FORKS = {19: 1}  # Tab Garden is a fork of Commit Garden

SEED_BOARDS = [
    ("demo", "Weekend builds", "Small enough to ship in two days.", [0, 6, 10, 22, 16]),
    ("demo", "AI experiments", "", [7, 12, 21, 14]),
    ("maya", "Dev tools I want", "", [12, 16, 22, 18]),
    ("ari", "Pretty things", "", [11, 4, 1]),
]


def seed(db) -> None:
    rng = random.Random(7)
    now = time.time()
    if SETTINGS.demo:
        digest, salt = hash_password("shiphub123")
        demo_digest, demo_salt = hash_password("demo1234")
    else:
        digest, salt = hash_password(secrets.token_urlsafe(24))
        demo_digest, demo_salt = hash_password(secrets.token_urlsafe(24))
    user_ids: dict[str, int] = {}
    for index, (username, display_name, bio, hue) in enumerate(SEED_USERS):
        is_demo = username == "demo"
        user_ids[username] = db.insert(
            "INSERT INTO users (username, display_name, bio, avatar_hue, password_hash, password_salt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                username, display_name, bio, hue,
                demo_digest if is_demo else digest,
                demo_salt if is_demo else salt,
                now - (400 - index * 20) * 86400,
            ),
        )

    idea_ids: list[int] = []
    voters = [uid for name, uid in user_ids.items() if name != "demo"]
    for index, entry in enumerate(SEED_IDEAS):
        (author, title, pitch, tags, stack, scope, cover, popularity, hours, features, twist) = entry
        created = now - hours * 3600
        body = "### Core features\n" + "\n".join(f"- {item}" for item in features) + f"\n\n### The twist\n{twist}"
        idea_id = db.insert(
            "INSERT INTO ideas (user_id, title, pitch, body, stack, scope, cover_style, forked_from, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (user_ids[author], title, pitch, body, stack, scope, cover, created, created),
        )
        idea_ids.append(idea_id)
        db.executemany(
            "INSERT INTO idea_tags (idea_id, tag, pos) VALUES (?, ?, ?)",
            [(idea_id, tag, pos) for pos, tag in enumerate(tags)],
        )
        chosen = {user_ids[author]} | set(rng.sample(voters, min(len(voters), popularity)))
        db.executemany(
            "INSERT INTO idea_votes (idea_id, user_id, created_at) VALUES (?, ?, ?)",
            [(idea_id, uid, created + 60) for uid in chosen],
        )

    for fork_index, parent_index in SEED_FORKS.items():
        db.execute("UPDATE ideas SET forked_from = ? WHERE id = ?", (idea_ids[parent_index], idea_ids[fork_index]))

    def add_comments(idea_id, entries, parent_id=None):
        for author, text, hours, replies in entries:
            comment_id = db.insert(
                "INSERT INTO comments (idea_id, user_id, parent_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (idea_id, user_ids[author], parent_id, text, now - hours * 3600),
            )
            fans = {user_ids[author]} | set(rng.sample(voters, rng.randint(0, 6)))
            db.executemany(
                "INSERT INTO comment_votes (comment_id, user_id) VALUES (?, ?)",
                [(comment_id, uid) for uid in fans],
            )
            add_comments(idea_id, replies, comment_id)

    for index, entries in SEED_COMMENTS.items():
        add_comments(idea_ids[index], entries)

    for index, builds in SEED_BUILDS.items():
        for entry in builds:
            builder, status, note = entry[:3]
            repo_url = entry[3] if len(entry) > 3 else ""
            demo_url = entry[4] if len(entry) > 4 else ""
            stamp = now - rng.randint(1, 48) * 3600
            db.execute(
                "INSERT INTO builds (idea_id, user_id, status, repo_url, demo_url, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (idea_ids[index], user_ids[builder], status, repo_url, demo_url, note, stamp, stamp),
            )

    for owner, name, description, items in SEED_BOARDS:
        board_id = db.insert(
            "INSERT INTO boards (user_id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (user_ids[owner], name, description, now - 86400 * 3),
        )
        for offset, index in enumerate(items):
            db.execute(
                "INSERT INTO board_items (board_id, idea_id, created_at) VALUES (?, ?, ?)",
                (board_id, idea_ids[index], now - 3600 * (offset + 1)),
            )

    demo_id = user_ids["demo"]
    demo_idea = db.insert(
        "INSERT INTO ideas (user_id, title, pitch, body, stack, scope, cover_style, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            demo_id, "Bug Bounty for Typos", "Readers report typos on your blog and earn tiny tips for each one.",
            "### Core features\n- Highlight text → report typo\n- Author approves fixes\n- Micro-tips via Stripe",
            "Astro · Cloudflare · Stripe", 1, 8, now - 7 * 3600, now - 7 * 3600,
        ),
    )
    db.executemany(
        "INSERT INTO idea_tags (idea_id, tag, pos) VALUES (?, ?, ?)",
        [(demo_idea, "web", 0), (demo_idea, "community", 1)],
    )
    db.executemany(
        "INSERT INTO idea_votes (idea_id, user_id, created_at) VALUES (?, ?, ?)",
        [(demo_idea, uid, now) for uid in [demo_id, user_ids["maya"], user_ids["kai"], user_ids["omar"]]],
    )
    welcome_comment = db.insert(
        "INSERT INTO comments (idea_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
        (demo_idea, user_ids["maya"], "Love this. Could also work for docs sites, not just blogs.", now - 5 * 3600),
    )
    notify(db, demo_id, user_ids["maya"], "comment", demo_idea, welcome_comment)
    notify(db, demo_id, user_ids["omar"], "build", idea_ids[22])


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

class ShiphubServer(ThreadingHTTPServer):
    """Refuse to share a port with another process.

    The stdlib HTTPServer enables SO_REUSEADDR, which on Windows lets two
    servers bind the same port and silently steal each other's requests.
    """

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        # Browsers and proxies drop idle keep-alive connections all the time; that's not an error.
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def describe_database() -> str:
    if SETTINGS.postgres:
        parsed = urlparse(SETTINGS.database_url)
        return f"Postgres at {parsed.hostname}{parsed.path}"
    return f"SQLite at {SETTINGS.db_path}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the shiphub server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="Use 0.0.0.0 to share on your network")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8000))
    parser.add_argument("--db", type=Path, default=None, help="SQLite database file (ignored with DATABASE_URL)")
    parser.add_argument("--reset", action="store_true", help="Delete all data and re-seed demo data")
    parser.add_argument("--no-browser", action="store_true", help="Don't open a browser tab")
    args = parser.parse_args()

    if args.db is not None:
        SETTINGS.db_path = args.db.resolve()
    try:
        init_db(reset=args.reset)
    except ImportError:
        sys.exit('DATABASE_URL points at Postgres, so install the driver first:  pip install "psycopg[binary]"')

    # On a host that assigns PORT (Fly, Render, Docker) we must bind exactly that port.
    strict_port = bool(os.environ.get("PORT"))
    candidates = [args.port] if strict_port else range(args.port, args.port + 10)
    server = None
    for port in candidates:
        try:
            server = ShiphubServer((args.host, port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f"Could not bind to port {args.port}")

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "", "::") else args.host
    url = SETTINGS.public_url or f"http://{shown_host}:{server.server_port}"
    if server.server_port != args.port:
        print(f"\n  Port {args.port} is busy, using {server.server_port} instead.", flush=True)
    print(f"\n  shiphub is running at {url}/", flush=True)
    print(f"  database: {describe_database()}", flush=True)
    print(f"  GitHub sign-in: {'on' if SETTINGS.github_enabled else 'off (set GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET)'}", flush=True)
    if SETTINGS.demo:
        print("  demo login: demo / demo1234", flush=True)
    print("  Ctrl+C to stop\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, [f"http://{shown_host}:{server.server_port}/"]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
