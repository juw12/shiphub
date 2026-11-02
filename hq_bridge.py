"""Mount vibeHQ inside shiphub at /hq: one site, one account.

shiphub starts vibeHQ as a child process on a private loopback port and proxies
everything under /hq/ to it. Sign-in is shared: when the vibeHQ page asks for a
session (POST /hq/api/sso), shiphub attaches an HMAC-signed, short-lived copy of
the logged-in shiphub user. The secret is generated per boot and only the two
processes know it; clients can never set that header themselves.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HQ_PREFIX = "/hq"
ASSERT_HEADER = "X-Shiphub-Assert"
SSO_PATH = HQ_PREFIX + "/api/sso"
MAX_BODY_BYTES = 1024 * 1024
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
# Never forwarded to vibeHQ: shiphub's own cookies, spoofable forwarding info, and the trust header.
STRIP_REQUEST = HOP_BY_HOP | {"host", "cookie", "content-length", "x-forwarded-for", "x-forwarded-proto", ASSERT_HEADER.lower()}
STRIP_RESPONSE = HOP_BY_HOP | {"server", "date", "content-length"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class HQBridge:
    def __init__(self, app_dir: Path, data_dir: Path, demo: bool) -> None:
        self.app_dir = app_dir
        self.data_dir = data_dir
        self.demo = demo
        self.secret = secrets.token_hex(32)
        self.port = 0
        self.process: subprocess.Popen | None = None
        self.stopping = False
        self.ready = False

    # ----- child process ----- #

    def child_env(self, site_url: str) -> dict:
        env = dict(os.environ)
        env.update({
            "VIBEHQ_BASE_PATH": HQ_PREFIX,
            "VIBEHQ_SSO_SECRET": self.secret,
            "VIBEHQ_SSO_NAME": "shiphub",
            "VIBEHQ_SSO_LOGIN_URL": "/#/login?next=" + HQ_PREFIX + "/",
            "VIBEHQ_SSO_LOGOUT_URL": "/api/auth/logout",
            "VIBEHQ_SSO_HOME_URL": "/",
            "PUBLIC_URL": site_url.rstrip("/") + HQ_PREFIX,
            "TRUST_PROXY": "1",  # shiphub is its proxy and passes the real client IP
            "VIBEHQ_QUIET": "1",
            "PYTHONUNBUFFERED": "1",
            "VIBEHQ_EXIT_WITH_PARENT": "1",  # child quits if shiphub dies without cleanup
        })
        env.setdefault("VIBEHQ_DB", str(self.data_dir / "vibehq.db"))
        # Optional separate GitHub OAuth app for vibeHQ; otherwise it shares shiphub's.
        for key in ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"):
            override = os.environ.get("VIBEHQ_" + key)
            if override:
                env[key] = override
        return env

    def spawn(self, site_url: str) -> None:
        self.port = free_port()
        args = [sys.executable, str(self.app_dir / "server.py"), "--host", "127.0.0.1", "--port", str(self.port)]
        if self.demo:
            args.append("--demo")
        self.process = subprocess.Popen(
            args,
            cwd=self.app_dir,
            env=self.child_env(site_url),
            stdin=subprocess.PIPE,  # held open for the child's lifetime; closes when we exit
        )

    def wait_ready(self, timeout: float = 20.0) -> bool:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process is None or self.process.poll() is not None:
                return False
            try:
                opener.open(f"http://127.0.0.1:{self.port}{HQ_PREFIX}/api/config", timeout=2).read()
                return True
            except OSError:
                time.sleep(0.25)
        return False

    def start(self, site_url: str) -> bool:
        self.spawn(site_url)
        self.ready = self.wait_ready()
        threading.Thread(target=self.supervise, args=(site_url,), daemon=True).start()
        return self.ready

    def supervise(self, site_url: str) -> None:
        """Restart vibeHQ if it ever exits, with a short back-off."""
        delay = 1.0
        while not self.stopping:
            if self.process is not None and self.process.poll() is not None and not self.stopping:
                self.ready = False
                sys.stderr.write(f"  vibeHQ exited ({self.process.returncode}), restarting in {delay:.0f}s\n")
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                if self.stopping:
                    break
                self.spawn(site_url)
                self.ready = self.wait_ready()
                if self.ready:
                    delay = 1.0
            time.sleep(1.0)

    def stop(self) -> None:
        self.stopping = True
        self.ready = False
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # ----- identity ----- #

    def sign(self, user) -> str:
        identity = {
            "id": int(user["id"]),
            "username": user["username"],
            "display_name": user["display_name"],
            "bio": user["bio"] or "",
            "avatar_url": user["avatar_url"] or "",
            "github_login": user["github_login"] or "",
            "ts": time.time(),
        }
        payload = base64.urlsafe_b64encode(json.dumps(identity).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    # ----- proxy ----- #

    def forward(self, handler, method: str, user=None) -> None:
        """Relay one request to vibeHQ and stream the answer back (SSE included)."""
        length = int(handler.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            handler.close_connection = True
            handler.send_json(413, {"error": "Request is too large"})
            return
        body = handler.rfile.read(length) if length else None
        if not self.ready:
            handler.send_json(503, {"error": "vibeHQ is starting, try again in a moment"})
            return

        headers = {key: value for key, value in handler.headers.items() if key.lower() not in STRIP_REQUEST}
        headers["Host"] = handler.headers.get("Host", "localhost")
        headers["X-Forwarded-For"] = handler.client_ip()
        headers["X-Forwarded-Proto"] = "https" if handler.is_https() else "http"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        if user is not None:
            headers[ASSERT_HEADER] = self.sign(user)

        upstream = http.client.HTTPConnection("127.0.0.1", self.port, timeout=90)
        try:
            try:
                upstream.request(method, handler.path, body=body, headers=headers)
                response = upstream.getresponse()
            except OSError:
                handler.send_json(502, {"error": "vibeHQ is not responding"})
                return
            handler.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in STRIP_RESPONSE:
                    handler.send_header(key, value)
            length_header = response.getheader("Content-Length")
            if length_header is not None:
                handler.send_header("Content-Length", length_header)
            else:
                handler.send_header("Connection", "close")
                handler.close_connection = True
            handler.end_headers()
            try:
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                handler.close_connection = True
        finally:
            upstream.close()
