#!/usr/bin/env python3
"""
VibeHQ server - the social HQ for vibe coders.

Social feed (ships, tips, news), friends, realtime chat, XP ladder,
marketplace, and remote monitoring/commanding of your own devices & AI agents.
Optional integrations (configure in .env): Stripe Connect payments, GitHub
login + verified ships, Web Push / ntfy notifications for the mobile app.

Zero dependencies: Python 3.9+ standard library only.
Run:  python server.py --demo   (then open http://localhost:8787)
"""
import argparse
import datetime
import hashlib
import hmac
import json
import math
import mimetypes
import os
import queue
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import webpush  # noqa: E402
from github_client import GitHub, GitHubError, parse_repo_url  # noqa: E402
from stripe_client import Stripe, StripeError, verify_webhook  # noqa: E402


def load_env_file(path):
    """Tiny .env loader: KEY=VALUE lines; real environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(os.path.join(ROOT, ".env"))

STATIC_DIR = os.path.join(ROOT, "static")
DB_PATH = os.environ.get("VIBEHQ_DB", os.path.join(ROOT, "vibehq.db"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/png", ".png")

# --- payments (Stripe Connect). Without a key the market runs in demo mode.
PLATFORM_FEE_PERCENT = float(os.environ.get("PLATFORM_FEE_PERCENT", "10"))
CURRENCY = os.environ.get("CURRENCY", "usd").lower()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE = (
    Stripe(os.environ["STRIPE_SECRET_KEY"], api_base=os.environ.get("STRIPE_API_BASE", "https://api.stripe.com"))
    if os.environ.get("STRIPE_SECRET_KEY") else None
)

# --- GitHub OAuth login + ship verification
GITHUB = (
    GitHub(
        os.environ["GITHUB_CLIENT_ID"],
        os.environ["GITHUB_CLIENT_SECRET"],
        api_base=os.environ.get("GITHUB_API_BASE", "https://api.github.com"),
        oauth_base=os.environ.get("GITHUB_OAUTH_BASE", "https://github.com"),
        app_token=os.environ.get("GITHUB_TOKEN") or None,
    )
    if os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET") else None
)
SHIP_FRESH_DAYS = 30
PUSH_EVENT_DAYS = 7

# --- notifications
NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
PUSH_EXTRA_HOSTS = {host.strip().lower() for host in os.environ.get("PUSH_EXTRA_HOSTS", "").split(",") if host.strip()}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

# --- security
SESSION_IDLE_DAYS = int(os.environ.get("SESSION_IDLE_DAYS", "30"))
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"  # only behind your own reverse proxy
MAX_STREAMS_PER_USER = 5
RISKY_COMMANDS = {"agent_task", "shell"}
FRESH_SESSION_SECONDS = 600
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",  # single-file app uses inline handlers; no third-party scripts
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "form-action 'self'",
])

MAX_BODY_BYTES = 256 * 1024
DEVICE_ONLINE_SECONDS = 30
COMMAND_KINDS = {"ping", "sysinfo", "list_agents", "agent_task", "shell"}
POST_KINDS = {"ship", "tip", "news", "post"}
PRODUCT_KINDS = {"template", "prompt", "agent", "mcp", "app", "course", "other"}

# XP economy: amount per action and a daily cap per action (anti-farming).
XP_RULES = {
    "ship": (50, 3),
    "tip": (20, 5),
    "news": (10, 5),
    "post": (5, 10),
    "like_received": (2, 50),
    "task_done": (10, 20),
    "sale": (100, 50),
    "friend": (10, 10),
    "daily_login": (5, 1),
    "ship_verified": (50, 3),
    "github_push": (3, 20),
}
TIERS = [
    (0, "Bronze"),
    (500, "Silver"),
    (1500, "Gold"),
    (4000, "Platinum"),
    (10000, "Diamond"),
    (25000, "Legend"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    pw_hash TEXT NOT NULL,
    pw_salt TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    stack TEXT NOT NULL DEFAULT '',
    xp INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS friendships (
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    created INTEGER NOT NULL,
    PRIMARY KEY (requester_id, addressee_id)
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel, id);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT UNIQUE NOT NULL,
    last_seen INTEGER NOT NULL DEFAULT 0,
    info TEXT NOT NULL DEFAULT '{}',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    delivery_link TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    price_cents INTEGER NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS xp_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_user ON xp_log(user_id, reason, created);
"""

# Columns added after v0.1 - applied with ALTER TABLE so existing databases upgrade in place.
MIGRATIONS = [
    ("users", "github_id", "INTEGER"),
    ("users", "github_login", "TEXT NOT NULL DEFAULT ''"),
    ("users", "avatar_url", "TEXT NOT NULL DEFAULT ''"),
    ("users", "stripe_account_id", "TEXT NOT NULL DEFAULT ''"),
    ("users", "payouts_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "ntfy_topic", "TEXT NOT NULL DEFAULT ''"),
    ("posts", "verified", "INTEGER NOT NULL DEFAULT 0"),
    ("posts", "repo", "TEXT NOT NULL DEFAULT ''"),
    ("orders", "status", "TEXT NOT NULL DEFAULT 'paid'"),
    ("orders", "stripe_session_id", "TEXT NOT NULL DEFAULT ''"),
    ("orders", "fee_cents", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "has_password", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "command_pin_hash", "TEXT NOT NULL DEFAULT ''"),
    ("users", "command_pin_salt", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "last_seen", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "user_agent", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "ip", "TEXT NOT NULL DEFAULT ''"),
]

SCHEMA_EXTRA = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github ON users(github_id) WHERE github_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(stripe_session_id);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    read INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT UNIQUE NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER,
    created INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------- helpers

def now():
    return int(time.time())


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = connect()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.executescript(SCHEMA_EXTRA)
    if not conn.execute("SELECT 1 FROM settings WHERE key='sessions_hashed'").fetchone():
        for row in conn.execute("SELECT token FROM sessions").fetchall():
            conn.execute("UPDATE sessions SET token=? WHERE token=?", (sha256(row["token"]), row["token"]))
        conn.execute("INSERT INTO settings(key, value) VALUES ('sessions_hashed', '1')")
    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return digest.hex(), salt


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def tier_for(xp):
    current = TIERS[0]
    following = None
    for index, (threshold, name) in enumerate(TIERS):
        if xp >= threshold:
            current = (threshold, name)
            following = TIERS[index + 1] if index + 1 < len(TIERS) else None
    return current, following


def public_user(row):
    xp = row["xp"]
    (tier_floor, tier_name), following = tier_for(xp)
    return {
        "username": row["username"],
        "country": row["country"],
        "bio": row["bio"],
        "stack": row["stack"],
        "xp": xp,
        "level": int(math.sqrt(xp / 100)) + 1,
        "tier": tier_name,
        "tier_floor": tier_floor,
        "next_tier": following[1] if following else None,
        "next_tier_xp": following[0] if following else None,
        "created": row["created"],
        "github_login": row["github_login"],
        "avatar_url": row["avatar_url"],
    }


def award_xp(conn, user_id, reason, ref=""):
    """Grant XP for an action, respecting daily caps and one-time refs."""
    amount, daily_cap = XP_RULES[reason]
    if ref:
        duplicate = conn.execute(
            "SELECT 1 FROM xp_log WHERE user_id=? AND reason=? AND ref=?",
            (user_id, reason, ref),
        ).fetchone()
        if duplicate:
            return 0
    day_start = now() - 86400
    used_today = conn.execute(
        "SELECT COUNT(*) FROM xp_log WHERE user_id=? AND reason=? AND created>?",
        (user_id, reason, day_start),
    ).fetchone()[0]
    if used_today >= daily_cap:
        return 0
    conn.execute(
        "INSERT INTO xp_log(user_id, amount, reason, ref, created) VALUES (?,?,?,?,?)",
        (user_id, amount, reason, ref, now()),
    )
    conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (amount, user_id))
    return amount


def friend_ids(conn, user_id):
    rows = conn.execute(
        """SELECT CASE WHEN requester_id=? THEN addressee_id ELSE requester_id END AS fid
           FROM friendships
           WHERE status='accepted' AND (requester_id=? OR addressee_id=?)""",
        (user_id, user_id, user_id),
    ).fetchall()
    return [row["fid"] for row in rows]


def are_friends(conn, a, b):
    return conn.execute(
        """SELECT 1 FROM friendships WHERE status='accepted' AND
           ((requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?))""",
        (a, b, b, a),
    ).fetchone() is not None


def text_field(body, name, max_len, required=True):
    value = str(body.get(name, "") or "").strip()
    if required and not value:
        raise ApiError(400, f"'{name}' is required")
    if len(value) > max_len:
        raise ApiError(400, f"'{name}' is too long (max {max_len})")
    return value


def safe_link(value):
    if value and not re.match(r"^https?://", value, re.I):
        raise ApiError(400, "links must start with http:// or https://")
    return value


# ---------------------------------------------------------------- notifications & push

PUSH_QUEUE = queue.Queue()
_REQUEST_STATE = threading.local()
_VAPID_LOCK = threading.Lock()
_VAPID_KEY = None


