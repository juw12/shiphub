"""End-to-end checks for shiphub + vibeHQ running as one site.

Run:  python tests/test_combined.py
Starts shiphub (which starts vibeHQ under /hq) on a free port with throwaway data.
"""
from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[bool, str]] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(condition), label))
    print(("PASS  " if condition else "FAIL  ") + label + ("" if condition else f"   [{detail}]"), flush=True)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Client:
    """Tiny HTTP client with its own cookie jar (one per simulated browser)."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
            NoRedirect(),
        )

    def call(self, method: str, path: str, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read()
                return response.status, dict(response.headers), raw
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def json(self, method: str, path: str, body=None, headers=None):
        status, _, raw = self.call(method, path, body, headers)
        try:
            return status, json.loads(raw or b"{}")
        except ValueError:
            return status, {"raw": raw[:200]}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def vibehq_children(port_hint: str) -> list[str]:
    """Running vibeHQ processes started from this checkout (best effort, Windows + Linux)."""
    marker = str(ROOT / "vibehq" / "server.py")
    if os.name == "nt":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "ForEach-Object { $_.CommandLine }",
        ]
    else:
        command = ["ps", "-eo", "args"]
    output = subprocess.run(command, capture_output=True, text=True, timeout=30).stdout
    return [line for line in output.splitlines() if marker in line]


def bearer(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="shiphub_combined_"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update({
        "SHIPHUB_DATA_DIR": str(data_dir),
        "SHIPHUB_DEMO": "1",
        "SHIPHUB_RATE_LIMITS": "0",
        "DATABASE_URL": "",
        "PORT": str(port),
        "NO_PROXY": "127.0.0.1,localhost",
    })
    for key in ("PUBLIC_URL", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "VIBEHQ_DB", "STRIPE_SECRET_KEY"):
        env.pop(key, None)
    log_path = data_dir / "server.log"
    log = open(log_path, "w")
    server = subprocess.Popen(
        [sys.executable, "-u", "server.py", "--reset", "--no-browser"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        anonymous = Client(base)
        deadline = time.time() + 40
        ready = False
        while time.time() < deadline and not ready:
            status, _, _ = anonymous.call("GET", "/hq/api/config")
            ready = status == 200
            if not ready:
                time.sleep(0.5)
        check(ready, "vibeHQ is reachable under /hq", log_path.read_text(errors="replace")[-800:])
        if not ready:
            return 1

        # ----- one site ----- #
        status, config = anonymous.json("GET", "/api/config")
        check(status == 200 and config.get("hq") is True, "shiphub config advertises the HQ tab", str(config))
        status, headers, _ = anonymous.call("GET", "/hq")
        check(status in (301, 302) and headers.get("Location", "").endswith("/hq/"), "/hq redirects to /hq/", f"{status} {headers.get('Location')}")
        status, headers, raw = anonymous.call("GET", "/hq/")
        check(status == 200 and b"vibe<span" in raw, "/hq/ serves the vibeHQ app", str(status))
        check("Content-Security-Policy" in headers, "vibeHQ security headers pass through the proxy")
        status, headers, raw = anonymous.call("GET", "/hq/sw.js")
        check(status == 200 and "javascript" in headers.get("Content-Type", ""), "service worker served from /hq/sw.js", headers.get("Content-Type", ""))
        status, _, raw = anonymous.call("GET", "/hq/manifest.webmanifest")
        manifest = json.loads(raw) if status == 200 else {}
        check(manifest.get("scope") == "./", "PWA manifest is relative to /hq/", str(manifest.get("scope")))
        status, hq_config = anonymous.json("GET", "/hq/api/config")
        sso = hq_config.get("sso") or {}
        check(sso.get("name") == "shiphub" and sso.get("login_url", "").startswith("/#/login"), "vibeHQ config switches to shiphub sign-in", str(sso))
        status, _ = anonymous.json("GET", "/api/users/demo")
        check(status == 200, "shiphub pages still work next to /hq")

        # ----- shared account ----- #
        status, _ = anonymous.json("POST", "/hq/api/sso", {})
        check(status == 401, "no shiphub login -> no vibeHQ session", str(status))
        forged = "eyJpZCI6IDEsICJ1c2VybmFtZSI6ICJkZW1vIiwgInRzIjogOTk5OTk5OTk5OTl9.deadbeef"
        status, _ = anonymous.json("POST", "/hq/api/sso", {}, {"X-Shiphub-Assert": forged})
        check(status == 401, "a client-supplied identity header is stripped", str(status))
        status, _ = anonymous.json("POST", "/hq/api/register", {"username": "sneaky", "password": "longenough1"})
        check(status == 403, "separate vibeHQ sign-ups are disabled", str(status))
        status, headers, _ = anonymous.call("GET", "/hq/api/auth/github/start")
        check(status == 302 and headers.get("Location", "").startswith("/#/login"), "vibeHQ GitHub login defers to shiphub", headers.get("Location", ""))

        browser = Client(base)
        status, login = browser.json("POST", "/api/auth/login", {"username": "demo", "password": "demo1234"})
        check(status == 200, "log in to shiphub as demo", str(login))
        status, _ = browser.json("POST", "/hq/api/sso", {}, {"Origin": "http://evil.example"})
        check(status == 403, "cross-site sign-on attempt is blocked", str(status))
        status, first = browser.json("POST", "/hq/api/sso", {}, {"Origin": base})
        token = first.get("token", "")
        check(status == 200 and token, "shiphub login gives a vibeHQ session", str(first))
        status, me = browser.json("GET", "/hq/api/me", headers=bearer(token))
        hq_user = me.get("user", {})
        check(status == 200 and hq_user.get("username") == "demo", "vibeHQ knows you as your shiphub username", str(hq_user.get("username")))
        status, second = browser.json("POST", "/hq/api/sso", {}, bearer(token))
        new_token = second.get("token", "")
        status_old, _ = browser.json("GET", "/hq/api/me", headers=bearer(token))
        status_new, me_again = browser.json("GET", "/hq/api/me", headers=bearer(new_token))
        check(status_old == 401, "re-sign-on rotates the old vibeHQ session", str(status_old))
        check(
            status_new == 200 and me_again.get("user", {}).get("id") == hq_user.get("id"),
            "same shiphub user -> same vibeHQ account (no duplicates)",
            str(me_again.get("user", {}).get("id")),
        )
        token = new_token

        other = Client(base)
        other.json("POST", "/api/auth/signup", {"username": "juw12", "password": "testpass123"})
        status, other_session = other.json("POST", "/hq/api/sso", {})
        status, other_me = other.json("GET", "/hq/api/me", headers=bearer(other_session.get("token", "")))
        check(other_me.get("user", {}).get("username") == "juw12", "a new shiphub account gets its own vibeHQ account", str(other_me))

        # ----- vibeHQ features through the proxy ----- #
        status, posted = browser.json("POST", "/hq/api/posts", {"kind": "tip", "body": "Combined site works: one login for ideas and agents."}, bearer(token))
        check(status == 200, "post a tip through /hq", str(posted))
        status, feed = browser.json("GET", "/hq/api/feed", headers=bearer(token))
        bodies = [item.get("body", "") for item in feed.get("posts", feed.get("items", []))]
        check(any("Combined site works" in body for body in bodies), "the tip shows in the vibeHQ feed", str(bodies[:3]))
        status, ticket = browser.json("POST", "/hq/api/stream/ticket", {}, bearer(token))
        stream_ok = False
        if status == 200:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            connection.request("GET", "/hq/api/stream?ticket=" + ticket["ticket"])
            response = connection.getresponse()
            first_bytes = response.read1(64) if response.status == 200 else b""
            stream_ok = response.status == 200 and b"retry" in first_bytes
            connection.close()
        check(stream_ok, "live updates (SSE) stream through the proxy")

        # ----- one logout ----- #
        status, _ = browser.json("POST", "/api/auth/logout", {})
        status, _ = browser.json("POST", "/hq/api/sso", {})
        check(status == 401, "logging out of shiphub ends vibeHQ sign-on", str(status))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        time.sleep(0.5)
        shutil.rmtree(data_dir, ignore_errors=True)

    time.sleep(3)
    check(not vibehq_children(port_hint=data_dir.name), "vibeHQ child exits when shiphub is killed")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
