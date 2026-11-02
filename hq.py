"""shiphub HQ: the vibe-coder side of shiphub.

Same accounts, same database, same server as the idea board. Adds:
  - feed of ships / tips / news (GitHub-verified ships) and likes
  - XP, tiers and a ladder (global / country / friends, all-time / week)
  - friends and chat (world channel + DMs), live over server-sent events
  - devices: run agent.py on your machines, see running agents, send tasks
    (agent tasks and shell commands need a separate command PIN)
  - marketplace with Stripe Connect payouts (demo mode without a key)
  - phone push (Web Push / ntfy) for HQ notifications

server.py wires this module in with bind() and registers ROUTES. All SQL is
written SQLite-style and runs on Postgres through server.Database.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import math
import os
import queue
import re
import secrets
import threading
import time
import urllib.request
from urllib.parse import quote, urlparse

import webpush
from github_client import GitHub, GitHubError, parse_repo_url
from stripe_client import Stripe, StripeError, verify_webhook

# --------------------------------------------------------------------------- #
# Wiring (set by server.bind_hq)
# --------------------------------------------------------------------------- #


class _Unbound(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


ApiError = _Unbound
connect = None
SETTINGS = None


def bind(*, api_error, connect_fn, settings) -> None:
    global ApiError, connect, SETTINGS
    ApiError = api_error
    connect = connect_fn
    SETTINGS = settings


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

PLATFORM_FEE_PERCENT = float(os.environ.get("PLATFORM_FEE_PERCENT", "10"))
CURRENCY = os.environ.get("CURRENCY", "usd").lower()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE = (
    Stripe(os.environ["STRIPE_SECRET_KEY"], api_base=os.environ.get("STRIPE_API_BASE", "https://api.stripe.com"))
    if os.environ.get("STRIPE_SECRET_KEY") else None
)

# GitHub API access for verified ships (the same OAuth app shiphub signs in with works fine).
GITHUB = (
    GitHub(
        os.environ.get("GITHUB_CLIENT_ID", ""),
        os.environ.get("GITHUB_CLIENT_SECRET", ""),
        api_base=os.environ.get("GITHUB_API_URL") or os.environ.get("GITHUB_API_BASE") or "https://api.github.com",
        app_token=os.environ.get("GITHUB_TOKEN") or None,
    )
    if (os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET")) or os.environ.get("GITHUB_TOKEN")
    else None
)
SHIP_FRESH_DAYS = 30
PUSH_EVENT_DAYS = 7

NTFY_BASE = os.environ.get("NTFY_BASE", "https://ntfy.sh").rstrip("/")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
PUSH_EXTRA_HOSTS = {host.strip().lower() for host in os.environ.get("PUSH_EXTRA_HOSTS", "").split(",") if host.strip()}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

DEVICE_ONLINE_SECONDS = 30
COMMAND_KINDS = {"ping", "sysinfo", "list_agents", "agent_task", "shell"}
RISKY_COMMANDS = {"agent_task", "shell"}
POST_KINDS = {"ship", "tip", "news", "post"}
PRODUCT_KINDS = {"template", "prompt", "agent", "mcp", "app", "course", "other"}
FRESH_SESSION_SECONDS = 600
MAX_STREAMS_PER_USER = 5
PIN_LIMIT = (5, 900)  # wrong command PINs per user per 15 min

# XP per action and a daily cap per action (anti-farming). Idea-board actions earn XP too.
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
    "idea": (15, 5),
    "idea_shipped": (60, 3),
    "comment": (2, 20),
}
TIERS = [
    (0, "Bronze"),
    (500, "Silver"),
    (1500, "Gold"),
    (4000, "Platinum"),
    (10000, "Diamond"),
    (25000, "Legend"),
]

# --------------------------------------------------------------------------- #
# Schema (merged into server.SCHEMA; {pk} is the dialect's auto-increment key)
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS hq_friendships (
    requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    created BIGINT NOT NULL,
    PRIMARY KEY (requester_id, addressee_id)
);
CREATE TABLE IF NOT EXISTS hq_posts (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    link TEXT NOT NULL DEFAULT '',
    repo TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    created BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hq_posts_user ON hq_posts(user_id, id);
CREATE TABLE IF NOT EXISTS hq_likes (
    post_id INTEGER NOT NULL REFERENCES hq_posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS hq_messages (
    id {pk},
    channel TEXT NOT NULL,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hq_messages_channel ON hq_messages(channel, id);
CREATE TABLE IF NOT EXISTS hq_devices (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    last_seen BIGINT NOT NULL DEFAULT 0,
    info TEXT NOT NULL DEFAULT '{}',
    created BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS hq_commands (
    id {pk},
    device_id INTEGER NOT NULL REFERENCES hq_devices(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    created BIGINT NOT NULL,
    updated BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hq_commands_device ON hq_commands(device_id, status);
CREATE TABLE IF NOT EXISTS hq_products (
    id {pk},
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    delivery_link TEXT NOT NULL DEFAULT '',
    created BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS hq_orders (
    id {pk},
    product_id INTEGER NOT NULL REFERENCES hq_products(id) ON DELETE CASCADE,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    price_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    stripe_session_id TEXT NOT NULL DEFAULT '',
    fee_cents INTEGER NOT NULL DEFAULT 0,
    created BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hq_orders_session ON hq_orders(stripe_session_id);
CREATE TABLE IF NOT EXISTS hq_xp_log (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    ref TEXT NOT NULL DEFAULT '',
    created BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hq_xp_user ON hq_xp_log(user_id, reason, created);
CREATE TABLE IF NOT EXISTS hq_push_subscriptions (
    id {pk},
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    created BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS hq_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added to shiphub tables (applied in place on existing databases).
MIGRATIONS = [
    ("users", "country", "TEXT NOT NULL DEFAULT ''"),
    ("users", "stack", "TEXT NOT NULL DEFAULT ''"),
    ("users", "xp", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "stripe_account_id", "TEXT NOT NULL DEFAULT ''"),
    ("users", "payouts_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "ntfy_topic", "TEXT NOT NULL DEFAULT ''"),
    ("users", "command_pin_hash", "TEXT NOT NULL DEFAULT ''"),
    ("users", "command_pin_salt", "TEXT NOT NULL DEFAULT ''"),
    ("notifications", "text", "TEXT NOT NULL DEFAULT ''"),
    ("notifications", "link", "TEXT NOT NULL DEFAULT ''"),
    ("sessions", "created_at", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
]

POST_MIGRATION_SQL = """
CREATE INDEX IF NOT EXISTS idx_users_xp ON users (xp);
"""

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def now() -> int:
    return int(time.time())


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def pin_hash(pin: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000)
    return digest.hex(), salt


def tier_for(xp: int):
    current = TIERS[0]
    following = None
    for index, (threshold, name) in enumerate(TIERS):
        if xp >= threshold:
            current = (threshold, name)
            following = TIERS[index + 1] if index + 1 < len(TIERS) else None
    return current, following


def hq_user(row) -> dict:
    """Public HQ view of a shiphub user."""
    xp = row["xp"] or 0
    (tier_floor, tier_name), following = tier_for(xp)
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "avatar_hue": row["avatar_hue"],
        "avatar_url": row["avatar_url"] or "",
        "github_login": row["github_login"] or "",
        "bio": row["bio"],
        "country": row["country"],
        "stack": row["stack"],
        "xp": xp,
        "level": int(math.sqrt(xp / 100)) + 1,
        "tier": tier_name,
        "tier_floor": tier_floor,
        "next_tier": following[1] if following else None,
        "next_tier_xp": following[0] if following else None,
    }


def author_json(row, prefix="") -> dict:
    return {
        "username": row[f"{prefix}username"],
        "display_name": row[f"{prefix}display_name"],
        "avatar_hue": row[f"{prefix}avatar_hue"],
        "avatar_url": row[f"{prefix}avatar_url"] or "",
    }


def text_field(body: dict, name: str, max_len: int, required: bool = True) -> str:
    value = str(body.get(name, "") or "").strip()
    if required and not value:
        raise ApiError(400, f"'{name}' is required")
    if len(value) > max_len:
        raise ApiError(400, f"'{name}' is too long (max {max_len})")
    return value


def safe_link(value: str) -> str:
    if value and not re.match(r"^https?://", value, re.I):
        raise ApiError(400, "links must start with http:// or https://")
    return value


def require_user(ctx):
    if not ctx.user:
        raise ApiError(401, "Log in to do that")
    return ctx.user


def user_by_name(db, username: str):
    row = db.execute("SELECT * FROM users WHERE lower(username) = lower(?)", (username,)).fetchone()
    if not row:
        raise ApiError(404, f"user '{username}' not found")
    return row


def in_clause(ids) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def award_xp(db, user_id: int, reason: str, ref: str = "") -> int:
    """Grant XP for an action, respecting daily caps and one-time refs."""
    amount, daily_cap = XP_RULES[reason]
    if ref and db.execute(
        "SELECT 1 FROM hq_xp_log WHERE user_id = ? AND reason = ? AND ref = ?", (user_id, reason, ref)
    ).fetchone():
        return 0
    used_today = db.execute(
        "SELECT COUNT(*) FROM hq_xp_log WHERE user_id = ? AND reason = ? AND created > ?",
        (user_id, reason, now() - 86400),
    ).fetchone()[0]
    if used_today >= daily_cap:
        return 0
    db.execute(
        "INSERT INTO hq_xp_log (user_id, amount, reason, ref, created) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, reason, ref, now()),
    )
    db.execute("UPDATE users SET xp = xp + ? WHERE id = ?", (amount, user_id))
    return amount


def friend_ids(db, user_id: int) -> list[int]:
    rows = db.execute(
        """SELECT CASE WHEN requester_id = ? THEN addressee_id ELSE requester_id END AS fid
           FROM hq_friendships
           WHERE status = 'accepted' AND (requester_id = ? OR addressee_id = ?)""",
        (user_id, user_id, user_id),
    ).fetchall()
    return [row["fid"] for row in rows]


def are_friends(db, a: int, b: int) -> bool:
    return db.execute(
        """SELECT 1 FROM hq_friendships WHERE status = 'accepted' AND
           ((requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?))""",
        (a, b, b, a),
    ).fetchone() is not None


# --------------------------------------------------------------------------- #
# Realtime hub (server-sent events)
# --------------------------------------------------------------------------- #


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.subscribers: dict[int, set] = {}

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
CHAT_RATE: dict[int, float] = {}
CHAT_RATE_LOCK = threading.Lock()


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: dict[str, list[float]] = {}

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

# --------------------------------------------------------------------------- #
# Notifications (shared with the idea board's bell) + phone push
# --------------------------------------------------------------------------- #

PUSH_QUEUE: queue.Queue = queue.Queue()
_REQUEST_STATE = threading.local()
_VAPID_LOCK = threading.Lock()
_VAPID_KEY = None


def notify(db, user_id: int, text: str, link: str = "hq", actor_id: int | None = None) -> None:
    """HQ notification: shows in the shared bell, live over SSE, and as a phone push after commit."""
    actor = actor_id or user_id
    notification_id = db.insert(
        "INSERT INTO notifications (user_id, actor_id, kind, text, link, created_at) VALUES (?, ?, 'hq', ?, ?, ?)",
        (user_id, actor, text, link, time.time()),
    )
    HUB.publish(user_id, {"type": "notify", "id": notification_id, "text": text, "link": link})
    pending = getattr(_REQUEST_STATE, "pushes", None)
    if pending is None:
        PUSH_QUEUE.put((user_id, text, link))
    else:
        pending.append((user_id, text, link))


def begin_request() -> None:
    _REQUEST_STATE.pushes = []


def end_request(committed: bool) -> None:
    pending = getattr(_REQUEST_STATE, "pushes", None) or []
    _REQUEST_STATE.pushes = None
    if committed:
        for item in pending:
            PUSH_QUEUE.put(item)


def vapid_private_key() -> int:
    global _VAPID_KEY
    with _VAPID_LOCK:
        if _VAPID_KEY is None:
            db = connect()
            try:
                row = db.execute("SELECT value FROM hq_settings WHERE key = 'vapid_private'").fetchone()
                if row:
                    _VAPID_KEY = int(row["value"], 16)
                else:
                    _VAPID_KEY = webpush.generate_private_key()
                    db.execute(
                        "INSERT INTO hq_settings (key, value) VALUES ('vapid_private', ?)",
                        (format(_VAPID_KEY, "x"),),
                    )
                    db.commit()
            finally:
                db.close()
        return _VAPID_KEY


def opener_for(url: str):
    """System proxy for internet services, never for loopback/test hosts."""
    host = (urlparse(url).hostname or "").lower()
    if host in LOOPBACK_HOSTS or host in PUSH_EXTRA_HOSTS:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def send_ntfy(topic: str, text: str, link: str) -> int:
    headers = {"Title": "shiphub", "Tags": "rocket"}
    if SETTINGS and SETTINGS.public_url:
        headers["Click"] = f"{SETTINGS.public_url}/#/{link or 'hq'}"
    request = urllib.request.Request(
        f"{NTFY_BASE}/{quote(topic)}", data=text.encode("utf-8"), method="POST", headers=headers
    )
    with opener_for(request.full_url).open(request, timeout=15) as response:
        return response.status


def deliver_push(user_id: int, text: str, link: str) -> None:
    db = connect()
    try:
        user = db.execute("SELECT ntfy_topic FROM users WHERE id = ?", (user_id,)).fetchone()
        subscriptions = db.execute(
            "SELECT id, endpoint FROM hq_push_subscriptions WHERE user_id = ?", (user_id,)
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
                print(f"  push failed: {error}")
                continue
            if status in (404, 410):
                db.execute("DELETE FROM hq_push_subscriptions WHERE id = ?", (subscription["id"],))
        db.commit()
        if user and user["ntfy_topic"]:
            try:
                send_ntfy(user["ntfy_topic"], text, link)
            except OSError as error:
                print(f"  ntfy failed: {error}")
    finally:
        db.close()


def push_worker() -> None:
    while True:
        user_id, text, link = PUSH_QUEUE.get()
        try:
            deliver_push(user_id, text, link)
        except Exception as error:  # noqa: BLE001 - one bad push must not kill the worker
            print(f"  push worker error: {error!r}")


def start_background() -> None:
    vapid_private_key()
    threading.Thread(target=push_worker, daemon=True, name="hq-push").start()


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

ROUTES: list[tuple[str, str, object, bool, object]] = []


def api(method: str, path: str, auth: bool = False, raw=False):
    def register(func):
        ROUTES.append((method, path, func, auth, raw))
        return func
    return register


@api("GET", "/api/hq/config")
def hq_config(ctx):
    return {
        "payments": "stripe" if STRIPE else "demo",
        "stripe_test_mode": bool(STRIPE and STRIPE.secret_key.startswith("sk_test")),
        "fee_percent": PLATFORM_FEE_PERCENT,
        "currency": CURRENCY,
        "github_verify": GITHUB is not None,
        "vapid_public_key": webpush.b64url(webpush.public_key_bytes(vapid_private_key())),
        "ntfy_base": NTFY_BASE,
    }


@api("GET", "/api/hq/me", auth=True)
def hq_me(ctx):
    user = ctx.user
    award_xp(ctx.db, user["id"], "daily_login")
    fresh = ctx.db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    pending = ctx.db.execute(
        "SELECT COUNT(*) FROM hq_friendships WHERE addressee_id = ? AND status = 'pending'", (user["id"],)
    ).fetchone()[0]
    rank = ctx.db.execute("SELECT COUNT(*) + 1 FROM users WHERE xp > ?", (fresh["xp"],)).fetchone()[0]
    return {
        "user": dict(
            hq_user(fresh),
            ntfy_topic=fresh["ntfy_topic"],
            has_command_pin=bool(fresh["command_pin_hash"]),
            payouts_enabled=bool(fresh["payouts_enabled"]),
            stripe_connected=bool(fresh["stripe_account_id"]),
            has_password=bool(fresh["password_hash"]),
        ),
        "rank": rank,
        "pending_friend_requests": pending,
    }


@api("POST", "/api/hq/profile", auth=True)
def hq_profile_update(ctx):
    stack = text_field(ctx.body, "stack", 120, required=False)
    country = text_field(ctx.body, "country", 2, required=False).upper()
    if country and not re.match(r"^[A-Z]{2}$", country):
        raise ApiError(400, "country: two letters, e.g. US, ID, BR")
    ntfy_topic = text_field(ctx.body, "ntfy_topic", 64, required=False)
    if ntfy_topic and not re.match(r"^[A-Za-z0-9_-]{12,64}$", ntfy_topic):
        raise ApiError(400, "ntfy topic: 12-64 letters, digits, _ or - (make it hard to guess)")
    ctx.db.execute(
        "UPDATE users SET stack = ?, country = ?, ntfy_topic = ? WHERE id = ?",
        (stack, country, ntfy_topic, ctx.user["id"]),
    )
    return {"ok": True}


# ----- feed ------------------------------------------------------------------ #

POST_SELECT = """
SELECT p.*, u.username, u.display_name, u.avatar_hue, u.avatar_url, u.country, u.xp,
       (SELECT COUNT(*) FROM hq_likes l WHERE l.post_id = p.id) AS like_count,
       (SELECT COUNT(*) FROM hq_likes l WHERE l.post_id = p.id AND l.user_id = ?) AS liked