def notify(conn, user_id, text, link=""):
    """Store a notification, show it live, and queue phone push after the DB commits."""
    cursor = conn.execute(
        "INSERT INTO notifications(user_id, text, link, created) VALUES (?,?,?,?)",
        (user_id, text, link, now()),
    )
    HUB.publish(user_id, {"type": "notify", "id": cursor.lastrowid, "text": text, "link": link})
    pending = getattr(_REQUEST_STATE, "pushes", None)
    if pending is None:
        PUSH_QUEUE.put((user_id, text, link))
    else:
        pending.append((user_id, text, link))


def vapid_private_key():
    global _VAPID_KEY
    with _VAPID_LOCK:
        if _VAPID_KEY is None:
            conn = connect()
            row = conn.execute("SELECT value FROM settings WHERE key='vapid_private'").fetchone()
            if row:
                _VAPID_KEY = int(row["value"], 16)
            else:
                _VAPID_KEY = webpush.generate_private_key()
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES ('vapid_private', ?)",
                    (format(_VAPID_KEY, "x"),),
                )
                conn.commit()
            conn.close()
        return _VAPID_KEY


def opener_for(url):
    """Use the system proxy for internet services, but never for loopback/test hosts."""
    host = (urlparse(url).hostname or "").lower()
    if host in LOOPBACK_HOSTS or host in PUSH_EXTRA_HOSTS:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def send_ntfy(topic, text, link):
    request = urllib.request.Request(
        f"{NTFY_BASE}/{quote(topic)}",
        data=text.encode("utf-8"),
        method="POST",
        headers={
            "Title": "vibeHQ",
            "Tags": "rocket",
            "Click": f"{PUBLIC_URL}/#{link or 'feed'}",
        },
    )
    with opener_for(request.full_url).open(request, timeout=15) as response:
        return response.status


def deliver_push(user_id, text, link):
    conn = connect()
    try:
        user = conn.execute("SELECT ntfy_topic FROM users WHERE id=?", (user_id,)).fetchone()
        subscriptions = conn.execute(
            "SELECT id, endpoint FROM push_subscriptions WHERE user_id=?", (user_id,)
        ).fetchall()
        for subscription in subscriptions:
            try:
                status = webpush.send_push(
                    subscription["endpoint"],
                    vapid_private_key(),
                    VAPID_SUBJECT,
                    opener=opener_for(subscription["endpoint"]),
                )
            except OSError as error:
                print(f"push failed: {error}")
                continue
            if status in (404, 410):
                conn.execute("DELETE FROM push_subscriptions WHERE id=?", (subscription["id"],))
        conn.commit()
        if user and user["ntfy_topic"]:
            try:
                send_ntfy(user["ntfy_topic"], text, link)
            except OSError as error:
                print(f"ntfy failed: {error}")
    finally:
        conn.close()


def push_worker():
    while True:
        user_id, text, link = PUSH_QUEUE.get()
        try:
            deliver_push(user_id, text, link)
        except Exception as error:  # never let one bad push kill the worker
            print(f"push worker error: {error!r}")


# ---------------------------------------------------------------- abuse protection

class RateLimiter:
    """In-memory sliding-window counter. Fine for one process; use Redis when scaling out."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = {}

    def _recent(self, key, window):
        cutoff = time.time() - window
        recent = [stamp for stamp in self.events.get(key, []) if stamp > cutoff]
        self.events[key] = recent
        return recent

    def blocked(self, key, limit, window):
        with self.lock:
            return len(self._recent(key, window)) >= limit

    def hit(self, key, window):
        with self.lock:
            self._recent(key, window).append(time.time())

    def reset(self, key):
        with self.lock:
            self.events.pop(key, None)


LIMITER = RateLimiter()
LOGIN_LIMIT = (5, 900)          # failures per username per 15 min
LOGIN_IP_LIMIT = (20, 900)      # failures per IP per 15 min
REGISTER_LIMIT = (5, 3600)      # sign-ups per IP per hour
PIN_LIMIT = (5, 900)            # wrong command PINs per user per 15 min

STREAM_TICKETS = {}
STREAM_TICKETS_LOCK = threading.Lock()


def issue_stream_ticket(user_id):
    ticket = secrets.token_urlsafe(24)
    with STREAM_TICKETS_LOCK:
        for key, (_, expires) in list(STREAM_TICKETS.items()):
            if expires < time.time():
                del STREAM_TICKETS[key]
        STREAM_TICKETS[ticket] = (user_id, time.time() + 60)
    return ticket


def redeem_stream_ticket(ticket):
    with STREAM_TICKETS_LOCK:
        entry = STREAM_TICKETS.pop(ticket, None)
    if not entry or entry[1] < time.time():
        return None
    return entry[0]


# ---------------------------------------------------------------- realtime hub

class Hub:
    """Fan-out of server-sent events to connected browser sessions."""

    def __init__(self):
        self.lock = threading.Lock()
        self.subscribers = {}

    def subscribe(self, user_id):
        events = queue.Queue(maxsize=500)
        with self.lock:
            self.subscribers.setdefault(user_id, set()).add(events)
        return events

    def unsubscribe(self, user_id, events):
        with self.lock:
            self.subscribers.get(user_id, set()).discard(events)

    def stream_count(self, user_id):
        with self.lock:
            return len(self.subscribers.get(user_id, ()))

    def online_user_ids(self):
        with self.lock:
            return {uid for uid, queues in self.subscribers.items() if queues}

    def publish(self, user_id, event):
        with self.lock:
            targets = list(self.subscribers.get(user_id, ()))
        for events in targets:
            try:
                events.put_nowait(event)
            except queue.Full:
                pass

    def broadcast(self, event):
        for user_id in self.online_user_ids():
            self.publish(user_id, event)


HUB = Hub()
CHAT_RATE = {}
CHAT_RATE_LOCK = threading.Lock()


# ---------------------------------------------------------------- routing

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


ROUTES = []


def route(method, pattern):
    def register(handler):
        ROUTES.append((method, re.compile("^" + pattern + "$"), handler))
        return handler
    return register


class Ctx:
    def __init__(self, handler, conn, query, body, raw_body=b""):
        self.raw_body = raw_body
        self.handler = handler
        self.conn = conn
        self.query = query
        self.body = body
        self._user = None

    def arg(self, name, default=""):
        return self.query.get(name, [default])[0]

    def client_ip(self):
        forwarded = self.handler.headers.get("X-Forwarded-For", "")
        if TRUST_PROXY and forwarded:
            # the last hop is the one added by OUR proxy; earlier entries can be forged by clients
            return forwarded.split(",")[-1].strip()
        return self.handler.client_address[0]

    def user(self):
        if self._user is not None:
            return self._user
        header = self.handler.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token:
            raise ApiError(401, "login required")
        session = self.conn.execute(
            "SELECT * FROM sessions WHERE token=?", (sha256(token),)
        ).fetchone()
        if not session:
            raise ApiError(401, "session expired")
        last_active = session["last_seen"] or session["created"]
        if now() - last_active > SESSION_IDLE_DAYS * 86400:
            self.conn.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
            raise ApiError(401, "session expired")
        if now() - last_active > 300:
            self.conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (now(), session["token"]))
        self.session = session
        self._user = self.conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        return self._user

    def session_is_fresh(self):
        self.user()
        return now() - self.session["created"] < FRESH_SESSION_SECONDS

    def device(self):
        key = self.handler.headers.get("X-Device-Key", "")
        row = self.conn.execute(
            "SELECT * FROM devices WHERE key_hash=?", (sha256(key),)
        ).fetchone() if key else None
        if not row:
            raise ApiError(401, "unknown device key")
        return row

    def user_by_name(self, username):
        row = self.conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise ApiError(404, f"user '{username}' not found")
        return row


# ---------------------------------------------------------------- auth & profile

def create_session(conn, user_id, ctx=None):
    """Only a SHA-256 of the token is stored, so a database leak doesn't leak logins."""
    token = secrets.token_urlsafe(32)
    user_agent = ctx.handler.headers.get("User-Agent", "")[:200] if ctx else ""
    ip = ctx.client_ip() if ctx else ""
    conn.execute(
        "INSERT INTO sessions(token, user_id, created, last_seen, user_agent, ip) VALUES (?,?,?,?,?,?)",
        (sha256(token), user_id, now(), now(), user_agent, ip),
    )
    return token


@route("POST", "/api/register")
def register(ctx):
    register_key = f"register:{ctx.client_ip()}"
    if LIMITER.blocked(register_key, *REGISTER_LIMIT):
        raise ApiError(429, "too many sign-ups from this network - try again later")
    username = text_field(ctx.body, "username", 24)
    password = str(ctx.body.get("password", ""))
    if not re.match(r"^[A-Za-z0-9_]{3,24}$", username):
        raise ApiError(400, "username: 3-24 letters, digits or _")
    if len(password) < 8:
        raise ApiError(400, "password must be at least 8 characters")
    if ctx.conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ApiError(409, "username taken")
    country = text_field(ctx.body, "country", 2, required=False).upper()
    pw_hash, salt = hash_password(password)
    cursor = ctx.conn.execute(
        "INSERT INTO users(username, pw_hash, pw_salt, country, created) VALUES (?,?,?,?,?)",
        (username, pw_hash, salt, country, now()),
    )
    LIMITER.hit(register_key, REGISTER_LIMIT[1])
    token = create_session(ctx.conn, cursor.lastrowid, ctx)
    return {"token": token}


