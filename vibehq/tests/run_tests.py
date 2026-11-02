#!/usr/bin/env python3
"""
End-to-end tests for vibeHQ. Starts the real server against local fakes of
Stripe, GitHub, a Web Push service and ntfy, then exercises every flow.

Run:  python tests/run_tests.py
(If the `cryptography` package is installed, VAPID signatures are also
cross-checked against it; otherwise the built-in verifier is used.)
"""
import base64
import hashlib
import hmac
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
import webpush  # noqa: E402

DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
NO_REDIRECT = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None})(),
)
WEBHOOK_SECRET = "whsec_test_secret"
RESULTS = []


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---------------------------------------------------------------- fake external services

class FakeState:
    sessions = {}
    session_counter = 0
    pushes = []
    ntfy = []
    accounts_created = 0


def iso(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


class FakeServices(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/v1/accounts/acct_test123":
            return self.reply(200, {"id": "acct_test123", "charges_enabled": True, "details_submitted": True})
        if path.startswith("/v1/checkout/sessions/"):
            session = FakeState.sessions.get(path.rsplit("/", 1)[1])
            return self.reply(200 if session else 404, session or {"error": {"message": "no such session"}})
        if path == "/user":
            return self.reply(200, {"id": 4242, "login": "octovibe", "avatar_url": "https://avatars.test/o.png", "bio": "ships daily"})
        if path == "/repos/octovibe/shipit":
            return self.reply(200, {"owner": {"login": "octovibe"}, "pushed_at": iso(3600), "fork": False})
        if path == "/repos/someone/else":
            return self.reply(200, {"owner": {"login": "someone"}, "pushed_at": iso(3600), "fork": False})
        if path == "/repos/someone/else/contributors":
            return self.reply(200, [{"login": "someone"}])
        if path == "/repos/octovibe/stale":
            return self.reply(200, {"owner": {"login": "octovibe"}, "pushed_at": iso(90 * 86400), "fork": False})
        if path == "/users/octovibe/events/public":
            return self.reply(200, [
                {"id": "e1", "type": "PushEvent", "created_at": iso(3600)},
                {"id": "e2", "type": "PushEvent", "created_at": iso(7200)},
                {"id": "e3", "type": "WatchEvent", "created_at": iso(7200)},
                {"id": "e4", "type": "PushEvent", "created_at": iso(20 * 86400)},
                {"id": "e5", "type": "PushEvent", "created_at": iso(86400)},
            ])
        return self.reply(404, {"message": "Not Found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        raw = self.body()
        form = dict(urllib.parse.parse_qsl(raw.decode(errors="replace")))
        if path == "/v1/accounts":
            FakeState.accounts_created += 1
            return self.reply(200, {"id": "acct_test123"})
        if path == "/v1/account_links":
            return self.reply(200, {"url": "https://connect.stripe.test/onboard"})
        if path == "/v1/checkout/sessions":
            FakeState.session_counter += 1
            session_id = f"cs_test_{FakeState.session_counter}"
            FakeState.sessions[session_id] = {"id": session_id, "payment_status": "unpaid", "params": form}
            return self.reply(200, {"id": session_id, "url": f"https://checkout.stripe.test/{session_id}"})
        if path == "/login/oauth/access_token":
            return self.reply(200, {"access_token": "gho_fake"} if form.get("code") == "good" else {"error_description": "bad code"})
        if path.startswith("/push/"):
            FakeState.pushes.append({"path": path, "auth": self.headers.get("Authorization", ""), "ttl": self.headers.get("TTL")})
            return self.reply(410 if path.endswith("/gone") else 201, {})
        if path.startswith("/ntfy/"):
            FakeState.ntfy.append({"topic": path[6:], "body": raw.decode(), "click": self.headers.get("Click")})
            return self.reply(200, {})
        return self.reply(404, {})


# ---------------------------------------------------------------- helpers

class App:
    def __init__(self, base):
        self.base = base

    def call(self, path, body=None, token=None, headers=None, raw=None):
        request_headers = {"Content-Type": "application/json"}
        if token:
            request_headers["Authorization"] = "Bearer " + token
        request_headers.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers,
                                         method="POST" if data is not None else "GET")
        try:
            with DIRECT.open(request, timeout=15) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def redirect(self, path):
        try:
            NO_REDIRECT.open(self.base + path, timeout=15)
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Location", "")
        return 200, ""

    def login(self, username):
        return self.call("/api/login", {"username": username, "password": "demo1234"})[1]["token"]


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))


def stripe_signature(payload, secret=WEBHOOK_SECRET, timestamp=None):
    timestamp = str(int(timestamp or time.time()))
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_vapid(auth_header, expected_audience, server_public_key):
    """Check a 'vapid t=JWT, k=KEY' header the way a push service would."""
    parts = dict(part.strip().split("=", 1) for part in auth_header[len("vapid "):].split(","))
    header_b64, claims_b64, signature_b64 = parts["t"].split(".")
    claims = json.loads(webpush.b64url_decode(claims_b64))
    public_key = webpush.b64url_decode(parts["k"])
    signature = webpush.b64url_decode(signature_b64)
    signing_input = f"{header_b64}.{claims_b64}".encode()
    ok = (
        public_key == server_public_key
        and claims["aud"] == expected_audience
        and claims["exp"] > time.time()
        and webpush.verify(public_key, signing_input, signature)
    )
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key)
        der = utils.encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
        key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
        library = "cryptography"
    except ImportError:
        library = "builtin"
    return ok, library