FROM hq_posts p JOIN users u ON u.id = p.user_id
"""


def list_posts(db, viewer_id: int, kind: str = "", author_id=None, author_ids=None, limit: int = 50):
    clauses = []
    params: list = [viewer_id]
    if kind:
        clauses.append("p.kind = ?")
        params.append(kind)
    if author_id is not None:
        clauses.append("p.user_id = ?")
        params.append(author_id)
    if author_ids is not None:
        clauses.append(f"p.user_id IN ({in_clause(author_ids)})")
        params.extend(author_ids)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = db.execute(f"{POST_SELECT} {where} ORDER BY p.id DESC LIMIT ?", params).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "body": row["body"],
            "link": row["link"],
            "repo": row["repo"],
            "verified": bool(row["verified"]),
            "created": row["created"],
            "author": dict(author_json(row), country=row["country"], tier=tier_for(row["xp"] or 0)[0][1]),
            "likes": row["like_count"],
            "liked": bool(row["liked"]),
        }
        for row in rows
    ]


@api("GET", "/api/hq/feed")
def hq_feed(ctx):
    viewer = ctx.user["id"] if ctx.user else 0
    kind = ctx.q("kind")
    if kind and kind not in POST_KINDS:
        kind = ""
    author_ids = None
    if ctx.q("scope") == "friends":
        user = require_user(ctx)
        author_ids = friend_ids(ctx.db, user["id"]) + [user["id"]]
    return {"posts": list_posts(ctx.db, viewer, kind=kind, author_ids=author_ids)}


def parse_github_time(value: str) -> float:
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc
    ).timestamp()


def verify_ship(user, repo_url: str):
    """Verified = the author owns or contributes to the public repo and it was pushed recently."""
    if not repo_url:
        return False, ""
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return False, "not a github.com repository URL"
    if GITHUB is None:
        return False, "GitHub verification is not configured on this server"
    if not user["github_login"]:
        return False, "sign in with GitHub (or link it in your profile) to get verified ships"
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


@api("POST", "/api/hq/posts", auth=True)
def hq_create_post(ctx):
    user = ctx.user
    kind = ctx.body.get("kind", "post")
    if kind not in POST_KINDS:
        raise ApiError(400, "unknown post kind")
    body = text_field(ctx.body, "body", 2000)
    link = safe_link(text_field(ctx.body, "link", 500, required=False))
    repo = safe_link(text_field(ctx.body, "repo", 300, required=False)) if kind == "ship" else ""
    verified, verify_note = verify_ship(user, repo)
    post_id = ctx.db.insert(
        "INSERT INTO hq_posts (user_id, kind, body, link, repo, verified, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["id"], kind, body, link, repo, int(verified), now()),
    )
    gained = award_xp(ctx.db, user["id"], kind, ref=f"post:{post_id}")
    if verified:
        gained += award_xp(ctx.db, user["id"], "ship_verified", ref=f"post:{post_id}")
    HUB.broadcast({"type": "feed", "author": user["username"], "kind": kind})
    return {"id": post_id, "xp_gained": gained, "verified": verified, "verify_note": verify_note}


@api("POST", "/api/hq/posts/<id>/like", auth=True)
def hq_toggle_like(ctx):
    user = ctx.user
    post_id = ctx.param_id()
    post = ctx.db.execute("SELECT * FROM hq_posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        raise ApiError(404, "post not found")
    if ctx.db.execute("SELECT 1 FROM hq_likes WHERE post_id = ? AND user_id = ?", (post_id, user["id"])).fetchone():
        ctx.db.execute("DELETE FROM hq_likes WHERE post_id = ? AND user_id = ?", (post_id, user["id"]))
        return {"liked": False}
    ctx.db.execute("INSERT INTO hq_likes (post_id, user_id) VALUES (?, ?)", (post_id, user["id"]))
    if post["user_id"] != user["id"]:
        award_xp(ctx.db, post["user_id"], "like_received", ref=f"{post_id}:{user['id']}")
        notify(ctx.db, post["user_id"], f"❤️ {user['display_name']} liked your post", "hq/feed", user["id"])
    return {"liked": True}


@api("POST", "/api/hq/github/sync", auth=True)
def hq_github_sync(ctx):
    user = ctx.user
    if GITHUB is None or not user["github_login"]:
        raise ApiError(400, "sign in with GitHub first")
    try:
        events = GITHUB.recent_push_events(user["github_login"])
    except GitHubError as error:
        raise ApiError(502, str(error)) from None
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
        gained += award_xp(ctx.db, user["id"], "github_push", ref=f"gh:{event.get('id')}")
    return {"pushes_found": fresh, "xp_gained": gained}


# ----- ladder ----------------------------------------------------------------- #

@api("GET", "/api/hq/ladder")
def hq_ladder(ctx):
    scope = ctx.q("scope", "global")
    period = ctx.q("period", "all")
    clauses = []
    params: list = []
    if scope == "country":
        user = require_user(ctx)
        if not user["country"]:
            raise ApiError(400, "set your country in HQ settings to see your country's ladder")
        clauses.append("u.country = ?")
        params.append(user["country"])
    elif scope == "friends":
        user = require_user(ctx)
        ids = friend_ids(ctx.db, user["id"]) + [user["id"]]
        clauses.append(f"u.id IN ({in_clause(ids)})")
        params.extend(ids)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    if period == "week":
        score_sql = "(SELECT COALESCE(SUM(amount), 0) FROM hq_xp_log x WHERE x.user_id = u.id AND x.created > ?)"
        params.insert(0, now() - 7 * 86400)
    else:
        score_sql = "u.xp"
    rows = ctx.db.execute(
        f"SELECT u.*, {score_sql} AS score FROM users u {where} ORDER BY score DESC, u.id ASC",
        params,
    ).fetchall()
    online = HUB.online_user_ids()
    viewer_id = ctx.user["id"] if ctx.user else None
    entries = []
    my_rank = None
    for index, row in enumerate(rows, start=1):
        if row["id"] == viewer_id:
            my_rank = index
        if index <= 100:
            entries.append(dict(hq_user(row), rank=index, score=row["score"], online=row["id"] in online))
    return {"entries": entries, "my_rank": my_rank, "total": len(rows)}


# ----- people & friends -------------------------------------------------------- #

@api("GET", "/api/hq/users", auth=True)
def hq_search_users(ctx):
    term = ctx.q("q").strip().lower().replace("%", "").replace("_", "")[:30]
    rows = ctx.db.execute(
        """SELECT * FROM users
           WHERE (lower(username) LIKE ? OR lower(display_name) LIKE ?) AND id != ?
           ORDER BY xp DESC LIMIT 20""",
        (f"%{term}%", f"%{term}%", ctx.user["id"]),
    ).fetchall()
    return {"users": [hq_user(row) for row in rows]}


@api("GET", "/api/hq/users/<username>")
def hq_user_profile(ctx):
    db = ctx.db
    target = user_by_name(db, ctx.params["username"])
    viewer = ctx.user
    relation = "anonymous"
    if viewer:
        relation = "self" if target["id"] == viewer["id"] else "none"
    if relation == "none":
        link = db.execute(
            """SELECT requester_id, status FROM hq_friendships
               WHERE (requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?)""",
            (viewer["id"], target["id"], target["id"], viewer["id"]),
        ).fetchone()
        if link and link["status"] == "accepted":
            relation = "friends"
        elif link:
            relation = "outgoing" if link["requester_id"] == viewer["id"] else "incoming"
    viewer_id = viewer["id"] if viewer else 0
    stats = {
        "global_rank": db.execute("SELECT COUNT(*) + 1 FROM users WHERE xp > ?", (target["xp"],)).fetchone()[0],
        "ships": db.execute(
            "SELECT COUNT(*) FROM hq_posts WHERE user_id = ? AND kind = 'ship'", (target["id"],)
        ).fetchone()[0],
        "friends": len(friend_ids(db, target["id"])),
        "sales": db.execute(
            """SELECT COUNT(*) FROM hq_orders o JOIN hq_products p ON p.id = o.product_id
               WHERE p.seller_id = ? AND o.status = 'paid'""",
            (target["id"],),
        ).fetchone()[0],
        "tasks_done": db.execute(
            """SELECT COUNT(*) FROM hq_commands c JOIN hq_devices d ON d.id = c.device_id
               WHERE d.user_id = ? AND c.status = 'done'""",
            (target["id"],),
        ).fetchone()[0],
    }
    return {
        "user": dict(hq_user(target), online=target["id"] in HUB.online_user_ids()),
        "relation": relation,
        "stats": stats,
        "posts": list_posts(db, viewer_id, author_id=target["id"], limit=20),
        "products": list_products(db, viewer_id, seller_id=target["id"]),
    }


@api("GET", "/api/hq/friends", auth=True)
def hq_friends(ctx):
    db = ctx.db
    user = ctx.user
    online = HUB.online_user_ids()
    ids = friend_ids(db, user["id"])
    accepted = [
        dict(hq_user(row), online=row["id"] in online)
        for row in db.execute(f"SELECT * FROM users WHERE id IN ({in_clause(ids)}) ORDER BY xp DESC", ids).fetchall()
    ]
    incoming = db.execute(
        """SELECT u.* FROM hq_friendships f JOIN users u ON u.id = f.requester_id
           WHERE f.addressee_id = ? AND f.status = 'pending'""",
        (user["id"],),
    ).fetchall()
    outgoing = db.execute(
        """SELECT u.* FROM hq_friendships f JOIN users u ON u.id = f.addressee_id
           WHERE f.requester_id = ? AND f.status = 'pending'""",
        (user["id"],),
    ).fetchall()
    return {
        "friends": accepted,
        "incoming": [hq_user(row) for row in incoming],
        "outgoing": [hq_user(row) for row in outgoing],
    }


def accept_friendship(db, requester, addressee) -> None:
    db.execute(
        "UPDATE hq_friendships SET status = 'accepted' WHERE requester_id = ? AND addressee_id = ?",
        (requester["id"], addressee["id"]),
    )
    pair = f"{min(requester['id'], addressee['id'])}:{max(requester['id'], addressee['id'])}"
    award_xp(db, requester["id"], "friend", ref=pair)
    award_xp(db, addressee["id"], "friend", ref=pair)
    notify(db, requester["id"], f"🤝 {addressee['display_name']} accepted your friend request", "hq/friends", addressee["id"])
    HUB.publish(requester["id"], {"type": "friends"})
    HUB.publish(addressee["id"], {"type": "friends"})


@api("POST", "/api/hq/friends/<action>", auth=True)
def hq_friend_action(ctx):
    action = ctx.params["action"]
    user = ctx.user
    db = ctx.db
    other = user_by_name(db, text_field(ctx.body, "username", 40))
    if action == "request":
        if other["id"] == user["id"]:
            raise ApiError(400, "you can't friend yourself")
        reverse = db.execute(
            "SELECT status FROM hq_friendships WHERE requester_id = ? AND addressee_id = ?",
            (other["id"], user["id"]),
        ).fetchone()
        if reverse and reverse["status"] == "pending":
            accept_friendship(db, other, user)
            return {"status": "accepted"}
        if reverse:
            return {"status": reverse["status"]}
        existing = db.execute(
            "SELECT status FROM hq_friendships WHERE requester_id = ? AND addressee_id = ?",
            (user["id"], other["id"]),
        ).fetchone()
        if existing:
            return {"status": existing["status"]}
        db.execute(
            "INSERT INTO hq_friendships (requester_id, addressee_id, status, created) VALUES (?, ?, 'pending', ?)",
            (user["id"], other["id"], now()),
        )
        notify(db, other["id"], f"👋 {user['display_name']} sent you a friend request", "hq/friends", user["id"])
        HUB.publish(other["id"], {"type": "friends"})
        return {"status": "pending"}
    if action == "accept":
        pending = db.execute(
            "SELECT 1 FROM hq_friendships WHERE requester_id = ? AND addressee_id = ? AND status = 'pending'",
            (other["id"], user["id"]),
        ).fetchone()
        if not pending:
            raise ApiError(404, "no pending request from that user")
        accept_friendship(db, other, user)
        return {"status": "accepted"}
    if action == "remove":
        db.execute(
            """DELETE FROM hq_friendships WHERE (requester_id = ? AND addressee_id = ?)
               OR (requester_id = ? AND addressee_id = ?)""",
            (user["id"], other["id"], other["id"], user["id"]),
        )
        HUB.publish(other["id"], {"type": "friends"})
        return {"ok": True}
    raise ApiError(404, "Not found")


# ----- chat -------------------------------------------------------------------- #

def resolve_channel(ctx, name: str):
    """'world' or 'dm:<username>' -> storage key and the DM partner."""
    user = ctx.user
    if name == "world":
        return "world", None
    if name.startswith("dm:"):
        other = user_by_name(ctx.db, name[3:])
        if not are_friends(ctx.db, user["id"], other["id"]):
            raise ApiError(403, "you can only DM friends")
        low, high = sorted((user["id"], other["id"]))
        return f"dm:{low}:{high}", other
    raise ApiError(404, "unknown channel")


def message_json(row) -> dict:
    return {
        "id": row["id"],
        "sender": author_json(row),
        "body": row["body"],
        "created": row["created"],
    }


@api("GET", "/api/hq/chat/<channel>", auth=True)
def hq_chat_history(ctx):
    key, _ = resolve_channel(ctx, ctx.params["channel"])
    try:
        after = int(ctx.q("after", "0") or 0)
    except ValueError:
        after = 0
    rows = ctx.db.execute(
        """SELECT * FROM (
               SELECT m.*, u.username, u.display_name, u.avatar_hue, u.avatar_url FROM hq_messages m
               JOIN users u ON u.id = m.sender_id
               WHERE m.channel = ? AND m.id > ? ORDER BY m.id DESC LIMIT 100
           ) AS recent ORDER BY id ASC""",
        (key, after),
    ).fetchall()
    return {"messages": [message_json(row) for row in rows]}


@api("POST", "/api/hq/chat/<channel>", auth=True)
def hq_chat_send(ctx):
    user = ctx.user
    key, other = resolve_channel(ctx, ctx.params["channel"])
    body = text_field(ctx.body, "body", 2000)
    with CHAT_RATE_LOCK:
        if time.time() - CHAT_RATE.get(user["id"], 0) < 0.7:
            raise ApiError(429, "slow down a little")
        CHAT_RATE[user["id"]] = time.time()
    message_id = ctx.db.insert(
        "INSERT INTO hq_messages (channel, sender_id, body, created) VALUES (?, ?, ?, ?)",
        (key, user["id"], body, now()),
    )
    message = {
        "id": message_id,
        "sender": author_json(user),
        "body": body,
        "created": now(),
    }
    if other is None:
        HUB.broadcast({"type": "chat", "channel": "world", "message": message})
    else:
        HUB.publish(other["id"], {"type": "chat", "channel": f"dm:{user['username']}", "message": message})
        HUB.publish(user["id"], {"type": "chat", "channel": f"dm:{other['username']}", "message": message})
        notify(ctx.db, other["id"], f"💬 {user['display_name']}: {body[:100]}", f"hq/chat/dm:{user['username']}", user["id"])
    return {"message": message}


# ----- devices & agents ---------------------------------------------------------- #

def device_json(row) -> dict:
    try:
        info = json.loads(row["info"] or "{}")
    except ValueError:
        info = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "online": now() - (row["last_seen"] or 0) < DEVICE_ONLINE_SECONDS,
        "last_seen": row["last_seen"],
        "info": info,
    }


def command_json(row) -> dict:
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


def owned_device(ctx):
    row = ctx.db.execute(
        "SELECT * FROM hq_devices WHERE id = ? AND user_id = ?", (ctx.param_id(), ctx.user["id"])
    ).fetchone()
    if not row:
        raise ApiError(404, "device not found")
    return row


def calling_device(ctx):
    key = ctx.headers.get("X-Device-Key", "")
    row = ctx.db.execute("SELECT * FROM hq_devices WHERE key_hash = ?", (sha256(key),)).fetchone() if key else None
    if not row:
        raise ApiError(401, "unknown device key")
    return row


def require_command_pin(ctx, pin: str) -> None:
    """Agent tasks and shell commands need a separate PIN, so a stolen login alone can't run code."""
    user = ctx.user
    if not user["command_pin_hash"]:
        raise ApiError(403, "set a command PIN first (HQ → Settings)")
    key = f"pin:{user['id']}"
    if LIMITER.blocked(key, *PIN_LIMIT):
        raise ApiError(429, "too many wrong PINs - remote commands locked for 15 minutes")
    candidate, _ = pin_hash(pin, user["command_pin_salt"])
    if not hmac.compare_digest(candidate, user["command_pin_hash"]):
        LIMITER.hit(key, PIN_LIMIT[1])
        raise ApiError(403, "wrong command PIN")
    LIMITER.reset(key)