@route("POST", "/api/login")
def login(ctx):
    username = text_field(ctx.body, "username", 24)
    password = str(ctx.body.get("password", ""))
    user_key = f"login:{username.lower()}"
    ip_key = f"login-ip:{ctx.client_ip()}"
    if LIMITER.blocked(user_key, *LOGIN_LIMIT) or LIMITER.blocked(ip_key, *LOGIN_IP_LIMIT):
        raise ApiError(429, "too many failed attempts - try again in 15 minutes")
    row = ctx.conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    salt = row["pw_salt"] if row else "0" * 32
    candidate, _ = hash_password(password, salt)  # same work for unknown users (no timing leak)
    if not row or not row["has_password"] or not hmac.compare_digest(candidate, row["pw_hash"]):
        LIMITER.hit(user_key, LOGIN_LIMIT[1])
        LIMITER.hit(ip_key, LOGIN_IP_LIMIT[1])
        raise ApiError(401, "wrong username or password")
    LIMITER.reset(user_key)
    token = create_session(ctx.conn, row["id"], ctx)
    award_xp(ctx.conn, row["id"], "daily_login")
    return {"token": token}


@route("POST", "/api/logout")
def logout(ctx):
    header = ctx.handler.headers.get("Authorization", "")
    ctx.conn.execute("DELETE FROM sessions WHERE token=?", (sha256(header[7:]),))
    return {"ok": True}


@route("GET", "/api/me")
def me(ctx):
    user = ctx.user()
    award_xp(ctx.conn, user["id"], "daily_login")
    fresh = ctx.conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    pending = ctx.conn.execute(
        "SELECT COUNT(*) FROM friendships WHERE addressee_id=? AND status='pending'",
        (user["id"],),
    ).fetchone()[0]
    unread = ctx.conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user["id"],)
    ).fetchone()[0]
    private = {
        "payouts_enabled": bool(fresh["payouts_enabled"]),
        "stripe_connected": bool(fresh["stripe_account_id"]),
        "ntfy_topic": fresh["ntfy_topic"],
        "has_password": bool(fresh["has_password"]),
        "has_command_pin": bool(fresh["command_pin_hash"]),
    }
    return {
        "user": dict(public_user(fresh), **private),
        "pending_friend_requests": pending,
        "unread_notifications": unread,
    }


@route("GET", "/api/config")
def public_config(ctx):
    return {
        "payments": "stripe" if STRIPE else "demo",
        "stripe_test_mode": bool(STRIPE and STRIPE.secret_key.startswith("sk_test")),
        "fee_percent": PLATFORM_FEE_PERCENT,
        "currency": CURRENCY,
        "github": GITHUB is not None,
        "vapid_public_key": webpush.b64url(webpush.public_key_bytes(vapid_private_key())),
        "ntfy_base": NTFY_BASE,
    }


@route("POST", "/api/profile")
def update_profile(ctx):
    user = ctx.user()
    bio = text_field(ctx.body, "bio", 280, required=False)
    stack = text_field(ctx.body, "stack", 120, required=False)
    country = text_field(ctx.body, "country", 2, required=False).upper()
    ntfy_topic = text_field(ctx.body, "ntfy_topic", 64, required=False)
    if ntfy_topic and not re.match(r"^[A-Za-z0-9_-]{12,64}$", ntfy_topic):
        raise ApiError(400, "ntfy topic: 12-64 letters, digits, _ or - (make it hard to guess)")
    ctx.conn.execute(
        "UPDATE users SET bio=?, stack=?, country=?, ntfy_topic=? WHERE id=?",
        (bio, stack, country, ntfy_topic, user["id"]),
    )
    return {"ok": True}


# ---------------------------------------------------------------- GitHub login & verification

class Redirect(str):
    """Return this from a route to send a 302 redirect."""


def github_redirect_uri():
    return f"{PUBLIC_URL}/api/auth/github/callback"


def new_oauth_state(conn, user_id=None):
    conn.execute("DELETE FROM oauth_states WHERE created < ?", (now() - 600,))
    state = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO oauth_states(state, user_id, created) VALUES (?,?,?)", (state, user_id, now())
    )
    return state


def unique_username(conn, wanted):
    base = re.sub(r"[^A-Za-z0-9_]", "_", wanted)[:20] or "builder"
    if len(base) < 3:
        base = (base + "___")[:3]
    candidate = base
    suffix = 1
    while conn.execute("SELECT 1 FROM users WHERE username=?", (candidate,)).fetchone():
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


@route("GET", "/api/auth/github/start")
def github_start(ctx):
    if GITHUB is None:
        return Redirect("/#autherror=" + quote("GitHub login is not configured on this server"))
    return Redirect(GITHUB.authorize_url(new_oauth_state(ctx.conn), github_redirect_uri()))


@route("POST", "/api/auth/github/link")
def github_link(ctx):
    user = ctx.user()
    if GITHUB is None:
        raise ApiError(400, "GitHub login is not configured on this server")
    return {"url": GITHUB.authorize_url(new_oauth_state(ctx.conn, user["id"]), github_redirect_uri())}


@route("GET", "/api/auth/github/callback")
def github_callback(ctx):
    conn = ctx.conn
    state = conn.execute(
        "SELECT * FROM oauth_states WHERE state=? AND created > ?", (ctx.arg("state"), now() - 600)
    ).fetchone()
    if GITHUB is None or not state:
        return Redirect("/#autherror=" + quote("login link expired - please try again"))
    conn.execute("DELETE FROM oauth_states WHERE state=?", (state["state"],))
    try:
        access_token = GITHUB.exchange_code(ctx.arg("code"), github_redirect_uri())
        profile = GITHUB.current_user(access_token)
    except GitHubError as error:
        return Redirect("/#autherror=" + quote(str(error)))
    github_id = int(profile["id"])
    login_name = profile.get("login", "")
    avatar = profile.get("avatar_url", "")
    owner = conn.execute("SELECT * FROM users WHERE github_id=?", (github_id,)).fetchone()

    if state["user_id"]:
        if owner and owner["id"] != state["user_id"]:
            return Redirect("/#autherror=" + quote("that GitHub account is linked to another vibeHQ user"))
        conn.execute(
            "UPDATE users SET github_id=?, github_login=?, avatar_url=? WHERE id=?",
            (github_id, login_name, avatar, state["user_id"]),
        )
        return Redirect("/#linked")

    if owner:
        conn.execute(
            "UPDATE users SET github_login=?, avatar_url=? WHERE id=?", (login_name, avatar, owner["id"])
        )
        user_id = owner["id"]
    else:
        # GitHub-only accounts get an unusable password hash; they always log in via GitHub.
        unusable_hash = secrets.token_hex(32)
        salt = secrets.token_hex(16)
        cursor = conn.execute(
            """INSERT INTO users(username, pw_hash, pw_salt, bio, github_id, github_login, avatar_url, created,
                                 has_password)
               VALUES (?,?,?,?,?,?,?,?,0)""",
            (
                unique_username(conn, login_name),
                unusable_hash,
                salt,
                (profile.get("bio") or "")[:280],
                github_id,
                login_name,
                avatar,
                now(),
            ),
        )
        user_id = cursor.lastrowid
    return Redirect(f"/#auth={create_session(conn, user_id, ctx)}")


def parse_github_time(value):
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc
    ).timestamp()


def verify_ship(user, repo_url):
    """A ship is verified when the author owns/contributes to the repo and it was pushed recently."""
    if not repo_url:
        return False, ""
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return False, "not a github.com repository URL"
    if GITHUB is None:
        return False, "GitHub verification is not configured on this server"
    if not user["github_login"]:
        return False, "link your GitHub account to get verified ships"
    owner, name = parsed
    try:
        repo = GITHUB.repo(owner, name)
        if not repo:
            return False, "repository not found (it must be public)"
        login_name = user["github_login"].lower()
        involved = repo.get("owner", {}).get("login", "").lower() == login_name
        if not involved:
            involved = GITHUB.is_contributor(owner, name, user["github_login"])
        if not involved:
            return False, f"@{user['github_login']} isn't the owner or a contributor of {owner}/{name}"
        pushed = parse_github_time(repo.get("pushed_at") or "1970-01-01T00:00:00Z")
        if time.time() - pushed > SHIP_FRESH_DAYS * 86400:
            return False, f"no pushes in the last {SHIP_FRESH_DAYS} days"
    except (GitHubError, ValueError) as error:
        return False, f"couldn't verify: {error}"
    return True, f"verified: @{user['github_login']} shipped {owner}/{name}"