def wait_for(predicate, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if predicate():
                return True
        except OSError:
            pass  # e.g. server still starting up
        time.sleep(0.2)
    return False


# ---------------------------------------------------------------- the tests

def run(app, fake_base):
    alice = app.login("alice")
    chen = app.login("chen")
    dara = app.login("dara")

    # --- config
    _, config = app.call("/api/config")
    vapid_public = webpush.b64url_decode(config["vapid_public_key"])
    check("config: stripe + github + vapid key", config["payments"] == "stripe" and config["github"] and len(vapid_public) == 65)

    # --- GitHub OAuth login
    status, location = app.redirect("/api/auth/github/start")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("state", [""])[0]
    check("github: start redirects to authorize", status == 302 and "/login/oauth/authorize" in location and state)
    status, location = app.redirect(f"/api/auth/github/callback?code=good&state={state}")
    octo = location.split("#auth=", 1)[1] if "#auth=" in location else ""
    check("github: callback signs in", status == 302 and octo)
    _, me = app.call("/api/me", token=octo)
    check("github: account created from profile", me["user"]["username"] == "octovibe" and me["user"]["github_login"] == "octovibe")
    status, location = app.redirect(f"/api/auth/github/callback?code=good&state={state}")
    check("github: state can't be replayed", "autherror" in location)
    status, location = app.redirect("/api/auth/github/start")
    state2 = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["state"][0]
    _, location = app.redirect(f"/api/auth/github/callback?code=good&state={state2}")
    again = location.split("#auth=", 1)[1]
    _, me_again = app.call("/api/me", token=again)
    check("github: second login reuses account", me_again["user"]["username"] == "octovibe")
    _, link = app.call("/api/auth/github/link", {}, alice)
    link_state = urllib.parse.parse_qs(urllib.parse.urlparse(link["url"]).query)["state"][0]
    _, location = app.redirect(f"/api/auth/github/callback?code=good&state={link_state}")
    check("github: can't link an account owned by someone else", "autherror" in location)

    # --- verified ships + GitHub XP
    xp0 = app.call("/api/me", token=octo)[1]["user"]["xp"]
    _, ship = app.call("/api/posts", {"kind": "ship", "body": "shipit v1", "repo": "https://github.com/octovibe/shipit"}, octo)
    check("ships: own fresh repo is verified (+50 +50 XP)", ship.get("verified") and ship["xp_gained"] == 100, ship)
    _, other = app.call("/api/posts", {"kind": "ship", "body": "not mine", "repo": "https://github.com/someone/else"}, octo)
    check("ships: someone else's repo is NOT verified", other.get("verified") is False and "contributor" in other["verify_note"])
    _, stale = app.call("/api/posts", {"kind": "ship", "body": "old", "repo": "https://github.com/octovibe/stale"}, octo)
    check("ships: stale repo is NOT verified", stale.get("verified") is False and "no pushes" in stale["verify_note"])
    _, unlinked = app.call("/api/posts", {"kind": "ship", "body": "x", "repo": "https://github.com/octovibe/shipit"}, chen)
    check("ships: unlinked user can't verify", unlinked.get("verified") is False and "link your GitHub" in unlinked["verify_note"])
    _, feed = app.call("/api/feed", token=alice)
    verified_post = next(post for post in feed["posts"] if post["body"] == "shipit v1")
    check("ships: feed shows verified badge data", verified_post["verified"] and verified_post["repo"].endswith("shipit"))
    _, sync = app.call("/api/github/sync", {}, octo)
    check("github sync: 3 recent pushes -> +9 XP", sync == {"pushes_found": 3, "xp_gained": 9}, sync)
    _, sync2 = app.call("/api/github/sync", {}, octo)
    check("github sync: no double counting", sync2["xp_gained"] == 0)
    check("github sync: total XP adds up", app.call("/api/me", token=octo)[1]["user"]["xp"] == xp0 + 100 + 50 + 50 + 9)

    # --- Stripe Connect payments
    status, error = app.call("/api/products", {"kind": "template", "title": "Kit", "description": "d", "price": 20}, dara)
    check("payments: paid listing blocked before payouts", status == 400 and "payouts" in error["error"])
    _, connect = app.call("/api/payouts/connect", {}, dara)
    check("payments: onboarding link", connect["url"].startswith("https://connect.stripe.test"))
    _, refreshed = app.call("/api/payouts/refresh", {}, dara)
    check("payments: payouts enabled after onboarding", refreshed["payouts_enabled"] is True)
    status, product = app.call("/api/products", {"kind": "template", "title": "Pro Kit", "description": "d", "price": 20,
                                                 "delivery_link": "https://dl.test/kit"}, dara)
    check("payments: paid listing allowed after payouts", status == 200)
    product_id = product["id"]
    status, error = app.call("/api/products/1/buy", {}, chen)  # seed product of dara... (she is now enabled)
    seed_products = app.call("/api/products", token=chen)[1]["products"]
    budi_paid = next(p for p in seed_products if p["seller"] == "budi")
    status, error = app.call(f"/api/products/{budi_paid['id']}/buy", {}, chen)
    check("payments: can't buy from seller without payouts", status == 400 and not budi_paid["seller_can_sell"])
    free = next(p for p in seed_products if p["price_cents"] == 0)
    status, got = app.call(f"/api/products/{free['id']}/buy", {}, alice)
    check("payments: free product is instant", status == 200 and got["status"] == "paid")

    status, buy = app.call(f"/api/products/{product_id}/buy", {}, chen)
    session_id = buy.get("checkout_url", "").rsplit("/", 1)[-1]
    params = FakeState.sessions.get(session_id, {}).get("params", {})
    check("payments: checkout session created", status == 200 and buy["status"] == "pending" and session_id)
    check("payments: price, 10% fee and destination sent to Stripe",
          params.get("line_items[0][price_data][unit_amount]") == "2000"
          and params.get("payment_intent_data[application_fee_amount]") == "200"
          and params.get("payment_intent_data[transfer_data][destination]") == "acct_test123", params)
    owned_before = next(p for p in app.call("/api/products", token=chen)[1]["products"] if p["id"] == product_id)
    check("payments: not owned / link hidden until paid", not owned_before["owned"] and owned_before["delivery_link"] == "")

    event = json.dumps({"type": "checkout.session.completed",
                        "data": {"object": {"id": session_id, "payment_status": "paid"}}}).encode()
    status, _ = app.call("/api/stripe/webhook", raw=event, headers={"Stripe-Signature": stripe_signature(event, "wrong")})
    check("webhook: bad signature rejected", status == 400)
    old = stripe_signature(event, timestamp=time.time() - 3600)
    status, _ = app.call("/api/stripe/webhook", raw=event, headers={"Stripe-Signature": old})
    check("webhook: stale timestamp rejected", status == 400)
    dara_xp = app.call("/api/me", token=dara)[1]["user"]["xp"]
    status, _ = app.call("/api/stripe/webhook", raw=event, headers={"Stripe-Signature": stripe_signature(event)})
    app.call("/api/stripe/webhook", raw=event, headers={"Stripe-Signature": stripe_signature(event)})
    owned_after = next(p for p in app.call("/api/products", token=chen)[1]["products"] if p["id"] == product_id)
    check("webhook: valid event completes order", status == 200 and owned_after["owned"] and owned_after["delivery_link"])
    check("webhook: replay is idempotent (sale XP once)", app.call("/api/me", token=dara)[1]["user"]["xp"] == dara_xp + 100)
    _, dara_orders = app.call("/api/orders", token=dara)
    check("payments: seller revenue & net after fee", dara_orders["revenue_cents"] == 2000 and dara_orders["net_cents"] == 1800)
    status, _ = app.call(f"/api/products/{product_id}/buy", {}, chen)
    check("payments: can't buy twice", status == 409)

    _, buy2 = app.call(f"/api/products/{product_id}/buy", {}, alice)
    session2 = buy2["checkout_url"].rsplit("/", 1)[-1]
    _, pending = app.call(f"/api/checkout/confirm?session_id={session2}", token=alice)
    check("confirm: unpaid session stays pending", pending["status"] == "pending")
    FakeState.sessions[session2]["payment_status"] = "paid"
    _, confirmed = app.call(f"/api/checkout/confirm?session_id={session2}", token=alice)
    check("confirm: paid session completes without webhook", confirmed["status"] == "paid" and confirmed["delivery_link"])
    status, _ = app.call(f"/api/checkout/confirm?session_id={session2}", token=chen)
    check("confirm: other users can't confirm your order", status == 404)

    # --- notifications, Web Push, ntfy
    status, _ = app.call("/api/push/subscribe", {"endpoint": "https://evil.example/collect"}, alice)
    check("push: arbitrary endpoints rejected (SSRF guard)", status == 400)
    status, _ = app.call("/api/push/subscribe", {"endpoint": f"{fake_base}/push/alice-phone"}, alice)
    check("push: subscription saved", status == 200)
    status, error = app.call("/api/profile", {"ntfy_topic": "short"}, alice)
    check("ntfy: weak topic rejected", status == 400)
    status, _ = app.call("/api/profile", {"ntfy_topic": "alice-secret-topic-123", "country": "US"}, alice)
    check("ntfy: topic saved", status == 200)
    FakeState.pushes.clear()
    FakeState.ntfy.clear()
    _, my_post = app.call("/api/posts", {"kind": "post", "body": "push me"}, alice)
    app.call(f"/api/posts/{my_post['id']}/like", {}, chen)
    delivered = wait_for(lambda: FakeState.pushes and FakeState.ntfy)
    check("push: like triggers web push + ntfy", delivered)
    if FakeState.pushes:
        ok, library = verify_vapid(FakeState.pushes[0]["auth"], fake_base, vapid_public)
        check(f"push: VAPID JWT valid (verified with {library})", ok)
    if FakeState.ntfy:
        wait_for(lambda: any("chen liked your post" in item["body"] for item in FakeState.ntfy))
        liked = next((item for item in FakeState.ntfy if "chen liked your post" in item["body"]), None)
        check("ntfy: message text + click link", liked is not None
              and liked["topic"] == "alice-secret-topic-123" and liked["click"].endswith("#feed"), FakeState.ntfy)
    _, notes = app.call("/api/notifications?unread=1&limit=1", token=alice)
    check("notifications: worker can fetch newest text", notes["notifications"] and "liked your post" in notes["notifications"][0]["text"])
    app.call("/api/notifications/read", {}, alice)
    check("notifications: mark read", app.call("/api/notifications", token=alice)[1]["unread"] == 0)

    app.call("/api/push/subscribe", {"endpoint": f"{fake_base}/push/gone"}, chen)
    gone_hits = lambda: [push for push in FakeState.pushes if push["path"].endswith("/gone")]
    app.call("/api/push/test", {}, chen)
    wait_for(lambda: gone_hits())
    time.sleep(0.5)
    hits_after_first = len(gone_hits())
    app.call("/api/push/test", {}, chen)
    time.sleep(2)
    check("push: expired (410) subscriptions are removed", hits_after_first == 1 and len(gone_hits()) == 1, gone_hits())

    app.call("/api/friends/request", {"username": "alice"}, octo)
    check("notifications: friend request notifies", wait_for(lambda: any("friend request" in n["body"] for n in FakeState.ntfy)))
    app.call("/api/friends/accept", {"username": "alice"}, chen)  # seed: chen -> alice pending
    status, _ = app.call("/api/friends/accept", {"username": "chen"}, alice)
    time.sleep(1)
    app.call("/api/chat/dm:alice", {"body": "hey from chen"}, chen)
    check("notifications: DMs reach the phone", wait_for(lambda: any("hey from chen" in n["body"] for n in FakeState.ntfy)))

    # --- installable app assets
    for path, expected in [("/manifest.webmanifest", "manifest"), ("/sw.js", "javascript"), ("/static/icon-512.png", "png")]:
        with DIRECT.open(app.base + path, timeout=10) as response:
            check(f"pwa: {path} served as {expected}", expected in response.headers.get("Content-Type", ""))

    # --- regression: core features still work
    _, ladder = app.call("/api/ladder", token=alice)
    check("regression: ladder", ladder["entries"][0]["rank"] == 1 and ladder["total"] >= 6)
    status, device = app.call("/api/devices", {"name": "CI box"}, alice)
    app.call(f"/api/devices/{device['id']}/commands", {"kind": "ping"}, alice)
    bridge = subprocess.run([sys.executable, os.path.join(APP_DIR, "agent.py"), "--server", app.base,
                             "--key", device["key"], "--once",
                             "--audit-log", os.path.join(tempfile.mkdtemp(prefix="vibehq-audit-"), "audit.log")],
                            capture_output=True, text=True, timeout=120)
    _, commands = app.call(f"/api/devices/{device['id']}/commands", token=alice)
    check("regression: device bridge runs commands", commands["commands"][0]["status"] == "done", bridge.stderr[-300:])


def run_security(app, database):
    """Hardening checks: command PIN, brute force, sessions, stream tickets, headers, bridge guards."""
    import sqlite3

    emeka = app.login("emeka")

    # --- sessions are stored hashed
    with sqlite3.connect(database) as db:
        stored = [row[0] for row in db.execute("SELECT token FROM sessions")]
    check("sessions: raw tokens never stored", emeka not in stored and hashlib.sha256(emeka.encode()).hexdigest() in stored)

    # --- login brute force: 5 failures lock the account for 15 min (even for the right password)
    statuses = [app.call("/api/login", {"username": "budi", "password": f"wrong{n}"})[0] for n in range(5)]
    locked_status, locked = app.call("/api/login", {"username": "budi", "password": "demo1234"})
    check("login: wrong passwords rejected", statuses == [401] * 5)
    check("login: locked after 5 failures", locked_status == 429 and "15 minutes" in locked["error"])
    check("login: unknown user gives same error", app.call("/api/login", {"username": "nobody_x", "password": "x" * 8})[1]["error"] == "wrong username or password")

    # --- registration rate limit per IP
    codes = [app.call("/api/register", {"username": f"spam_user{n}", "password": "longpass1"})[0] for n in range(6)]
    check("register: 5 sign-ups per IP per hour", codes[:5] == [200] * 5 and codes[5] == 429, codes)

    # --- stream tickets replace tokens in URLs
    request = urllib.request.Request(f"{app.base}/api/stream?token={emeka}")
    try:
        DIRECT.open(request, timeout=5)
        legacy_status = 200
    except urllib.error.HTTPError as error:
        legacy_status = error.code
    check("stream: ?token= no longer accepted", legacy_status == 401)
    ticket = app.call("/api/stream/ticket", {}, emeka)[1]["ticket"]
    connection = http.client.HTTPConnection(urllib.parse.urlparse(app.base).hostname, urllib.parse.urlparse(app.base).port, timeout=5)
    connection.request("GET", f"/api/stream?ticket={ticket}")
    stream_response = connection.getresponse()
    first_bytes = stream_response.read(12)
    connection.close()
    check("stream: valid ticket opens the stream", stream_response.status == 200 and first_bytes.startswith(b"retry"))
    connection = http.client.HTTPConnection(urllib.parse.urlparse(app.base).hostname, urllib.parse.urlparse(app.base).port, timeout=5)
    connection.request("GET", f"/api/stream?ticket={ticket}")
    check("stream: ticket is single-use", connection.getresponse().status == 401)
    connection.close()

    # --- command PIN guards agent tasks & shell
    _, device = app.call("/api/devices", {"name": "Sec box"}, emeka)
    commands_url = f"/api/devices/{device['id']}/commands"
    status, error = app.call(commands_url, {"kind": "shell", "payload": "echo hi"}, emeka)
    check("pin: risky command blocked until a PIN is set", status == 403 and "set a command PIN" in error["error"])
    check("pin: read-only commands need no PIN", app.call(commands_url, {"kind": "ping"}, emeka)[0] == 200)
    check("pin: weak PIN rejected", app.call("/api/security/pin", {"pin": "12"}, emeka)[0] == 400)
    check("pin: set PIN", app.call("/api/security/pin", {"pin": "482913"}, emeka)[0] == 200)
    status, _ = app.call(commands_url, {"kind": "shell", "payload": "echo hi", "pin": "000000"}, emeka)
    check("pin: wrong PIN rejected", status == 403)
    status, sent = app.call(commands_url, {"kind": "shell", "payload": "echo pin-ok", "pin": "482913"}, emeka)
    check("pin: correct PIN accepted", status == 200)
    alerts = app.call("/api/notifications?limit=5", token=emeka)[1]["notifications"]
    check("pin: every risky command raises an alert", any("shell sent to Sec box" in item["text"] for item in alerts))
    for _ in range(5):
        app.call(commands_url, {"kind": "shell", "payload": "echo x", "pin": "111111"}, emeka)
    status, error = app.call(commands_url, {"kind": "shell", "payload": "echo x", "pin": "482913"}, emeka)
    check("pin: locked after 5 wrong PINs", status == 429)

    # --- sessions: list, revoke, password change signs out others
    second = app.login("emeka")
    _, listed = app.call("/api/security/sessions", token=emeka)
    check("sessions: listed with current flag", len(listed["sessions"]) >= 2 and sum(s["current"] for s in listed["sessions"]) == 1)
    other_id = next(s["id"] for s in app.call("/api/security/sessions", token=emeka)[1]["sessions"] if not s["current"])
    app.call("/api/security/sessions/revoke", {"id": other_id}, emeka)
    check("sessions: revoked session stops working", app.call("/api/me", token=second)[0] == 401)
    third = app.login("emeka")
    status, changed = app.call("/api/security/password", {"current_password": "wrongpass", "new_password": "newpass123"}, emeka)
    check("password: wrong current password rejected", status == 403)
    status, changed = app.call("/api/security/password", {"current_password": "demo1234", "new_password": "newpass123"}, emeka)
    check("password: change signs out other devices", status == 200 and changed["signed_out_sessions"] >= 1 and app.call("/api/me", token=third)[0] == 401)
    check("password: current device stays signed in", app.call("/api/me", token=emeka)[0] == 200)
    check("password: new password works", app.call("/api/login", {"username": "emeka", "password": "newpass123"})[0] == 200)

    # --- headers
    with DIRECT.open(app.base + "/", timeout=10) as response:
        headers = response.headers
    check("headers: CSP + frame + nosniff on the app",
          "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")
          and headers.get("X-Frame-Options") == "DENY"
          and headers.get("X-Content-Type-Options") == "nosniff")
    check("health endpoint", app.call("/api/health")[1].get("ok") is True)

    # --- bridge guards: shell allowlist + stale command refusal
    # (emeka's remote commands are locked by the wrong-PIN test above, so use another account)
    dara = app.login("dara")
    app.call("/api/security/pin", {"pin": "731905"}, dara)
    _, bridge_device = app.call("/api/devices", {"name": "Guarded box"}, dara)
    url = f"/api/devices/{bridge_device['id']}/commands"
    for payload in ["echo allowed-ok", "echo hi & whoami", "whoami", "echo stale"]:
        status, sent = app.call(url, {"kind": "shell", "payload": payload, "pin": "731905"}, dara)
        assert status == 200, (payload, sent)
    stale = sent
    with sqlite3.connect(database) as db:
        db.execute("UPDATE commands SET created=created-3600 WHERE id=?", (stale["command"]["id"],))
    audit_log = os.path.join(tempfile.mkdtemp(prefix="vibehq-audit-"), "audit.log")
    subprocess.run(
        [sys.executable, os.path.join(APP_DIR, "agent.py"), "--server", app.base, "--key", bridge_device["key"],
         "--allow-shell", "--shell-allow", "echo", "--audit-log", audit_log, "--once"],
        capture_output=True, text=True, timeout=120,
    )
    results = {c["payload"]: c for c in app.call(url, token=dara)[1]["commands"]}
    check("bridge: allowlisted shell runs", results["echo allowed-ok"]["status"] == "done" and "allowed-ok" in results["echo allowed-ok"]["result"])
    check("bridge: chaining refused", results["echo hi & whoami"]["status"] == "failed" and "chaining" in results["echo hi & whoami"]["result"])
    check("bridge: non-allowlisted command refused", results["whoami"]["status"] == "failed" and "not in --shell-allow" in results["whoami"]["result"])
    check("bridge: stale queued command refused", results["echo stale"]["status"] == "failed" and "waited" in results["echo stale"]["result"])
    with open(audit_log, encoding="utf-8") as handle:
        audit_lines = [json.loads(line) for line in handle if line.strip()]
    check("bridge: audit log records every command", len(audit_lines) == 4)