@api("GET", "/api/hq/devices", auth=True)
def hq_devices(ctx):
    rows = ctx.db.execute("SELECT * FROM hq_devices WHERE user_id = ? ORDER BY id", (ctx.user["id"],)).fetchall()
    return {"devices": [device_json(row) for row in rows]}


@api("POST", "/api/hq/devices", auth=True)
def hq_create_device(ctx):
    name = text_field(ctx.body, "name", 40)
    count = ctx.db.execute("SELECT COUNT(*) FROM hq_devices WHERE user_id = ?", (ctx.user["id"],)).fetchone()[0]
    if count >= 20:
        raise ApiError(400, "device limit reached (20)")
    key = "shd_" + secrets.token_urlsafe(24)
    device_id = ctx.db.insert(
        "INSERT INTO hq_devices (user_id, name, key_hash, created) VALUES (?, ?, ?, ?)",
        (ctx.user["id"], name, sha256(key), now()),
    )
    return {"id": device_id, "key": key}


@api("POST", "/api/hq/devices/<id>/delete", auth=True)
def hq_delete_device(ctx):
    device = owned_device(ctx)
    ctx.db.execute("DELETE FROM hq_devices WHERE id = ?", (device["id"],))
    return {"ok": True}


@api("GET", "/api/hq/devices/<id>/commands", auth=True)
def hq_device_commands(ctx):
    device = owned_device(ctx)
    rows = ctx.db.execute(
        "SELECT * FROM hq_commands WHERE device_id = ? ORDER BY id DESC LIMIT 50", (device["id"],)
    ).fetchall()
    return {"commands": [command_json(row) for row in rows]}


