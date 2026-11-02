"""End-to-end test for the HQ part of shiphub (feed, ladder, friends, chat, agents, market, account).

Starts server.py on a free port with a throwaway data folder and talks to it over HTTP.
Standard library only:  python tests/test_hq.py
"""

import http.client
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Client:
    """A browser-like client with its own cookie jar (one per signed-in user)."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def call(self, method: str, path: str, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {"_raw": raw.decode(errors="replace")}
        return status, payload

    def get(self, path, **kwargs):
        return self.call("GET", path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.call("POST", path, body if body is not None else {}, **kwargs)

    def session_cookie(self) -> str:
        for cookie in self.jar:
            if cookie.name == "shiphub_sid":
                return cookie.value
        return ""


class HQTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.TemporaryDirectory(prefix="shiphub_hq_test_")
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = dict(
            os.environ,
            SHIPHUB_DATA_DIR=cls.data_dir.name,
            SHIPHUB_DEMO="1",
            SHIPHUB_RATE_LIMITS="0",
            PORT=str(cls.port),
            PYTHONIOENCODING="utf-8",
        )
        for name in ("DATABASE_URL", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "GITHUB_TOKEN"):
            env.pop(name, None)
        cls.log = open(Path(cls.data_dir.name) / "server.log", "w", encoding="utf-8")
        cls.server = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), "--no-browser", "--host", "127.0.0.1"],
            cwd=ROOT,
            env=env,
            stdout=cls.log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                status, _ = Client(cls.base).get("/api/hq/config")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.3)
        else:
            cls.tearDownClass()
            raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        cls.log.close()
        cls.data_dir.cleanup()

    # ----- helpers ----------------------------------------------------------- #

    def signup(self, username: str, password: str = "password123") -> Client:
        client = Client(self.base)
        status, body = client.post(
            "/api/auth/signup",
            {"username": username, "password": password, "display_name": username.title()},
        )
        self.assertEqual(status, 200, body)
        return client

    def login(self, username: str, password: str = "password123") -> Client:
        client = Client(self.base)
        status, body = client.post("/api/auth/login", {"username": username, "password": password})
        self.assertEqual(status, 200, body)
        return client

    def ok(self, result, expected=200):
        status, body = result
        self.assertEqual(status, expected, body)
        return body

    def xp(self, client: Client) -> int:
        return self.ok(client.get("/api/hq/me"))["user"]["xp"]

    def notifications(self, client: Client) -> list:
        body = self.ok(client.get("/api/notifications"))
        return body.get("notifications") or body.get("items") or []

    def befriend(self, first: Client, first_name: str, second: Client, second_name: str):
        self.assertEqual(self.ok(first.post("/api/hq/friends/request", {"username": second_name}))["status"], "pending")
        self.assertEqual(self.ok(second.post("/api/hq/friends/accept", {"username": first_name}))["status"], "accepted")

    # ----- tests -------------------------------------------------------------- #

    def test_static_and_config(self):
        anonymous = Client(self.base)
        self.ok(anonymous.get("/api/hq/config"))
        self.ok(anonymous.get("/api/hq/feed"))
        self.ok(anonymous.get("/api/hq/ladder"))
        self.ok(anonymous.get("/api/hq/products"))
        self.assertEqual(anonymous.get("/api/hq/me")[0], 401)
        for path in ("/sw.js", "/manifest.webmanifest", "/static/hq.js", "/static/icon-192.png"):
            with anonymous.opener.open(self.base + path, timeout=10) as response:
                self.assertEqual(response.status, 200, path)
                self.assertTrue(response.read(), path)

    def test_stripe_webhook_off_without_config(self):
        status, _ = Client(self.base).post("/api/hq/stripe/webhook", {"type": "ping"})
        self.assertEqual(status, 404)

    def test_feed_like_and_notification(self):
        alice = self.signup("alice_feed")
        bob = self.signup("bob_feed")
        before = self.xp(alice)
        post = self.ok(alice.post("/api/hq/posts", {"kind": "tip", "body": "Commit before every agent run."}))
        self.assertGreater(post["xp_gained"], 0)
        self.assertEqual(self.xp(alice), before + post["xp_gained"])
        feed = self.ok(bob.get("/api/hq/feed"))
        self.assertIn(post["id"], [item["id"] for item in feed["posts"]])
        self.assertTrue(self.ok(bob.post(f"/api/hq/posts/{post['id']}/like"))["liked"])
        hq_notes = [note for note in self.notifications(alice) if note.get("kind") == "hq"]
        self.assertTrue(any("liked your post" in (note.get("text") or "") for note in hq_notes), hq_notes)
        self.assertFalse(self.ok(bob.post(f"/api/hq/posts/{post['id']}/like"))["liked"])

    def test_idea_earns_hq_xp(self):
        maker = self.signup("idea_maker")
        before = self.xp(maker)
        self.ok(maker.post("/api/ideas", {
            "title": "Agent status wall",
            "pitch": "A wall display that shows what every coding agent is doing.",
            "body": "",
            "stack": "Python",
        }))
        self.assertGreater(self.xp(maker), before)

    def test_friends_chat_and_dm(self):
        carol = self.signup("carol_chat")
        dave = self.signup("dave_chat")
        self.assertEqual(carol.post("/api/hq/chat/dm:dave_chat", {"body": "hi"})[0], 403)
        self.befriend(carol, "carol_chat", dave, "dave_chat")
        friends = self.ok(dave.get("/api/hq/friends"))
        self.assertIn("carol_chat", json.dumps(friends))
        self.ok(carol.post("/api/hq/chat/world", {"body": "hello world"}))
        time.sleep(0.8)
        self.ok(carol.post("/api/hq/chat/dm:dave_chat", {"body": "secret plan"}))
        history = self.ok(dave.get("/api/hq/chat/dm:carol_chat"))
        self.assertIn("secret plan", json.dumps(history))
        world = self.ok(dave.get("/api/hq/chat/world"))
        self.assertIn("hello world", json.dumps(world))
        self.assertEqual(carol.post("/api/hq/chat/world", {"body": "too fast"})[0], 429)
        ladder = self.ok(carol.get("/api/hq/ladder?scope=friends"))
        self.assertIn("dave_chat", json.dumps(ladder))
        self.ok(carol.get("/api/hq/ladder?period=week"))
        self.assertEqual(carol.get("/api/hq/ladder?scope=country")[0], 400)
        self.ok(carol.post("/api/hq/profile", {"country": "ID", "stack": "Codex"}))
        self.ok(carol.get("/api/hq/ladder?scope=country"))

    def test_devices_commands_and_pin(self):
        erin = self.signup("erin_agents")
        device = self.ok(erin.post("/api/hq/devices", {"name": "laptop"}))
        self.assertTrue(device["key"].startswith("shd_"))
        agent = Client(self.base)
        key_header = {"X-Device-Key": device["key"]}
        self.assertEqual(agent.post("/api/hq/agent/heartbeat", {"info": {}}, headers={"X-Device-Key": "nope"})[0], 401)
        self.ok(agent.post("/api/hq/agent/heartbeat", {"info": {"os": "test"}}, headers=key_header))

        command = self.ok(erin.post(f"/api/hq/devices/{device['id']}/commands", {"kind": "ping"}))["command"]
        polled = self.ok(agent.get("/api/hq/agent/poll", headers=key_header))["commands"]
        self.assertEqual([item["id"] for item in polled], [command["id"]])
        self.ok(agent.post("/api/hq/agent/result", {"id": command["id"], "status": "done", "result": "pong"}, headers=key_header))
        history = self.ok(erin.get(f"/api/hq/devices/{device['id']}/commands"))["commands"]
        self.assertEqual(history[0]["status"], "done")

        risky = {"kind": "shell", "payload": "git status"}
        status, body = erin.post(f"/api/hq/devices/{device['id']}/commands", risky)
        self.assertEqual(status, 403, body)
        self.ok(erin.post("/api/account/pin", {"pin": "246810"}))
        self.ok(erin.post(f"/api/hq/devices/{device['id']}/commands", dict(risky, pin="246810")))
        codes = [erin.post(f"/api/hq/devices/{device['id']}/commands", dict(risky, pin="000000"))[0] for _ in range(6)]
        self.assertEqual(codes[:5], [403] * 5)
        self.assertEqual(codes[5], 429)

        # Another user can't see or drive this device.
        mallory = self.signup("mallory_agents")
        self.assertEqual(mallory.post(f"/api/hq/devices/{device['id']}/commands", {"kind": "ping"})[0], 404)

    def test_agent_script_once(self):
        frank = self.signup("frank_agent")
        device = self.ok(frank.post("/api/hq/devices", {"name": "ci-box"}))
        self.ok(frank.post(f"/api/hq/devices/{device['id']}/commands", {"kind": "ping"}))
        with tempfile.TemporaryDirectory() as workdir:
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "agent.py"),
                    "--server", self.base,
                    "--key", device["key"],
                    "--workdir", workdir,
                    "--audit-log", str(Path(workdir) / "audit.log"),
                    "--once",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                env=dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost", PYTHONIOENCODING="utf-8"),
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        history = self.ok(frank.get(f"/api/hq/devices/{device['id']}/commands"))["commands"]
        self.assertEqual(history[0]["status"], "done", history)
        devices = self.ok(frank.get("/api/hq/devices"))["devices"]
        self.assertTrue(devices[0].get("online") or devices[0].get("last_seen"), devices)

    def test_market_demo_buy(self):
        gina = self.signup("gina_market")
        products = self.ok(gina.get("/api/hq/products"))["products"]
        paid = [item for item in products if item.get("price_cents", 0) > 0]
        self.assertTrue(paid, "demo seed should include paid products")
        bought = self.ok(gina.post(f"/api/hq/products/{paid[0]['id']}/buy"))
        self.assertEqual(bought["status"], "paid")
        self.assertTrue(bought["demo"])
        self.assertEqual(gina.post(f"/api/hq/products/{paid[0]['id']}/buy")[0], 409)
        orders = self.ok(gina.get("/api/hq/orders"))
        self.assertIn(paid[0]["title"], json.dumps(orders))
        listing = self.ok(gina.post("/api/hq/products", {
            "kind": "template",
            "title": "Prompt pack",
            "description": "Twenty prompts for refactors.",
            "price": 0,
        }))
        self.assertTrue(listing)

    def test_sse_stream(self):
        hank = self.signup("hank_stream")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", "/api/hq/stream", headers={"Cookie": f"shiphub_sid={hank.session_cookie()}"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.getheader("Content-Type", ""))
        first = response.fp.readline().decode()
        self.assertTrue(first.startswith("retry:"), first)
        connection.close()
        anonymous = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        anonymous.request("GET", "/api/hq/stream")
        self.assertEqual(anonymous.getresponse().status, 401)
        anonymous.close()

    def test_sessions_and_password(self):
        ivy_laptop = self.signup("ivy_account")
        ivy_phone = self.login("ivy_account")
        ivy_tablet = self.login("ivy_account")
        sessions = self.ok(ivy_laptop.get("/api/account/sessions"))["sessions"]
        self.assertEqual(len(sessions), 3)
        self.assertEqual(sum(1 for item in sessions if item["current"]), 1)

        phone_id = next(item["id"] for item in self.ok(ivy_phone.get("/api/account/sessions"))["sessions"] if item["current"])
        self.assertEqual(self.ok(ivy_laptop.post("/api/account/sessions/revoke", {"id": phone_id}))["signed_out"], 1)
        self.assertEqual(ivy_phone.get("/api/hq/me")[0], 401)
        self.ok(ivy_tablet.get("/api/hq/me"))

        self.assertEqual(ivy_laptop.post("/api/account/password", {
            "current_password": "wrong-one", "new_password": "newpassword456",
        })[0], 403)
        changed = self.ok(ivy_laptop.post("/api/account/password", {
            "current_password": "password123", "new_password": "newpassword456",
        }))
        self.assertEqual(changed["signed_out_sessions"], 1)
        self.assertEqual(ivy_tablet.get("/api/hq/me")[0], 401)
        self.ok(ivy_laptop.get("/api/hq/me"))
        self.login("ivy_account", "newpassword456")

    def test_public_profile_has_hq_block(self):
        self.signup("jade_profile")
        anonymous = Client(self.base)
        profile = self.ok(anonymous.get("/api/users/jade_profile"))
        self.assertIn("hq", profile)
        self.ok(anonymous.get("/api/hq/users/jade_profile"))
        self.assertEqual(anonymous.get("/api/hq/users/nobody_here_xyz")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