def main():
    fake_port = free_port()
    fake = ThreadingHTTPServer(("127.0.0.1", fake_port), FakeServices)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    fake_base = f"http://127.0.0.1:{fake_port}"

    app_port = free_port()
    database = os.path.join(tempfile.mkdtemp(prefix="vibehq-test-"), "test.db")
    env = dict(
        os.environ,
        VIBEHQ_DB=database,
        VIBEHQ_QUIET="1",
        PUBLIC_URL=f"http://127.0.0.1:{app_port}",
        STRIPE_SECRET_KEY="sk_test_fake",
        STRIPE_API_BASE=fake_base,
        STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
        GITHUB_CLIENT_ID="fake-client",
        GITHUB_CLIENT_SECRET="fake-secret",
        GITHUB_API_BASE=fake_base,
        GITHUB_OAUTH_BASE=fake_base,
        NTFY_BASE=f"{fake_base}/ntfy",
        PUSH_EXTRA_HOSTS="127.0.0.1",
        NO_PROXY="127.0.0.1,localhost",
    )
    server_log_path = os.path.join(os.path.dirname(database), "server.log")
    server_log = open(server_log_path, "w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-u", os.path.join(APP_DIR, "server.py"), "--demo", "--port", str(app_port)],
        env=env, stdout=server_log, stderr=subprocess.STDOUT, text=True,
    )
    app = App(f"http://127.0.0.1:{app_port}")
    try:
        if not wait_for(lambda: app.call("/api/config")[0] == 200 if server.poll() is None else True, timeout=15):
            raise SystemExit("server did not start")
        if server.poll() is not None:
            raise SystemExit("server crashed:\n" + open(server_log_path, encoding="utf-8").read())
        run(app, fake_base)
        run_security(app, database)
    finally:
        server.terminate()
        server.wait(timeout=10)
        server_log.close()
        fake.shutdown()
    if not all(ok for _, ok, _ in RESULTS):
        print("---- server log (tail) ----")
        print(open(server_log_path, encoding="utf-8").read()[-3000:])
    passed = 0
    for label, ok, detail in RESULTS:
        passed += ok
        print(("PASS  " if ok else "FAIL  ") + label + ("" if ok or not detail else f"   -> {detail}"))
    print(f"\n{passed}/{len(RESULTS)} passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