@api("POST", "/api/hq/devices/<id>/commands", auth=True)
def hq_send_command(ctx):
    device = owned_device(ctx)
    kind = ctx.body.get("kind", "")
    if kind not in COMMAND_KINDS:
        raise ApiError(400, "unknown command kind")
    payload = text_field(ctx.body, "payload", 4000, required=kind in RISKY_COMMANDS)
    if kind in RISKY_COMMANDS:
        require_command_pin(ctx, str(ctx.body.get("pin", "")))
    command_id = ctx.db.insert(
        "INSERT INTO hq_commands (device_id, kind, payload, status, created, updated) VALUES (?, ?, ?, 'queued', ?, ?)",
        (device["id"], kind, payload, now(), now()),
    )
    row = ctx.db.execute("SELECT * FROM hq_commands WHERE id = ?", (command_id,)).fetchone()
    HUB.publish(device["user_id"], {"type": "command", "command": command_json(row)})
    if kind in RISKY_COMMANDS:
        notify(
            ctx.db,
            device["user_id"],
            f"🛡️ {kind} sent to {device['name']}. Not you? HQ → Settings → sign out everywhere",
            "hq/agents",
        )
    return {"command": command_json(row)}


@api("POST", "/api/hq/agent/heartbeat")
def hq_agent_heartbeat(ctx):
    device = calling_device(ctx)
    info = ctx.body.get("info", {})
    if not isinstance(info, dict):
        raise ApiError(400, "info must be an object")
    ctx.db.execute(
        "UPDATE hq_devices SET last_seen = ?, info = ? WHERE id = ?", (now(), json.dumps(info)[:20000], device["id"])
    )
    fresh = ctx.db.execute("SELECT * FROM hq_devices WHERE id = ?", (device["id"],)).fetchone()
    HUB.publish(device["user_id"], {"type": "device", "device": device_json(fresh)})
    return {"ok": True, "device": device["name"]}