@route("POST", "/api/github/sync")
def github_sync(ctx):
    user = ctx.user()
    if GITHUB is None or not user["github_login"]:
        raise ApiError(400, "link your GitHub account first")
    try:
        events = GITHUB.recent_push_events(user["github_login"])
    except GitHubError as error:
        raise ApiError(502, str(error))
    cutoff = time.time() - PUSH_EVENT_DAYS * 86400
    gained = 0
    fresh = 0
    for event in events:
        try:
            created = parse_github_time(event.get("created_at", ""))
        except ValueError:
            continue
        if created < cutoff:
            continue
        fresh += 1
        gained += award_xp(ctx.conn, user["id"], "github_push", ref=f"gh:{event.get('id')}")
    return {"pushes_found": fresh, "xp_gained": gained}


# ---------------------------------------------------------------- notifications & push API

@route("GET", "/api/notifications")
def list_notifications(ctx):
    user = ctx.user()
    limit = max(1, min(int(ctx.arg("limit", "30") or 30), 100))
    unread_filter = "AND read=0" if ctx.arg("unread") == "1" else ""
    rows = ctx.conn.execute(
        f"""SELECT id, text, link, read, created FROM notifications
            WHERE user_id=? {unread_filter} ORDER BY id DESC LIMIT ?""",
        (user["id"], limit),
    ).fetchall()
    unread = ctx.conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user["id"],)
    ).fetchone()[0]
    return {"notifications": [dict(row) for row in rows], "unread": unread}


@route("POST", "/api/notifications/read")
def read_notifications(ctx):
    user = ctx.user()
    ctx.conn.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
    return {"ok": True}


@route("POST", "/api/push/subscribe")
def push_subscribe(ctx):
    user = ctx.user()
    endpoint = text_field(ctx.body, "endpoint", 1000)
    if not webpush.endpoint_allowed(endpoint, PUSH_EXTRA_HOSTS):
        raise ApiError(400, "unsupported push service")
    ctx.conn.execute(
        """INSERT INTO push_subscriptions(user_id, endpoint, created) VALUES (?,?,?)
           ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id""",
        (user["id"], endpoint, now()),
    )
    return {"ok": True}


@route("POST", "/api/push/unsubscribe")
def push_unsubscribe(ctx):
    user = ctx.user()
    ctx.conn.execute(
        "DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?",
        (user["id"], str(ctx.body.get("endpoint", ""))),
    )
    return {"ok": True}


@route("POST", "/api/push/test")
def push_test(ctx):
    user = ctx.user()
    notify(ctx.conn, user["id"], "🔔 Test notification - push is working!", "feed")
    return {"ok": True}


@route("GET", "/api/users")
def search_users(ctx):
    me_row = ctx.user()
    term = ctx.arg("q").strip()
    rows = ctx.conn.execute(
        "SELECT * FROM users WHERE username LIKE ? AND id!=? ORDER BY xp DESC LIMIT 20",
        (f"%{term}%", me_row["id"]),
    ).fetchall()
    return {"users": [public_user(row) for row in rows]}


@route("GET", "/api/users/([A-Za-z0-9_]+)")
def user_profile(ctx, username):
    viewer = ctx.user()
    target = ctx.user_by_name(username)
    conn = ctx.conn
    relation = "self" if target["id"] == viewer["id"] else "none"
    if relation == "none":
        link = conn.execute(
            """SELECT requester_id, status FROM friendships
               WHERE (requester_id=? AND addressee_id=?) OR (requester_id=? AND addressee_id=?)""",
            (viewer["id"], target["id"], target["id"], viewer["id"]),
        ).fetchone()
        if link and link["status"] == "accepted":
            relation = "friends"
        elif link:
            relation = "outgoing" if link["requester_id"] == viewer["id"] else "incoming"
    rank = conn.execute("SELECT COUNT(*) + 1 FROM users WHERE xp > ?", (target["xp"],)).fetchone()[0]
    stats = {
        "global_rank": rank,
        "ships": conn.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id=? AND kind='ship'", (target["id"],)
        ).fetchone()[0],
        "friends": len(friend_ids(conn, target["id"])),
        "sales": conn.execute(
            """SELECT COUNT(*) FROM orders o JOIN products p ON p.id=o.product_id
               WHERE p.seller_id=? AND o.status='paid'""",
            (target["id"],),
        ).fetchone()[0],
        "tasks_done": conn.execute(
            """SELECT COUNT(*) FROM commands c JOIN devices d ON d.id=c.device_id
               WHERE d.user_id=? AND c.status='done'""",
            (target["id"],),
        ).fetchone()[0],
    }
    return {
        "user": public_user(target),
        "relation": relation,
        "stats": stats,
        "posts": list_posts(conn, viewer["id"], author_id=target["id"], limit=20),
        "products": list_products(conn, viewer["id"], seller_id=target["id"]),
    }


# ---------------------------------------------------------------- feed

def list_posts(conn, viewer_id, kind="", author_id=None, author_ids=None, limit=50):
    clauses = []
    params = [viewer_id]
    if kind:
        clauses.append("p.kind=?")
        params.append(kind)
    if author_id is not None:
        clauses.append("p.user_id=?")
        params.append(author_id)
    if author_ids is not None:
        placeholders = ",".join("?" * len(author_ids)) or "NULL"
        clauses.append(f"p.user_id IN ({placeholders})")
        params.extend(author_ids)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"""SELECT p.*, u.username, u.country, u.xp,
                   (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS like_count,
                   EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) AS liked
            FROM posts p JOIN users u ON u.id=p.user_id
            {where} ORDER BY p.id DESC LIMIT ?""",
        params,
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "body": row["body"],
            "link": row["link"],
            "created": row["created"],
            "author": row["username"],
            "author_country": row["country"],
            "author_tier": tier_for(row["xp"])[0][1],
            "verified": bool(row["verified"]),
            "repo": row["repo"],
            "likes": row["like_count"],
            "liked": bool(row["liked"]),
        }
        for row in rows
    ]


@route("GET", "/api/feed")
def feed(ctx):
    user = ctx.user()
    kind = ctx.arg("kind")
    author_ids = None
    if ctx.arg("scope") == "friends":
        author_ids = friend_ids(ctx.conn, user["id"]) + [user["id"]]
    return {"posts": list_posts(ctx.conn, user["id"], kind=kind, author_ids=author_ids)}


@route("POST", "/api/posts")
def create_post(ctx):
    user = ctx.user()
    kind = ctx.body.get("kind", "post")
    if kind not in POST_KINDS:
        raise ApiError(400, "unknown post kind")
    body = text_field(ctx.body, "body", 2000)
    link = safe_link(text_field(ctx.body, "link", 500, required=False))
    repo = safe_link(text_field(ctx.body, "repo", 300, required=False)) if kind == "ship" else ""
    verified, verify_note = verify_ship(user, repo)
    cursor = ctx.conn.execute(
        "INSERT INTO posts(user_id, kind, body, link, repo, verified, created) VALUES (?,?,?,?,?,?,?)",
        (user["id"], kind, body, link, repo, int(verified), now()),
    )
    gained = award_xp(ctx.conn, user["id"], kind, ref=f"post:{cursor.lastrowid}")
    if verified:
        gained += award_xp(ctx.conn, user["id"], "ship_verified", ref=f"post:{cursor.lastrowid}")
    HUB.broadcast({"type": "feed", "author": user["username"], "kind": kind})
    return {
        "id": cursor.lastrowid,
        "xp_gained": gained,
        "verified": verified,
        "verify_note": verify_note,
    }


@route("POST", r"/api/posts/(\d+)/like")
def toggle_like(ctx, post_id):
    user = ctx.user()
    post = ctx.conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        raise ApiError(404, "post not found")
    existing = ctx.conn.execute(
        "SELECT 1 FROM likes WHERE post_id=? AND user_id=?", (post_id, user["id"])
    ).fetchone()
    if existing:
        ctx.conn.execute("DELETE FROM likes WHERE post_id=? AND user_id=?", (post_id, user["id"]))
        return {"liked": False}
    ctx.conn.execute("INSERT INTO likes(post_id, user_id) VALUES (?,?)", (post_id, user["id"]))
    if post["user_id"] != user["id"]:
        award_xp(ctx.conn, post["user_id"], "like_received", ref=f"{post_id}:{user['id']}")
        notify(ctx.conn, post["user_id"], f"❤️ {user['username']} liked your post", "feed")
    return {"liked": True}


# ---------------------------------------------------------------- friends

@route("GET", "/api/friends")
def friends(ctx):
    user = ctx.user()
    conn = ctx.conn
    online = HUB.online_user_ids()
    ids = friend_ids(conn, user["id"])
    placeholders = ",".join("?" * len(ids)) or "NULL"
    accepted = [
        dict(public_user(row), online=row["id"] in online)
        for row in conn.execute(
            f"SELECT * FROM users WHERE id IN ({placeholders}) ORDER BY xp DESC",
            ids,
        ).fetchall()
    ]
    incoming = conn.execute(
        """SELECT u.* FROM friendships f JOIN users u ON u.id=f.requester_id
           WHERE f.addressee_id=? AND f.status='pending'""",
        (user["id"],),
    ).fetchall()
    outgoing = conn.execute(
        """SELECT u.* FROM friendships f JOIN users u ON u.id=f.addressee_id
           WHERE f.requester_id=? AND f.status='pending'""",
        (user["id"],),
    ).fetchall()
    return {
        "friends": accepted,
        "incoming": [public_user(row) for row in incoming],
        "outgoing": [public_user(row) for row in outgoing],
    }


