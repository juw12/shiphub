#!/usr/bin/env python3
"""
VibeHQ device bridge.

Runs on your machine, reports health + which AI coding agents are running,
and executes commands you send from the VibeHQ app.

Safety model (defense in depth):
  * Read-only commands (ping, sysinfo, list_agents) always work.
  * Agent tasks / shell must be enabled ON THIS MACHINE (--allow-agent / --allow-shell);
    the server can never turn them on. The sender also needs their command PIN.
  * --approve asks you here (y/N) before every agent task or shell command.
  * --shell-allow restricts shell to listed command prefixes, no chaining/redirects.
  * Risky commands that sat in the queue longer than --max-age are refused.
  * Every command is appended to a local audit log (--audit-log).

Usage:
  python agent.py --server http://localhost:8787 --key vhq_xxx
  python agent.py --key vhq_xxx --allow-agent --agent-cmd "claude -p" --workdir C:\\code\\myapp
"""
import argparse
import json
import os
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

KNOWN_AGENTS = {
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "cursor": "Cursor",
    "aider": "Aider",
    "gemini": "Gemini CLI",
    "ollama": "Ollama",
    "goose": "Goose",
    "opencode": "OpenCode",
    "windsurf": "Windsurf",
    "copilot": "GitHub Copilot CLI",
    "amp": "Amp",
}
RISKY_KINDS = {"agent_task", "shell"}
SHELL_METACHARACTERS = set(";&|`$<>\n\r")
MAX_RESULT_CHARS = 20000
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 2
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Bridge:
    def __init__(self, args):
        self.args = args
        self.server = args.server.rstrip("/")
        self.running_ids = set()
        self.lock = threading.Lock()
        self.approval_lock = threading.Lock()
        self.audit_lock = threading.Lock()
        self.shell_allow = [prefix.strip() for prefix in (args.shell_allow or "").split(",") if prefix.strip()]
        # Corporate proxies often hijack loopback traffic; talk to local servers directly.
        host = urllib.parse.urlparse(self.server).hostname or ""
        handlers = [urllib.request.ProxyHandler({})] if host in LOCAL_HOSTS else []
        self.opener = urllib.request.build_opener(*handlers)

    # ------------------------------------------------------------ HTTP

    def request(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.server + path,
            data=data,
            method=method,
            headers={"X-Device-Key": self.args.key, "Content-Type": "application/json"},
        )
        with self.opener.open(req, timeout=20) as response:
            return json.loads(response.read() or b"{}")

    # ------------------------------------------------------------ discovery

    def running_processes(self):
        try:
            if os.name == "nt":
                output = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                names = [line.split('","')[0].strip('"') for line in output.splitlines() if line]
            else:
                output = subprocess.run(
                    ["ps", "-eo", "comm="], capture_output=True, text=True, timeout=10
                ).stdout
                names = [os.path.basename(line.strip()) for line in output.splitlines()]
        except (OSError, subprocess.SubprocessError):
            return []
        return [name.lower().removesuffix(".exe") for name in names if name]

    def detect_agents(self):
        processes = self.running_processes()
        agents = []
        for key, label in KNOWN_AGENTS.items():
            running = sum(1 for name in processes if name == key or name.startswith(key + "-"))
            installed = shutil.which(key) is not None
            if running or installed:
                agents.append({"id": key, "name": label, "running": running, "installed": installed})
        return agents

    def system_info(self):
        disk = shutil.disk_usage(self.args.workdir)
        info = {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "disk_total_gb": round(disk.total / 1e9, 1),
            "workdir": os.path.abspath(self.args.workdir),
            "allow_agent": self.args.allow_agent,
            "allow_shell": self.args.allow_shell,
            "agent_cmd": self.args.agent_cmd if self.args.allow_agent else "",
            "busy": len(self.running_ids),
        }
        if hasattr(os, "getloadavg"):
            info["load_avg"] = [round(value, 2) for value in os.getloadavg()]
        return info

    # ------------------------------------------------------------ commands

    def agent_argv(self, prompt):
        """Build the agent CLI argv; handles quoted paths and Windows .cmd shims (npm CLIs)."""
        parts = shlex.split(self.args.agent_cmd, posix=os.name != "nt")
        parts = [part.strip('"') for part in parts]
        resolved = shutil.which(parts[0])
        if resolved:
            parts[0] = resolved
        return parts + [prompt]

    def run_process(self, argv, shell, timeout):
        completed = subprocess.run(
            argv,
            shell=shell,
            cwd=self.args.workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        status = "done" if completed.returncode == 0 else "failed"
        return status, f"[exit {completed.returncode}]\n{output}"

    def audit(self, command, status, note=""):
        line = json.dumps({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "id": command["id"],
            "kind": command["kind"],
            "payload": command.get("payload", "")[:300],
            "status": status,
            "note": note[:200],
        })
        with self.audit_lock:
            with open(self.args.audit_log, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def guard(self, command):
        """Device-side checks for risky commands. Returns a refusal reason or None."""
        kind = command["kind"]
        payload = command.get("payload", "")
        if kind not in RISKY_KINDS:
            return None
        age = command.get("_age", 0)
        if age > self.args.max_age:
            return f"refused: command waited {age // 60} min in the queue (limit {self.args.max_age // 60} min)"
        if kind == "shell" and self.shell_allow:
            if any(char in SHELL_METACHARACTERS for char in payload):
                return "refused: shell chaining/redirection is not allowed by --shell-allow"
            if not any(payload == prefix or payload.startswith(prefix + " ") for prefix in self.shell_allow):
                return f"refused: '{payload.split()[0] if payload.split() else payload}' is not in --shell-allow"
        if self.args.approve:
            with self.approval_lock:
                print(f"\n[APPROVAL] #{command['id']} {kind}: {payload[:500]}")
                answer = input("Run this on this machine? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return "refused: declined on the device"
        return None

    def execute(self, command):
        kind = command["kind"]
        payload = command.get("payload", "")
        refusal = self.guard(command)
        if refusal:
            return "failed", refusal
        if kind == "ping":
            return "done", f"pong from {socket.gethostname()}"
        if kind == "sysinfo":
            return "done", json.dumps(self.system_info(), indent=2)
        if kind == "list_agents":
            return "done", json.dumps(self.detect_agents(), indent=2)
        if kind == "agent_task":
            if not self.args.allow_agent:
                return "failed", "agent tasks are disabled on this device (start bridge with --allow-agent)"
            return self.run_process(self.agent_argv(payload), shell=False, timeout=self.args.task_timeout)
        if kind == "shell":
            if not self.args.allow_shell:
                return "failed", "shell is disabled on this device (start bridge with --allow-shell)"
            return self.run_process(payload, shell=True, timeout=self.args.task_timeout)
        return "failed", f"unknown command kind: {kind}"

    def handle(self, command):
        print(f"-> #{command['id']} {command['kind']} {command.get('payload', '')[:60]}")
        try:
            status, result = self.execute(command)
        except subprocess.TimeoutExpired:
            status, result = "failed", f"timed out after {self.args.task_timeout}s"
        except FileNotFoundError as error:
            status, result = "failed", f"program not found: {error}"
        except Exception as error:
            status, result = "failed", f"error: {error!r}"
        if len(result) > MAX_RESULT_CHARS:
            result = "...(truncated)\n" + result[-MAX_RESULT_CHARS:]
        try:
            self.audit(command, status, result if status == "failed" else "")
        except OSError as error:
            print(f"   could not write audit log: {error}")
        try:
            self.request("POST", "/api/agent/result", {"id": command["id"], "status": status, "result": result})
        except (urllib.error.URLError, OSError) as error:
            print(f"   could not report result: {error}")
        print(f"<- #{command['id']} {status}")
        with self.lock:
            self.running_ids.discard(command["id"])

    # ------------------------------------------------------------ main loop

    def heartbeat(self):
        info = self.system_info()
        info["agents"] = self.detect_agents()
        return self.request("POST", "/api/agent/heartbeat", {"info": info})

    def heartbeat_forever(self):
        """Process discovery can take seconds on Windows, so it runs off the poll loop."""
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            try:
                self.heartbeat()
            except urllib.error.HTTPError as error:
                print(f"heartbeat rejected ({error.code})")
            except (urllib.error.URLError, OSError) as error:
                print(f"heartbeat failed ({error})")

    def loop(self):
        hello = self.heartbeat()
        print(f"Connected to {self.server} as device '{hello.get('device')}'")
        print(f"agent tasks: {'ON' if self.args.allow_agent else 'off'} | shell: {'ON' if self.args.allow_shell else 'off'}"
              f" | approve: {'ON' if self.args.approve else 'off'} | shell allowlist: {self.shell_allow or 'none'}")
        print(f"audit log: {self.args.audit_log}")
        threading.Thread(target=self.heartbeat_forever, daemon=True).start()
        workers = []
        while True:
            try:
                poll = self.request("GET", "/api/agent/poll")
                server_time = poll.get("server_time", int(time.time()))
                for command in poll.get("commands", []):
                    command["_age"] = max(0, server_time - command.get("created", server_time))
                    with self.lock:
                        self.running_ids.add(command["id"])
                    worker = threading.Thread(target=self.handle, args=(command,), daemon=True)
                    worker.start()
                    workers.append(worker)
            except urllib.error.HTTPError as error:
                if error.code == 401:
                    sys.exit("Device key rejected - was this device deleted in the app?")
                print(f"server error {error.code}, retrying")
            except (urllib.error.URLError, OSError) as error:
                print(f"connection problem ({error}), retrying")
                time.sleep(5)
            if self.args.once:
                for worker in workers:
                    worker.join(timeout=self.args.task_timeout)
                return
            time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="VibeHQ device bridge")
    parser.add_argument("--server", default=os.environ.get("VIBEHQ_SERVER", "http://127.0.0.1:8787"))
    parser.add_argument("--key", default=os.environ.get("VIBEHQ_DEVICE_KEY"), help="device key from the app")
    parser.add_argument("--workdir", default=os.getcwd(), help="folder where tasks run")
    parser.add_argument("--allow-agent", action="store_true", help="allow remote agent tasks")
    parser.add_argument("--agent-cmd", default="claude -p", help="agent CLI; the prompt is appended as last arg")
    parser.add_argument("--allow-shell", action="store_true", help="allow remote shell commands (dangerous)")
    parser.add_argument("--task-timeout", type=int, default=900, help="seconds before a task is killed")
    parser.add_argument("--approve", action="store_true", help="ask y/N here before every agent task or shell command")
    parser.add_argument("--shell-allow", default="", help='allowed shell prefixes, e.g. "git status,npm test"')
    parser.add_argument("--max-age", type=int, default=600, help="refuse risky commands queued longer than this (s)")
    parser.add_argument("--audit-log", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "vibehq-audit.log"),
                        help="append-only local log of every command")
    parser.add_argument("--once", action="store_true", help="poll once and exit (testing)")
    args = parser.parse_args()
    if not args.key:
        parser.error("--key is required (create a device in the Agents tab)")
    Bridge(args).loop()


if __name__ == "__main__":
    main()