@api("GET", "/api/hq/agent/poll")
def hq_agent_poll(ctx):
    device = calling_device(ctx)
    db = ctx.db
    db.execute("UPDATE hq_devices SET last_seen = ? WHERE id = ?", (now(), device["id"]))
    rows = db.execute(
        "SELECT * FROM hq_commands WHERE device_id = ? AND status = 'queued' ORDER BY id LIMIT 5", (device["id"],)
    ).fetchall()
    claimed = []
    for row in rows:
        db.execute("UPDATE hq_commands SET status = 'running', updated = ? WHERE id = ?", (now(), row["id"]))
        updated = dict(command_json(row), status="running")
        claimed.append(updated)
        HUB.publish(device["user_id"], {"type": "command", "command": updated})
    return {"commands": claimed, "server_time": now()}


@api("POST", "/api/hq/agent/result")
def hq_agent_result(ctx):
    device = calling_device(ctx)
    try:
        command_id = int(ctx.body.get("id", 0))
    except (TypeError, ValueError):
        raise ApiError(400, "invalid command id") from None
    status = ctx.body.get("status")
    if status not in {"done", "failed"}:
        raise ApiError(400, "status must be done or failed")
    result = str(ctx.body.get("result", ""))[-20000:]
    row = ctx.db.execute(
        "SELECT * FROM hq_commands WHERE id = ? AND device_id = ?", (command_id, device["id"])
    ).fetchone()
    if not row:
        raise ApiError(404, "command not found")
    ctx.db.execute(
        "UPDATE hq_commands SET status = ?, result = ?, updated = ? WHERE id = ?", (status, result, now(), command_id)
    )
    if status == "done" and row["kind"] == "agent_task":
        award_xp(ctx.db, device["user_id"], "task_done", ref=f"cmd:{command_id}")
    fresh = ctx.db.execute("SELECT * FROM hq_commands WHERE id = ?", (command_id,)).fetchone()
    HUB.publish(device["user_id"], {"type": "command", "command": command_json(fresh)})
    mark = "✅" if status == "done" else "❌"
    notify(ctx.db, device["user_id"], f"{mark} {device['name']}: {row['kind']} {status}", "hq/agents")
    return {"ok": True}