def accept_friendship(conn, requester, addressee):
    conn.execute(
        "UPDATE friendships SET status='accepted' WHERE requester_id=? AND addressee_id=?",
        (requester["id"], addressee["id"]),
    )
    pair = f"{min(requester['id'], addressee['id'])}:{max(requester['id'], addressee['id'])}"
    award_xp(conn, requester["id"], "friend", ref=pair)
    award_xp(conn, addressee["id"], "friend", ref=pair)
    notify(conn, requester["id"], f"🤝 {addressee['username']} accepted your friend request", "friends")
    HUB.publish(requester["id"], {"type": "friends"})
    HUB.publish(addressee["id"], {"type": "friends"})


@route("POST", "/api/friends/request")
def friend_request(ctx):
    user = ctx.user()
    target = ctx.user_by_name(text_field(ctx.body, "username", 24))
    if target["id"] == user["id"]:
        raise ApiError(400, "you can't friend yourself")
    conn = ctx.conn
    reverse = conn.execute(
        "SELECT status FROM friendships WHERE requester_id=? AND addressee_id=?",
        (target["id"], user["id"]),
    ).fetchone()
    if reverse and reverse["status"] == "pending":
        accept_friendship(conn, target, user)
        return {"status": "accepted"}
    if reverse:
        return {"status": reverse["status"]}
    conn.execute(
        "INSERT OR IGNORE INTO friendships(requester_id, addressee_id, status, created) VALUES (?,?,?,?)",
        (user["id"], target["id"], "pending", now()),
    )
    notify(conn, target["id"], f"👋 {user['username']} sent you a friend request", "friends")
    HUB.publish(target["id"], {"type": "friends"})
    return {"status": "pending"}


@route("POST", "/api/friends/accept")
def friend_accept(ctx):
    user = ctx.user()
    requester = ctx.user_by_name(text_field(ctx.body, "username", 24))
    pending = ctx.conn.execute(
        "SELECT 1 FROM friendships WHERE requester_id=? AND addressee_id=? AND status='pending'",
        (requester["id"], user["id"]),
    ).fetchone()
    if not pending:
        raise ApiError(404, "no pending request from that user")
    accept_friendship(ctx.conn, requester, user)
    return {"status": "accepted"}


@route("POST", "/api/friends/remove")
def friend_remove(ctx):
    user = ctx.user()
    other = ctx.user_by_name(text_field(ctx.body, "username", 24))
    ctx.conn.execute(
        """DELETE FROM friendships WHERE (requester_id=? AND addressee_id=?)
           OR (requester_id=? AND addressee_id=?)""",
        (user["id"], other["id"], other["id"], user["id"]),
    )
    HUB.publish(other["id"], {"type": "friends"})
    return {"ok": True}


# ---------------------------------------------------------------- chat

def resolve_channel(ctx, name):
    """Map 'world' or 'dm:<username>' to a storage key and the DM partner."""
    user = ctx.user()
    if name == "world":
        return "world", None
    if name.startswith("dm:"):
        other = ctx.user_by_name(name[3:])
        if not are_friends(ctx.conn, user["id"], other["id"]):
            raise ApiError(403, "you can only DM friends")
        low, high = sorted((user["id"], other["id"]))
        return f"dm:{low}:{high}", other
    raise ApiError(404, "unknown channel")


def message_json(row):
    return {
        "id": row["id"],
        "sender": row["username"],
        "sender_country": row["country"],
        "body": row["body"],
        "created": row["created"],
    }


@route("GET", "/api/chat/([A-Za-z0-9_:]+)")
def chat_history(ctx, channel_name):
    key, _ = resolve_channel(ctx, channel_name)
    after = int(ctx.arg("after", "0") or 0)
    rows = ctx.conn.execute(
        """SELECT * FROM (
               SELECT m.*, u.username, u.country FROM messages m
               JOIN users u ON u.id=m.sender_id
               WHERE m.channel=? AND m.id>? ORDER BY m.id DESC LIMIT 100
           ) ORDER BY id ASC""",
        (key, after),
    ).fetchall()
    return {"messages": [message_json(row) for row in rows]}


@route("POST", "/api/chat/([A-Za-z0-9_:]+)")
def chat_send(ctx, channel_name):
    user = ctx.user()
    key, other = resolve_channel(ctx, channel_name)
    body = text_field(ctx.body, "body", 2000)
    with CHAT_RATE_LOCK:
        if time.time() - CHAT_RATE.get(user["id"], 0) < 0.7:
            raise ApiError(429, "slow down a little")
        CHAT_RATE[user["id"]] = time.time()
    cursor = ctx.conn.execute(
        "INSERT INTO messages(channel, sender_id, body, created) VALUES (?,?,?,?)",
        (key, user["id"], body, now()),
    )
    message = {
        "id": cursor.lastrowid,
        "sender": user["username"],
        "sender_country": user["country"],
        "body": body,
        "created": now(),
    }
    if other is None:
        HUB.broadcast({"type": "chat", "channel": "world", "message": message})
    else:
        HUB.publish(other["id"], {"type": "chat", "channel": f"dm:{user['username']}", "message": message})
        notify(ctx.conn, other["id"], f"💬 {user['username']}: {body[:100]}", f"dm:{user['username']}")
        HUB.publish(user["id"], {"type": "chat", "channel": f"dm:{other['username']}", "message": message})
    return {"message": message}


# ---------------------------------------------------------------- account security

def require_command_pin(ctx, pin):
    """Agent tasks and shell commands need a separate PIN, so a stolen session alone can't run code."""
    user = ctx.user()
    if not user["command_pin_hash"]:
        raise ApiError(403, "set a command PIN first (Profile → Security)")
    pin_key = f"pin:{user['id']}"
    if LIMITER.blocked(pin_key, *PIN_LIMIT):
        raise ApiError(429, "too many wrong PINs - remote commands locked for 15 minutes")
    candidate, _ = hash_password(pin, user["command_pin_salt"])
    if not hmac.compare_digest(candidate, user["command_pin_hash"]):
        LIMITER.hit(pin_key, PIN_LIMIT[1])
        raise ApiError(403, "wrong command PIN")
    LIMITER.reset(pin_key)


@route("POST", "/api/security/pin")
def set_command_pin(ctx):
    user = ctx.user()
    pin = str(ctx.body.get("pin", ""))
    if not re.match(r"^[0-9]{6,12}$", pin):
        raise ApiError(400, "PIN must be 6-12 digits")
    if user["command_pin_hash"] and not ctx.session_is_fresh():
        require_command_pin(ctx, str(ctx.body.get("current_pin", "")))
    pin_hash, salt = hash_password(pin)
    ctx.conn.execute(
        "UPDATE users SET command_pin_hash=?, command_pin_salt=? WHERE id=?",
        (pin_hash, salt, user["id"]),
    )
    notify(ctx.conn, user["id"], "🔐 Your command PIN was changed", "profile")
    return {"ok": True}


@route("POST", "/api/security/password")
def change_password(ctx):
    user = ctx.user()
    new_password = str(ctx.body.get("new_password", ""))
    if len(new_password) < 8:
        raise ApiError(400, "password must be at least 8 characters")
    if user["has_password"]:
        candidate, _ = hash_password(str(ctx.body.get("current_password", "")), user["pw_salt"])
        if not hmac.compare_digest(candidate, user["pw_hash"]):
            raise ApiError(403, "current password is wrong")
    elif not ctx.session_is_fresh():
        raise ApiError(403, "for safety, sign in again (GitHub) and set your password within 10 minutes")
    pw_hash, salt = hash_password(new_password)
    ctx.conn.execute(
        "UPDATE users SET pw_hash=?, pw_salt=?, has_password=1 WHERE id=?", (pw_hash, salt, user["id"])
    )
    revoked = ctx.conn.execute(
        "DELETE FROM sessions WHERE user_id=? AND token!=?", (user["id"], ctx.session["token"])
    ).rowcount
    notify(ctx.conn, user["id"], "🔐 Your password was changed - other devices were signed out", "profile")
    return {"ok": True, "signed_out_sessions": revoked}


@route("GET", "/api/security/sessions")
def list_sessions(ctx):
    user = ctx.user()
    rows = ctx.conn.execute(
        "SELECT * FROM sessions WHERE user_id=? ORDER BY last_seen DESC", (user["id"],)
    ).fetchall()
    return {"sessions": [
        {
            "id": row["token"][:16],
            "created": row["created"],
            "last_seen": row["last_seen"] or row["created"],
            "user_agent": row["user_agent"],
            "ip": row["ip"],
            "current": row["token"] == ctx.session["token"],
        }
        for row in rows
    ]}


