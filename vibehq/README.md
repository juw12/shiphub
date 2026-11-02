# vibeHQ — the social HQ for vibe coders

One app for vibe coders worldwide to:

- **Monitor & command their own devices and AI coding agents.** It auto-detects running Claude Code, Codex, Cursor, Aider, Gemini CLI, Ollama, OpenCode, Goose and more. You can send tasks from anywhere, including your phone.
- **Share** ships, tips and news. A **✓ verified** badge appears when GitHub confirms that you actually shipped the repo.
- **Climb the ladder**: XP comes from ships, finished agent tasks, real GitHub pushes, sales and friendships. Ladders are global, per country and friends-only, all-time or weekly, with tiers from Bronze up to Legend.
- **Add friends and chat**: there's a world chat room plus DMs, delivered in realtime.
- **Sell** templates, prompts, agent configs, MCP servers and apps with **real Stripe Connect payouts**.
- **Install it as a phone app** with **push notifications**: agent finished, new sale, DMs, friend requests.

## How it compares to existing projects

| Project | Agent control | Social feed | Verified ladder | Chat & friends | Marketplace w/ payouts | Phone push |
|---|---|---|---|---|---|---|
| Multica, OpenChamber, T3 Code, claudecodeui | ✅ | – | – | team-only | – | some |
| viberank | – | – | tokens only | – | – | – |
| **vibeHQ** | ✅ (opt-in, device-side safety) | ✅ | ✅ GitHub-verified | ✅ | ✅ Stripe Connect | ✅ Web Push + ntfy |

## Run it (Python 3.9+, zero dependencies)

```powershell
python server.py --demo        # http://127.0.0.1:8787   (demo login: alice / demo1234)
```

With no `.env` file, everything works in demo mode: simulated payments and no GitHub login. To turn on the real integrations, copy `.env.example` to `.env` and fill it in:

| Feature | What you need |
|---|---|
| Real payments | Stripe secret key + webhook secret. Sellers onboard via **Market → Get paid** (Stripe Express). The platform keeps `PLATFORM_FEE_PERCENT`. |
| GitHub login / verified ships | A GitHub OAuth App (callback `{PUBLIC_URL}/api/auth/github/callback`) |
| Phone push | HTTPS `PUBLIC_URL`. VAPID keys are generated automatically on first run. |
| Phone alerts without HTTPS | Install the free **ntfy** app, subscribe to a secret topic, and enter it in **Profile → Edit profile** |

## Install on your phone

- **Android / desktop Chrome or Edge**: open the site, then Install app. Go to **Profile → Phone alerts → Enable push here**.
- **iPhone (iOS 16.4+)**: Safari → Share → **Add to Home Screen**. Open it from the home screen, then enable push.
- No HTTPS yet? Use ntfy: it works everywhere right away.

## Connect a device

1. In the app, open **Agents**, then **Add**. Copy the key; it's shown only once.
2. On that machine:

```powershell
python agent.py --server https://YOUR-SERVER --key vhq_xxx                         # monitor only
python agent.py --server https://YOUR-SERVER --key vhq_xxx --allow-agent --agent-cmd "claude -p" --workdir C:\code\app
```

Other agents work the same way: `--agent-cmd "codex exec"`, `"aider --yes -m"`, `"gemini -p"`.

## How verification works

- **Verified ship**: the post links a public GitHub repo that your linked account **owns or contributes to** and that was **pushed in the last 30 days**. It earns +50 bonus XP.
- **GitHub sync**: each public push in the last 7 days earns +3 XP, counted once per event and capped daily.
- GitHub access tokens are only used during login and are **never stored**.

## Security model

**Remote agent control (defense in depth)**
- Agent tasks and shell are **off by default**. They can only be enabled on the device itself (`--allow-agent`, `--allow-shell`).
- Sending them requires a separate **command PIN** (Profile → Security). A stolen login alone can't run code. After 5 wrong PINs, commands lock for 15 minutes.
- Every risky command triggers a 🛡️ alert on all your devices and phones.
- Optional device-side guards:
  - `--approve` asks y/N on the machine before each command.
  - `--shell-allow "git status,npm test"` restricts shell to those prefixes, with no chaining.
  - Commands queued longer than `--max-age` (10 min) are refused.
  - A local append-only `--audit-log` records every command.

**Accounts**
- Login tokens are stored only as SHA-256 hashes and expire after 30 idle days.
- You can see and revoke signed-in devices, and changing your password signs out everything else.
- Login is limited to 5 failures per account and 20 per IP per 15 minutes; sign-ups to 5 per IP per hour. Unknown users take the same time to reject (no username probing).
- The live event stream uses one-time 60-second tickets, so tokens never appear in URLs or logs.

**Web**
- CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, and HSTS on HTTPS.
- All SQL is parameterized, user content is escaped, and links must be http(s).

**Payments and push**
- Stripe webhooks are signature-checked (HMAC-SHA256, 5-minute tolerance) and processed idempotently. Delivery links are revealed only after payment.
- Push endpoints are restricted to known push services (SSRF guard). Pushes carry no payload; the app fetches text from your server.

**Known limits**
- Rate limits and stream tickets are in memory: they reset on restart and need Redis when running multiple instances.
- The VAPID signer (`webpush.py`) is pure Python and not constant-time. That's acceptable for short-lived server-side tokens.
- An agent task runs with whatever permissions the agent CLI has. Point `--workdir` at a project folder, not your home directory.

## Tests

```powershell
python tests/run_tests.py
```

This runs 79 end-to-end checks against local fakes of Stripe, GitHub, a push service and ntfy: OAuth, verified ships, Connect onboarding, checkout, webhook signatures and replay, push signing, ntfy, notifications, PWA assets and the device bridge.

## Deploy

See **DEPLOY.md**: Docker + Caddy (automatic HTTPS), backups, and a pre-launch checklist.

## Before a public launch

- Deploy behind HTTPS (Caddy or nginx), set `PUBLIC_URL`, and register the Stripe webhook.
- Move from SQLite to Postgres and add a shared pub/sub (Redis) once you run more than one server process.
- Add moderation and reporting, email verification, rate limits on sign-up, and Stripe refund/dispute handling.
- Review Stripe Connect and tax obligations for the countries you operate in.

## Files

- `server.py`: API, realtime events, XP engine, payments, OAuth, notifications
- `stripe_client.py`, `github_client.py`, `webpush.py`: zero-dependency integrations
- `agent.py`: device bridge
- `static/`: web app, service worker, manifest, icons
- `tests/run_tests.py`: end-to-end suite