# ----- marketplace ----------------------------------------------------------------- #

def list_products(db, viewer_id: int, seller_id=None, kind: str = ""):
    clauses = []
    params: list = [viewer_id]
    if seller_id is not None:
        clauses.append("p.seller_id = ?")
        params.append(seller_id)
    if kind:
        clauses.append("p.kind = ?")
        params.append(kind)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.execute(
        f"""SELECT p.*, u.username, u.display_name, u.avatar_hue, u.avatar_url, u.xp, u.payouts_enabled,
                   (SELECT COUNT(*) FROM hq_orders o WHERE o.product_id = p.id AND o.status = 'paid') AS sales,
                   (SELECT COUNT(*) FROM hq_orders o WHERE o.product_id = p.id AND o.buyer_id = ?
                      AND o.status = 'paid') AS owned
            FROM hq_products p JOIN users u ON u.id = p.seller_id
            {where} ORDER BY sales DESC, p.id DESC LIMIT 100""",
        params,
    ).fetchall()
    products = []
    for row in rows:
        mine = row["seller_id"] == viewer_id
        owned = bool(row["owned"])
        products.append({
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "description": row["description"],
            "price_cents": row["price_cents"],
            "seller": dict(author_json(row), tier=tier_for(row["xp"] or 0)[0][1]),
            "seller_can_sell": bool(row["payouts_enabled"]) or STRIPE is None or row["price_cents"] == 0,
            "sales": row["sales"],
            "owned": owned,
            "mine": mine,
            "delivery_link": row["delivery_link"] if (owned or mine) else "",
            "created": row["created"],
        })
    return products


def platform_fee(price_cents: int) -> int:
    return int(round(price_cents * PLATFORM_FEE_PERCENT / 100))


def complete_order(db, order) -> bool:
    """Mark an order paid exactly once, then reward the seller and notify both sides."""
    updated = db.execute(
        "UPDATE hq_orders SET status = 'paid' WHERE id = ? AND status != 'paid'", (order["id"],)
    ).rowcount
    if not updated:
        return False
    product = db.execute("SELECT * FROM hq_products WHERE id = ?", (order["product_id"],)).fetchone()
    buyer = db.execute("SELECT display_name FROM users WHERE id = ?", (order["buyer_id"],)).fetchone()
    award_xp(db, product["seller_id"], "sale", ref=f"order:{order['id']}")
    notify(db, product["seller_id"], f"💰 {buyer['display_name']} bought '{product['title']}'", "hq/market", order["buyer_id"])
    notify(db, order["buyer_id"], f"📦 Purchase confirmed: {product['title']}", "hq/market")
    return True


@api("GET", "/api/hq/products")
def hq_products(ctx):
    kind = ctx.q("kind")
    viewer = ctx.user["id"] if ctx.user else 0
    return {"products": list_products(ctx.db, viewer, kind=kind if kind in PRODUCT_KINDS else "")}