@route("POST", "/api/security/sessions/revoke")
def revoke_sessions(ctx):
    user = ctx.user()
    if ctx.body.get("all_others"):
        count = ctx.conn.execute(
            "DELETE FROM sessions WHERE user_id=? AND token!=?", (user["id"], ctx.session["token"])
        ).rowcount
    else:
        session_id = str(ctx.body.get("id", ""))
        if len(session_id) != 16:
            raise ApiError(400, "invalid session id")
        count = ctx.conn.execute(
            "DELETE FROM sessions WHERE user_id=? AND substr(token, 1, 16)=? AND token!=?",
            (user["id"], session_id, ctx.session["token"]),
        ).rowcount
    return {"signed_out": count}


@route("POST", "/api/stream/ticket")
def stream_ticket(ctx):
    """One-time, 60-second ticket for the live event stream (keeps tokens out of URLs and logs)."""
    user = ctx.user()
    return {"ticket": issue_stream_ticket(user["id"])}


@route("GET", "/api/health")
def health(ctx):
    ctx.conn.execute("SELECT 1").fetchone()
    return {"ok": True, "time": now()}


# ---------------------------------------------------------------- devices & agents

def device_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "online": now() - row["last_seen"] < DEVICE_ONLINE_SECONDS,
        "last_seen": row["last_seen"],
        "info": json.loads(row["info"] or "{}"),
    }


def command_json(row):
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "kind": row["kind"],
        "payload": row["payload"],
        "status": row["status"],
        "result": row["result"],
        "created": row["created"],
        "updated": row["updated"],
    }


def owned_device(ctx, device_id):
    user = ctx.user()
    row = ctx.conn.execute(
        "SELECT * FROM devices WHERE id=? AND user_id=?", (device_id, user["id"])
    ).fetchone()
    if not row:
        raise ApiError(404, "device not found")
    return row


@route("GET", "/api/devices")
def list_devices(ctx):
    user = ctx.user()
    rows = ctx.conn.execute(
        "SELECT * FROM devices WHERE user_id=? ORDER BY id", (user["id"],)
    ).fetchall()
    return {"devices": [device_json(row) for row in rows]}


@route("POST", "/api/devices")
def create_device(ctx):
    user = ctx.user()
    name = text_field(ctx.body, "name", 40)
    count = ctx.conn.execute(
        "SELECT COUNT(*) FROM devices WHERE user_id=?", (user["id"],)
    ).fetchone()[0]
    if count >= 20:
        raise ApiError(400, "device limit reached (20)")
    key = "vhq_" + secrets.token_urlsafe(24)
    cursor = ctx.conn.execute(
        "INSERT INTO devices(user_id, name, key_hash, created) VALUES (?,?,?,?)",
        (user["id"], name, sha256(key), now()),
    )
    return {"id": cursor.lastrowid, "key": key}


@route("POST", r"/api/devices/(\d+)/delete")
def delete_device(ctx, device_id):
    device = owned_device(ctx, device_id)
    ctx.conn.execute("DELETE FROM devices WHERE id=?", (device["id"],))
    return {"ok": True}


@route("GET", r"/api/devices/(\d+)/commands")
def device_commands(ctx, device_id):
    device = owned_device(ctx, device_id)
    rows = ctx.conn.execute(
        "SELECT * FROM commands WHERE device_id=? ORDER BY id DESC LIMIT 50", (device["id"],)
    ).fetchall()
    return {"commands": [command_json(row) for row in rows]}


@route("POST", r"/api/devices/(\d+)/commands")
def send_command(ctx, device_id):
    device = owned_device(ctx, device_id)
    kind = ctx.body.get("kind", "")
    if kind not in COMMAND_KINDS:
        raise ApiError(400, "unknown command kind")
    payload = text_field(ctx.body, "payload", 4000, required=kind in RISKY_COMMANDS)
    if kind in RISKY_COMMANDS:
        require_command_pin(ctx, str(ctx.body.get("pin", "")))
    cursor = ctx.conn.execute(
        "INSERT INTO commands(device_id, kind, payload, status, created, updated) VALUES (?,?,?,?,?,?)",
        (device["id"], kind, payload, "queued", now(), now()),
    )
    row = ctx.conn.execute("SELECT * FROM commands WHERE id=?", (cursor.lastrowid,)).fetchone()
    HUB.publish(device["user_id"], {"type": "command", "command": command_json(row)})
    if kind in RISKY_COMMANDS:
        notify(
            ctx.conn,
            device["user_id"],
            f"🛡️ {kind} sent to {device['name']}. Not you? Profile → Security → sign out everywhere",
            "agents",
        )
    return {"command": command_json(row)}


@route("POST", "/api/agent/heartbeat")
def agent_heartbeat(ctx):
    device = ctx.device()
    info = ctx.body.get("info", {})
    if not isinstance(info, dict):
        raise ApiError(400, "info must be an object")
    encoded = json.dumps(info)[:20000]
    ctx.conn.execute(
        "UPDATE devices SET last_seen=?, info=? WHERE id=?", (now(), encoded, device["id"])
    )
    fresh = ctx.conn.execute("SELECT * FROM devices WHERE id=?", (device["id"],)).fetchone()
    HUB.publish(device["user_id"], {"type": "device", "device": device_json(fresh)})
    return {"ok": True, "device": device["name"]}


@route("GET", "/api/agent/poll")
def agent_poll(ctx):
    device = ctx.device()
    conn = ctx.conn
    conn.execute("UPDATE devices SET last_seen=? WHERE id=?", (now(), device["id"]))
    rows = conn.execute(
        "SELECT * FROM commands WHERE device_id=? AND status='queued' ORDER BY id LIMIT 5",
        (device["id"],),
    ).fetchall()
    claimed = []
    for row in rows:
        conn.execute(
            "UPDATE commands SET status='running', updated=? WHERE id=?", (now(), row["id"])
        )
        updated = dict(command_json(row), status="running")
        claimed.append(updated)
        HUB.publish(device["user_id"], {"type": "command", "command": updated})
    return {"commands": claimed, "server_time": now()}


@route("POST", "/api/agent/result")
def agent_result(ctx):
    device = ctx.device()
    command_id = int(ctx.body.get("id", 0))
    status = ctx.body.get("status")
    if status not in {"done", "failed"}:
        raise ApiError(400, "status must be done or failed")
    result = str(ctx.body.get("result", ""))[-20000:]
    row = ctx.conn.execute(
        "SELECT * FROM commands WHERE id=? AND device_id=?", (command_id, device["id"])
    ).fetchone()
    if not row:
        raise ApiError(404, "command not found")
    ctx.conn.execute(
        "UPDATE commands SET status=?, result=?, updated=? WHERE id=?",
        (status, result, now(), command_id),
    )
    if status == "done" and row["kind"] == "agent_task":
        award_xp(ctx.conn, device["user_id"], "task_done", ref=f"cmd:{command_id}")
    fresh = ctx.conn.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
    HUB.publish(device["user_id"], {"type": "command", "command": command_json(fresh)})
    icon = "✅" if status == "done" else "❌"
    notify(ctx.conn, device["user_id"], f"{icon} {device['name']}: {row['kind']} {status}", "agents")
    return {"ok": True}


# ---------------------------------------------------------------- marketplace