@api("POST", "/api/hq/products", auth=True)
def hq_create_product(ctx):
    user = ctx.user
    kind = ctx.body.get("kind", "other")
    if kind not in PRODUCT_KINDS:
        raise ApiError(400, "unknown product kind")
    title = text_field(ctx.body, "title", 80)
    description = text_field(ctx.body, "description", 2000)
    delivery_link = safe_link(text_field(ctx.body, "delivery_link", 500, required=False))
    try:
        price_cents = int(round(float(ctx.body.get("price", 0)) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "price must be a number") from None
    if not 0 <= price_cents <= 1_000_000:
        raise ApiError(400, "price must be between 0 and 10000")
    if 0 < price_cents < 50 and STRIPE is not None:
        raise ApiError(400, "paid products must cost at least 0.50")
    if price_cents and STRIPE is not None and not user["payouts_enabled"]:
        raise ApiError(400, "connect Stripe payouts first (HQ → Market → Get paid) to sell paid products")
    product_id = ctx.db.insert(
        """INSERT INTO hq_products (seller_id, kind, title, description, price_cents, delivery_link, created)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user["id"], kind, title, description, price_cents, delivery_link, now()),
    )
    return {"id": product_id}


@api("POST", "/api/hq/products/<id>/buy", auth=True)
def hq_buy_product(ctx):
    user = ctx.user
    db = ctx.db
    product_id = ctx.param_id()
    product = db.execute("SELECT * FROM hq_products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        raise ApiError(404, "product not found")
    if product["seller_id"] == user["id"]:
        raise ApiError(400, "you can't buy your own product")
    if db.execute(
        "SELECT 1 FROM hq_orders WHERE product_id = ? AND buyer_id = ? AND status = 'paid'", (product_id, user["id"])
    ).fetchone():
        raise ApiError(409, "you already own this")
    price = product["price_cents"]
    if price == 0 or STRIPE is None:
        # Free products, or demo mode when no Stripe key is configured.
        order_id = db.insert(
            "INSERT INTO hq_orders (product_id, buyer_id, price_cents, status, created) VALUES (?, ?, ?, 'pending', ?)",
            (product_id, user["id"], price, now()),
        )
        order = db.execute("SELECT * FROM hq_orders WHERE id = ?", (order_id,)).fetchone()
        complete_order(db, order)
        return {"status": "paid", "demo": price > 0, "order_id": order_id, "delivery_link": product["delivery_link"]}

    seller = db.execute("SELECT * FROM users WHERE id = ?", (product["seller_id"],)).fetchone()
    if not (seller["payouts_enabled"] and seller["stripe_account_id"]):
        raise ApiError(400, "this seller hasn't finished Stripe payout setup yet")
    fee = platform_fee(price)
    base = ctx.base_url
    try:
        session = STRIPE.create_checkout_session(
            title=product["title"],
            amount_cents=price,
            currency=CURRENCY,
            fee_cents=fee,
            destination=seller["stripe_account_id"],
            success_url=f"{base}/?checkout={{CHECKOUT_SESSION_ID}}#/hq/market",
            cancel_url=f"{base}/#/hq/market",
            metadata={"product_id": str(product["id"]), "buyer_id": str(user["id"])},
        )
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}") from None
    db.execute(
        "DELETE FROM hq_orders WHERE product_id = ? AND buyer_id = ? AND status = 'pending'", (product_id, user["id"])
    )
    db.execute(
        """INSERT INTO hq_orders (product_id, buyer_id, price_cents, status, stripe_session_id, fee_cents, created)
           VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
        (product_id, user["id"], price, session["id"], fee, now()),
    )
    return {"status": "pending", "checkout_url": session["url"]}


@api("GET", "/api/hq/checkout/confirm", auth=True)
def hq_checkout_confirm(ctx):
    """Fallback for when webhooks aren't reachable (e.g. local dev): ask Stripe directly."""
    session_id = ctx.q("session_id")
    order = ctx.db.execute(
        "SELECT * FROM hq_orders WHERE stripe_session_id = ? AND buyer_id = ?", (session_id, ctx.user["id"])
    ).fetchone()
    if not order or STRIPE is None:
        raise ApiError(404, "order not found")
    if order["status"] != "paid":
        try:
            session = STRIPE.retrieve_checkout_session(session_id)
        except StripeError as error:
            raise ApiError(502, f"payment provider error: {error}") from None
        if session.get("payment_status") == "paid":
            complete_order(ctx.db, order)
    fresh = ctx.db.execute(
        """SELECT o.status, p.delivery_link, p.title FROM hq_orders o
           JOIN hq_products p ON p.id = o.product_id WHERE o.id = ?""",
        (order["id"],),
    ).fetchone()
    paid = fresh["status"] == "paid"
    return {"status": fresh["status"], "title": fresh["title"], "delivery_link": fresh["delivery_link"] if paid else ""}


@api("POST", "/api/hq/stripe/webhook", raw="webhook")
def hq_stripe_webhook(ctx):
    if STRIPE is None or not STRIPE_WEBHOOK_SECRET:
        raise ApiError(404, "webhooks not configured")
    try:
        event = verify_webhook(ctx.raw or b"", ctx.headers.get("Stripe-Signature", ""), STRIPE_WEBHOOK_SECRET)
    except (StripeError, ValueError) as error:
        raise ApiError(400, str(error)) from None
    kind = event.get("type", "")
    data = event.get("data", {}).get("object", {})
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if data.get("payment_status") == "paid":
            order = ctx.db.execute(
                "SELECT * FROM hq_orders WHERE stripe_session_id = ?", (data.get("id", ""),)
            ).fetchone()
            if order:
                complete_order(ctx.db, order)
    elif kind == "account.updated":
        ready = bool(data.get("charges_enabled") and data.get("details_submitted"))
        ctx.db.execute(
            "UPDATE users SET payouts_enabled = ? WHERE stripe_account_id = ?", (int(ready), data.get("id", ""))
        )
    return {"received": True}


@api("POST", "/api/hq/payouts/connect", auth=True)
def hq_payouts_connect(ctx):
    user = ctx.user
    if STRIPE is None:
        raise ApiError(400, "payments run in demo mode - add STRIPE_SECRET_KEY to enable payouts")
    account_id = user["stripe_account_id"]
    base = ctx.base_url
    try:
        if not account_id:
            account = STRIPE.create_express_account({"shiphub_user_id": str(user["id"])})
            account_id = account["id"]
            ctx.db.execute("UPDATE users SET stripe_account_id = ? WHERE id = ?", (account_id, user["id"]))
        link = STRIPE.create_onboarding_link(
            account_id,
            refresh_url=f"{base}/?payouts=refresh#/hq/market",
            return_url=f"{base}/?payouts=done#/hq/market",
        )
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}") from None
    return {"url": link["url"]}


@api("POST", "/api/hq/payouts/refresh", auth=True)
def hq_payouts_refresh(ctx):
    user = ctx.user
    if STRIPE is None or not user["stripe_account_id"]:
        return {"payouts_enabled": bool(user["payouts_enabled"])}
    try:
        account = STRIPE.retrieve_account(user["stripe_account_id"])
    except StripeError as error:
        raise ApiError(502, f"payment provider error: {error}") from None
    ready = bool(account.get("charges_enabled") and account.get("details_submitted"))
    ctx.db.execute("UPDATE users SET payouts_enabled = ? WHERE id = ?", (int(ready), user["id"]))
    return {"payouts_enabled": ready}


@api("GET", "/api/hq/orders", auth=True)
def hq_orders(ctx):
    user_id = ctx.user["id"]
    purchases = ctx.db.execute(
        """SELECT o.id, o.price_cents, o.created, p.title, p.delivery_link, u.username AS seller
           FROM hq_orders o JOIN hq_products p ON p.id = o.product_id JOIN users u ON u.id = p.seller_id
           WHERE o.buyer_id = ? AND o.status = 'paid' ORDER BY o.id DESC""",
        (user_id,),
    ).fetchall()
    sales = ctx.db.execute(
        """SELECT o.id, o.price_cents, o.fee_cents, o.created, p.title, u.username AS buyer
           FROM hq_orders o JOIN hq_products p ON p.id = o.product_id JOIN users u ON u.id = o.buyer_id
           WHERE p.seller_id = ? AND o.status = 'paid' ORDER BY o.id DESC""",
        (user_id,),
    ).fetchall()
    return {
        "purchases": [dict(row) for row in purchases],
        "sales": [dict(row) for row in sales],
        "revenue_cents": sum(row["price_cents"] for row in sales),
        "net_cents": sum(row["price_cents"] - row["fee_cents"] for row in sales),
    }


# ----- push --------------------------------------------------------------------- #

@api("POST", "/api/hq/push/subscribe", auth=True)
def hq_push_subscribe(ctx):
    endpoint = text_field(ctx.body, "endpoint", 1000)
    if not webpush.endpoint_allowed(endpoint, PUSH_EXTRA_HOSTS):
        raise ApiError(400, "unsupported push service")
    ctx.db.execute(
        """INSERT INTO hq_push_subscriptions (user_id, endpoint, created) VALUES (?, ?, ?)
           ON CONFLICT (endpoint) DO UPDATE SET user_id = excluded.user_id""",
        (ctx.user["id"], endpoint, now()),
    )
    return {"ok": True}