def list_products(conn, viewer_id, seller_id=None, kind=""):
    clauses = []
    params = [viewer_id]
    if seller_id is not None:
        clauses.append("p.seller_id=?")
        params.append(seller_id)
    if kind:
        clauses.append("p.kind=?")
        params.append(kind)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""SELECT p.*, u.username, u.xp, u.payouts_enabled,
                   (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id AND o.status='paid') AS sales,
                   EXISTS(SELECT 1 FROM orders o WHERE o.product_id=p.id AND o.buyer_id=?
                          AND o.status='paid') AS owned
            FROM products p JOIN users u ON u.id=p.seller_id
            {where} ORDER BY sales DESC, p.id DESC LIMIT 100""",
        params,
    ).fetchall()
    products = []
    for row in rows:
        can_see_link = bool(row["owned"]) or row["seller_id"] == viewer_id
        products.append({
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "description": row["description"],
            "price_cents": row["price_cents"],
            "seller": row["username"],
            "seller_tier": tier_for(row["xp"])[0][1],
            "seller_can_sell": bool(row["payouts_enabled"]) or STRIPE is None or row["price_cents"] == 0,
            "sales": row["sales"],
            "owned": bool(row["owned"]),
            "mine": row["seller_id"] == viewer_id,
            "delivery_link": row["delivery_link"] if can_see_link else "",
            "created": row["created"],
        })
    return products


def platform_fee(price_cents):
    return int(round(price_cents * PLATFORM_FEE_PERCENT / 100))


def complete_order(conn, order):
    """Mark an order paid exactly once, then reward the seller and notify both sides."""
    updated = conn.execute(
        "UPDATE orders SET status='paid' WHERE id=? AND status!='paid'", (order["id"],)
    ).rowcount
    if not updated:
        return False
    product = conn.execute("SELECT * FROM products WHERE id=?", (order["product_id"],)).fetchone()
    buyer = conn.execute("SELECT username FROM users WHERE id=?", (order["buyer_id"],)).fetchone()
    award_xp(conn, product["seller_id"], "sale", ref=f"order:{order['id']}")
    notify(conn, product["seller_id"], f"💰 {buyer['username']} bought '{product['title']}'", "market")
    notify(conn, order["buyer_id"], f"📦 Purchase confirmed: {product['title']}", "market")
    return True


@route("GET", "/api/products")
def products(ctx):
    user = ctx.user()
    return {"products": list_products(ctx.conn, user["id"], kind=ctx.arg("kind"))}


@route("POST", "/api/products")
def create_product(ctx):
    user = ctx.user()
    kind = ctx.body.get("kind", "other")
    if kind not in PRODUCT_KINDS:
        raise ApiError(400, "unknown product kind")
    title = text_field(ctx.body, "title", 80)
    description = text_field(ctx.body, "description", 2000)
    delivery_link = safe_link(text_field(ctx.body, "delivery_link", 500, required=False))
    try:
        price_cents = int(round(float(ctx.body.get("price", 0)) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "price must be a number")
    if not 0 <= price_cents <= 1_000_000:
        raise ApiError(400, "price must be between 0 and 10000")
    if 0 < price_cents < 50 and STRIPE is not None:
        raise ApiError(400, "paid products must cost at least 0.50")
    if price_cents and STRIPE is not None and not user["payouts_enabled"]:
        raise ApiError(400, "connect Stripe payouts first (Market → Get paid) to sell paid products")
    cursor = ctx.conn.execute(
        """INSERT INTO products(seller_id, kind, title, description, price_cents, delivery_link, created)
           VALUES (?,?,?,?,?,?,?)""",
        (user["id"], kind, title, description, price_cents, delivery_link, now()),
    )
    return {"id": cursor.lastrowid}


@route("POST", r"/api/products/(\d+)/buy")
def buy_product(ctx, product_id):
    user = ctx.user()
    conn = ctx.conn
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product:
        raise ApiError(404, "product not found")
    if product["seller_id"] == user["id"]:
        raise ApiError(400, "you can't buy your own product")
    owned = conn.execute(
        "SELECT 1 FROM orders WHERE product_id=? AND buyer_id=? AND status='paid'",
        (product_id, user["id"]),
    ).fetchone()
    if owned:
        raise ApiError(409, "you already own this")
    price = product["price_cents"]

    if price == 0 or STRIPE is None:
        # Free products - or demo mode when no Stripe key is configured.
        cursor = conn.execute(
            "INSERT INTO orders(product_id, buyer_id, price_cents, status, created) VALUES (?,?,?,?,?)",
            (product_id, user["id"], price, "pending", now()),
        )
        order = conn.execute("SELECT * FROM orders WHERE id=?", (cursor.lastrowid,)).fetchone()
        complete_order(conn, order)
        return {
            "status": "paid",
            "demo": price > 0,
            "order_id": order["id"],
            "delivery_link": product["delivery_link"],
        }

    seller = conn.execute("SELECT * FROM users WHERE id=?", (product["seller_id"],)).fetchone()
    if not (seller["payouts_enabled"] and seller["stripe_account_id"]):
        raise ApiError(400, "this seller hasn't finished Stripe payout setup yet")
    fee = platform_fee(price)
    try:
        session = STRIPE.create_checkout_session(
            title=product["title"],
            amount_cents=price,
            currency=CURRENCY,
            fee_cents=fee,
            destination=seller["stripe_account_id"],
            success_url=f"{PUBLIC_URL}/?checkout={{CHECKOUT_SESSION_ID}}#market",
            cancel_url=f"{PUBLIC_URL}/#market",
            metadata={"product_id": str(product["id"]), "buyer_id": str(user["id"])},
        )
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}")
    conn.execute(
        "DELETE FROM orders WHERE product_id=? AND buyer_id=? AND status='pending'",
        (product_id, user["id"]),
    )
    conn.execute(
        """INSERT INTO orders(product_id, buyer_id, price_cents, status, stripe_session_id, fee_cents, created)
           VALUES (?,?,?,?,?,?,?)""",
        (product_id, user["id"], price, "pending", session["id"], fee, now()),
    )
    return {"status": "pending", "checkout_url": session["url"]}


@route("GET", "/api/checkout/confirm")
def checkout_confirm(ctx):
    """Fallback for when webhooks aren't reachable (e.g. local dev): ask Stripe directly."""
    user = ctx.user()
    session_id = ctx.arg("session_id")
    order = ctx.conn.execute(
        "SELECT * FROM orders WHERE stripe_session_id=? AND buyer_id=?", (session_id, user["id"])
    ).fetchone()
    if not order or STRIPE is None:
        raise ApiError(404, "order not found")
    if order["status"] != "paid":
        try:
            session = STRIPE.retrieve_checkout_session(session_id)
        except StripeError as error:
            raise ApiError(502, f"payment provider error: {error}")
        if session.get("payment_status") == "paid":
            complete_order(ctx.conn, order)
    fresh = ctx.conn.execute(
        """SELECT o.status, p.delivery_link, p.title FROM orders o
           JOIN products p ON p.id=o.product_id WHERE o.id=?""",
        (order["id"],),
    ).fetchone()
    paid = fresh["status"] == "paid"
    return {
        "status": fresh["status"],
        "title": fresh["title"],
        "delivery_link": fresh["delivery_link"] if paid else "",
    }


@route("POST", "/api/stripe/webhook")
def stripe_webhook(ctx):
    if STRIPE is None or not STRIPE_WEBHOOK_SECRET:
        raise ApiError(404, "webhooks not configured")
    try:
        event = verify_webhook(
            ctx.raw_body,
            ctx.handler.headers.get("Stripe-Signature", ""),
            STRIPE_WEBHOOK_SECRET,
        )
    except (StripeError, ValueError) as error:
        raise ApiError(400, str(error))
    kind = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if data.get("payment_status") == "paid":
            order = ctx.conn.execute(
                "SELECT * FROM orders WHERE stripe_session_id=?", (data.get("id", ""),)
            ).fetchone()
            if order:
                complete_order(ctx.conn, order)
    elif kind == "account.updated":
        ready = bool(data.get("charges_enabled") and data.get("details_submitted"))
        ctx.conn.execute(
            "UPDATE users SET payouts_enabled=? WHERE stripe_account_id=?",
            (int(ready), data.get("id", "")),
        )
    return {"received": True}


@route("POST", "/api/payouts/connect")
def payouts_connect(ctx):
    user = ctx.user()
    if STRIPE is None:
        raise ApiError(400, "payments run in demo mode - add STRIPE_SECRET_KEY to enable payouts")
    account_id = user["stripe_account_id"]
    try:
        if not account_id:
            account = STRIPE.create_express_account({"vibehq_user_id": str(user["id"])})
            account_id = account["id"]
            ctx.conn.execute(
                "UPDATE users SET stripe_account_id=? WHERE id=?", (account_id, user["id"])
            )
        link = STRIPE.create_onboarding_link(
            account_id,
            refresh_url=f"{PUBLIC_URL}/?payouts=refresh#market",
            return_url=f"{PUBLIC_URL}/?payouts=done#market",
        )
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}")
    return {"url": link["url"]}


@route("POST", "/api/payouts/refresh")
def payouts_refresh(ctx):
    user = ctx.user()
    if STRIPE is None or not user["stripe_account_id"]:
        return {"payouts_enabled": bool(user["payouts_enabled"])}
    try:
        account = STRIPE.retrieve_account(user["stripe_account_id"])
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}")
    ready = bool(account.get("charges_enabled") and account.get("details_submitted"))
    ctx.conn.execute("UPDATE users SET payouts_enabled=? WHERE id=?", (int(ready), user["id"]))
    return {"payouts_enabled": ready}


@route("GET", "/api/orders")
def orders(ctx):
    user = ctx.user()
    purchases = ctx.conn.execute(
        """SELECT o.id, o.price_cents, o.created, p.title, p.delivery_link, u.username AS seller
           FROM orders o JOIN products p ON p.id=o.product_id JOIN users u ON u.id=p.seller_id
           WHERE o.buyer_id=? AND o.status='paid' ORDER BY o.id DESC""",
        (user["id"],),
    ).fetchall()
    sales = ctx.conn.execute(
        """SELECT o.id, o.price_cents, o.fee_cents, o.created, p.title, u.username AS buyer
           FROM orders o JOIN products p ON p.id=o.product_id JOIN users u ON u.id=o.buyer_id
           WHERE p.seller_id=? AND o.status='paid' ORDER BY o.id DESC""",
        (user["id"],),
    ).fetchall()
    return {
        "purchases": [dict(row) for row in purchases],
        "sales": [dict(row) for row in sales],
        "revenue_cents": sum(row["price_cents"] for row in sales),
        "net_cents": sum(row["price_cents"] - row["fee_cents"] for row in sales),
    }


# ---------------------------------------------------------------- ladder

@route("GET", "/api/ladder")
def ladder(ctx):
    user = ctx.user()
    scope = ctx.arg("scope", "global")
    period = ctx.arg("period", "all")
    clauses = []
    params = []
    if scope == "country":
        clauses.append("u.country=?")
        params.append(user["country"])
    elif scope == "friends":
        ids = friend_ids(ctx.conn, user["id"]) + [user["id"]]
        clauses.append(f"u.id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    if period == "week":
        score_sql = "(SELECT COALESCE(SUM(amount),0) FROM xp_log x WHERE x.user_id=u.id AND x.created>?)"
        params.insert(0, now() - 7 * 86400)
    else:
        score_sql = "u.xp"
    rows = ctx.conn.execute(
        f"SELECT u.*, {score_sql} AS score FROM users u {where} ORDER BY score DESC, u.id ASC",
        params,
    ).fetchall()
    online = HUB.online_user_ids()
    entries = []
    my_rank = None
    for index, row in enumerate(rows, start=1):
        if row["id"] == user["id"]:
            my_rank = index
        if index <= 100:
            entries.append(dict(public_user(row), rank=index, score=row["score"], online=row["id"] in online))
    return {"entries": entries, "my_rank": my_rank, "total": len(rows)}


# ---------------------------------------------------------------- HTTP plumbing

class Handler(BaseHTTPRequestHandler):
    server_version = "VibeHQ/0.1"

    def log_message(self, fmt, *args):
        if os.environ.get("VIBEHQ_QUIET") != "1":
            super().log_message(fmt, *args)

    def security_headers(self, html=False):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if PUBLIC_URL.startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if html:
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)

    def send_json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        self.end_headers()

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if method == "GET" and not path.startswith("/api/"):
            return self.serve_static(path)
        if method == "GET" and path == "/api/stream":
            return self.serve_stream(parse_qs(parsed.query))
        body = {}
        raw = b""
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                return self.send_json(413, {"error": "request too large"})
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self.send_json(400, {"error": "invalid JSON"})
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "JSON object expected"})
        for route_method, pattern, handler in ROUTES:
            match = pattern.match(path)
            if route_method == method and match:
                conn = connect()
                _REQUEST_STATE.pushes = []
                try:
                    ctx = Ctx(self, conn, parse_qs(parsed.query), body, raw)
                    result = handler(ctx, *match.groups())
                    conn.commit()
                    for item in _REQUEST_STATE.pushes:
                        PUSH_QUEUE.put(item)
                    if isinstance(result, Redirect):
                        return self.send_redirect(result)
                    return self.send_json(200, result)
                except ApiError as error:
                    conn.rollback()
                    return self.send_json(error.status, {"error": error.message})
                except Exception as error:  # keep the server alive, report the fault
                    conn.rollback()
                    self.log_error("unhandled error: %r", error)
                    return self.send_json(500, {"error": "internal error"})
                finally:
                    _REQUEST_STATE.pushes = None
                    conn.close()
        return self.send_json(404, {"error": "not found"})

    def serve_stream(self, query):
        user_id = redeem_stream_ticket(query.get("ticket", [""])[0])
        if user_id is None:
            return self.send_json(401, {"error": "stream ticket missing or expired"})
        if HUB.stream_count(user_id) >= MAX_STREAMS_PER_USER:
            return self.send_json(429, {"error": "too many open streams"})
        user = {"id": user_id}
        events = HUB.subscribe(user["id"])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.security_headers()
        self.end_headers()
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = events.get(timeout=15)
                    chunk = f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    chunk = ": keepalive\n\n"
                self.wfile.write(chunk.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            HUB.unsubscribe(user["id"], events)

    def serve_static(self, path):
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        if relative.startswith("static/"):
            relative = relative[len("static/"):]
        full = os.path.realpath(os.path.join(STATIC_DIR, relative))
        if not full.startswith(os.path.realpath(STATIC_DIR)) or not os.path.isfile(full):
            full = os.path.join(STATIC_DIR, "index.html")
        with open(full, "rb") as handle:
            data = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.security_headers(html=full.endswith(".html"))
        self.end_headers()
        self.wfile.write(data)


# ---------------------------------------------------------------- demo data

def seed_demo():
    conn = connect()
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        conn.close()
        return
    people = [
        ("alice", "US", "Ships SaaS with Claude Code at 2am", "Next.js, Supabase, Claude Code", 3200),
        ("budi", "ID", "Indie hacker from Jakarta. Agents do my chores.", "Flutter, Firebase, Codex", 1800),
        ("chen", "CN", "Local LLM tinkerer", "Ollama, Rust, Aider", 950),
        ("dara", "BR", "Prompt engineer & template seller", "Cursor, Tailwind, Stripe", 5400),
        ("emeka", "NG", "Building agent workflows for Africa's SMBs", "Python, FastAPI, Gemini CLI", 420),
    ]
    ids = {}
    for name, country, bio, stack, xp in people:
        pw_hash, salt = hash_password("demo1234")
        cursor = conn.execute(
            """INSERT INTO users(username, pw_hash, pw_salt, country, bio, stack, xp, created)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, pw_hash, salt, country, bio, stack, xp, now() - 86400 * 30),
        )
        ids[name] = cursor.lastrowid
        conn.execute(
            "INSERT INTO xp_log(user_id, amount, reason, ref, created) VALUES (?,?,?,?,?)",
            (cursor.lastrowid, xp // 4, "ship", "seed", now() - 3600),
        )
    posts = [
        ("dara", "ship", "Shipped a landing-page kit: 12 sections, all generated + hand-polished. 4 hours start to Stripe.", "https://example.com/kit"),
        ("alice", "tip", "Tip: give your coding agent a TASKS.md and make it tick boxes. Way fewer 'creative' detours.", ""),
        ("budi", "news", "New open-weight coding models dropped this week - benchmarks look close to frontier for refactors.", ""),
        ("chen", "tip", "Run 2 agents in separate git worktrees so they never fight over the same files.", ""),
        ("emeka", "ship", "My agent now reconciles invoices for a bakery in Lagos every night. First paying user!", ""),
        ("alice", "ship", "VibeHQ challenge entry: habit tracker built 100% by agents in 48h.", "https://example.com/habits"),
    ]
    for offset, (author, kind, body, link) in enumerate(posts):
        conn.execute(
            "INSERT INTO posts(user_id, kind, body, link, created) VALUES (?,?,?,?,?)",
            (ids[author], kind, body, link, now() - 3600 * (len(posts) - offset)),
        )
    for a, b in [("alice", "budi"), ("alice", "dara"), ("budi", "chen"), ("dara", "emeka")]:
        conn.execute(
            "INSERT INTO friendships(requester_id, addressee_id, status, created) VALUES (?,?,?,?)",
            (ids[a], ids[b], "accepted", now()),
        )
    conn.execute(
        "INSERT INTO friendships(requester_id, addressee_id, status, created) VALUES (?,?,?,?)",
        (ids["chen"], ids["alice"], "pending", now()),
    )
    products = [
        ("dara", "template", "SaaS Landing Kit", "12 conversion-tested sections, Tailwind + Next.js.", 2900, "https://example.com/dl/kit"),
        ("alice", "prompt", "Claude Code Power Prompts", "40 battle-tested prompts for refactors, tests and migrations.", 900, "https://example.com/dl/prompts"),
        ("chen", "mcp", "Local Docs MCP Server", "Give any agent offline search over your docs folder.", 0, "https://example.com/dl/mcp"),
        ("budi", "agent", "Nightly Bug-Triage Agent", "Agent config that labels and reproduces new GitHub issues.", 1500, "https://example.com/dl/triage"),
    ]
    for seller, kind, title, description, price, link in products:
        conn.execute(
            """INSERT INTO products(seller_id, kind, title, description, price_cents, delivery_link, created)
               VALUES (?,?,?,?,?,?,?)""",
            (ids[seller], kind, title, description, price, link, now()),
        )
    chat = [
        ("budi", "Selamat pagi from Jakarta! Who's shipping today?"),
        ("dara", "Boa tarde! Finishing a template, agents running in the background"),
        ("chen", "My local model just passed all tests on the first try. Rare day."),
    ]
    for sender, body in chat:
        conn.execute(
            "INSERT INTO messages(channel, sender_id, body, created) VALUES (?,?,?,?)",
            ("world", ids[sender], body, now() - 600),
        )
    conn.commit()
    conn.close()
    print("Demo data loaded. Log in as alice / demo1234 (or budi, chen, dara, emeka).")


def main():
    parser = argparse.ArgumentParser(description="VibeHQ server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true", help="seed demo users and content")
    args = parser.parse_args()
    global PUBLIC_URL
    if not PUBLIC_URL:
        shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        PUBLIC_URL = f"http://{shown_host}:{args.port}"
    init_db()
    if args.demo:
        seed_demo()
    vapid_private_key()
    threading.Thread(target=push_worker, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    if STRIPE is None:
        payments = "demo (set STRIPE_SECRET_KEY for real payments)"
    elif STRIPE.secret_key.startswith("sk_test"):
        payments = "Stripe TEST mode"
    else:
        payments = "Stripe LIVE"
    print(f"VibeHQ running on http://{args.host}:{args.port}  (public URL {PUBLIC_URL})")
    print(f"  payments:     {payments}")
    print(f"  GitHub login: {'on' if GITHUB else 'off (set GITHUB_CLIENT_ID/SECRET)'}")
    print(f"  push:         web push on, ntfy via {NTFY_BASE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