@api("POST", "/api/hq/push/unsubscribe", auth=True)
def hq_push_unsubscribe(ctx):
    ctx.db.execute(
        "DELETE FROM hq_push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (ctx.user["id"], str(ctx.body.get("endpoint", ""))),
    )
    return {"ok": True}


@api("POST", "/api/hq/push/test", auth=True)
def hq_push_test(ctx):
    notify(ctx.db, ctx.user["id"], "🔔 Test notification - push is working!", "hq")
    return {"ok": True}


# ----- account security (PIN, password, sessions) ------------------------------------ #

def current_session(ctx):
    token = ctx.session_token
    return ctx.db.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone() if token else None


def session_is_fresh(ctx) -> bool:
    session = current_session(ctx)
    return bool(session) and time.time() - (session["created_at"] or 0) < FRESH_SESSION_SECONDS


@api("POST", "/api/account/pin", auth=True)
def account_set_pin(ctx):
    user = ctx.user
    pin = str(ctx.body.get("pin", ""))
    if not re.match(r"^[0-9]{6,12}$", pin):
        raise ApiError(400, "PIN must be 6-12 digits")
    if user["command_pin_hash"] and not session_is_fresh(ctx):
        # Forgot it? Log out and back in: a fresh login can reset the PIN for 10 minutes.
        require_command_pin(ctx, str(ctx.body.get("current_pin", "")))
    digest, salt = pin_hash(pin)
    ctx.db.execute(
        "UPDATE users SET command_pin_hash = ?, command_pin_salt = ? WHERE id = ?", (digest, salt, user["id"])
    )
    notify(ctx.db, user["id"], "🔐 Your command PIN was changed", "hq/settings")
    return {"ok": True}


@api("GET", "/api/account/sessions", auth=True)
def account_sessions(ctx):
    rows = ctx.db.execute(
        "SELECT token, created_at, expires_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
        (ctx.user["id"],),
    ).fetchall()
    current = ctx.session_token
    return {"sessions": [
        {
            "id": sha256(row["token"])[:16],
            "created": row["created_at"] or None,
            "expires": row["expires_at"],
            "current": row["token"] == current,
        }
        for row in rows
    ]}


@api("POST", "/api/account/sessions/revoke", auth=True)
def account_revoke_sessions(ctx):
    current = ctx.session_token
    rows = ctx.db.execute("SELECT token FROM sessions WHERE user_id = ?", (ctx.user["id"],)).fetchall()
    wanted = str(ctx.body.get("id", ""))
    everyone_else = bool(ctx.body.get("all_others"))
    if not everyone_else and len(wanted) != 16:
        raise ApiError(400, "invalid session id")
    count = 0
    for row in rows:
        token = row["token"]
        if token == current:
            continue
        if everyone_else or sha256(token)[:16] == wanted:
            ctx.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            count += 1
    return {"signed_out": count}


# --------------------------------------------------------------------------- #
# Demo data (seeded together with shiphub's demo users)
# --------------------------------------------------------------------------- #

DEMO_PROFILES = {
    # username: (country, stack, xp)
    "demo": ("US", "Claude Code, Next.js", 120),
    "devon": ("US", "Next.js, Supabase, Claude Code", 3200),
    "sol": ("ID", "Flutter, Firebase, Codex", 1800),
    "nina": ("BR", "Cursor, Tailwind, Stripe", 5400),
    "maya": ("DE", "Python, FastAPI, Gemini CLI", 2100),
    "ari": ("JP", "Svelte, Bun, Aider", 950),
    "omar": ("NG", "Python, Ollama, Rust", 420),
    "kai": ("CN", "Rust, Ollama, Aider", 1300),
}

DEMO_POSTS = [
    ("nina", "ship", "Shipped a landing-page kit: 12 sections, generated + hand-polished. 4 hours start to Stripe.", "https://example.com/kit"),
    ("devon", "tip", "Give your coding agent a TASKS.md and make it tick boxes. Way fewer 'creative' detours.", ""),
    ("sol", "news", "New open-weight coding models dropped this week - benchmarks look close to frontier for refactors.", ""),
    ("kai", "tip", "Run 2 agents in separate git worktrees so they never fight over the same files.", ""),
    ("omar", "ship", "My agent now reconciles invoices for a bakery in Lagos every night. First paying user!", ""),
    ("devon", "ship", "Habit tracker built 100% by agents in 48h. Ideas from shiphub, shipped from HQ.", "https://example.com/habits"),
]

DEMO_PRODUCTS = [
    ("nina", "template", "SaaS Landing Kit", "12 conversion-tested sections, Tailwind + Next.js.", 2900, "https://example.com/dl/kit"),
    ("devon", "prompt", "Claude Code Power Prompts", "40 battle-tested prompts for refactors, tests and migrations.", 900, "https://example.com/dl/prompts"),
    ("kai", "mcp", "Local Docs MCP Server", "Give any agent offline search over your docs folder.", 0, "https://example.com/dl/mcp"),
    ("sol", "agent", "Nightly Bug-Triage Agent", "Agent config that labels and reproduces new GitHub issues.", 1500, "https://example.com/dl/triage"),
]

DEMO_CHAT = [
    ("sol", "Selamat pagi from Jakarta! Who's shipping today?"),
    ("nina", "Boa tarde! Finishing a template, agents running in the background"),
    ("kai", "My local model just passed all tests on the first try. Rare day."),
]


def seed_demo(db, user_ids: dict[str, int]) -> None:
    stamp = now()
    for username, (country, stack, xp) in DEMO_PROFILES.items():
        if username in user_ids:
            db.execute(
                "UPDATE users SET country = ?, stack = ?, xp = ? WHERE id = ?",
                (country, stack, xp, user_ids[username]),
            )
            db.execute(
                "INSERT INTO hq_xp_log (user_id, amount, reason, ref, created) VALUES (?, ?, 'ship', 'seed', ?)",
                (user_ids[username], xp // 4, stamp - 3600),
            )
    for offset, (author, kind, body, link) in enumerate(DEMO_POSTS):
        if author in user_ids:
            db.execute(
                "INSERT INTO hq_posts (user_id, kind, body, link, created) VALUES (?, ?, ?, ?, ?)",
                (user_ids[author], kind, body, link, stamp - 3600 * (len(DEMO_POSTS) - offset)),
            )
    for a, b in [("devon", "sol"), ("devon", "nina"), ("sol", "kai"), ("nina", "omar"), ("demo", "devon")]:
        if a in user_ids and b in user_ids:
            db.execute(
                "INSERT INTO hq_friendships (requester_id, addressee_id, status, created) VALUES (?, ?, 'accepted', ?)",
                (user_ids[a], user_ids[b], stamp),
            )
    if "kai" in user_ids and "demo" in user_ids:
        db.execute(
            "INSERT INTO hq_friendships (requester_id, addressee_id, status, created) VALUES (?, ?, 'pending', ?)",
            (user_ids["kai"], user_ids["demo"], stamp),
        )
    for seller, kind, title, description, price, link in DEMO_PRODUCTS:
        if seller in user_ids:
            db.execute(
                """INSERT INTO hq_products (seller_id, kind, title, description, price_cents, delivery_link, created)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_ids[seller], kind, title, description, price, link, stamp),
            )
    for sender, body in DEMO_CHAT:
        if sender in user_ids:
            db.execute(
                "INSERT INTO hq_messages (channel, sender_id, body, created) VALUES ('world', ?, ?, ?)",
                (user_ids[sender], body, stamp - 600),
            )
