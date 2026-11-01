# shiphub

A Pinterest-style board of app ideas worth building, with forum threads,
builders ("I'm building this" → shipped, with repo + demo links), forks,
boards, notifications, GitHub sign-in and image uploads.

## Run it locally

Double-click `start.bat`, or:

```
python server.py
```

It opens http://127.0.0.1:8000 (or the next free port). Demo login: `demo` / `demo1234`.
Nothing to install: locally it uses SQLite in `data/shiphub.db`.

Useful flags: `--host 0.0.0.0` (share on your Wi-Fi), `--reset` (wipe + re-seed), `--no-browser`.

## Configuration

Copy `config.example.env` to `config.env` and fill in what you need. Environment
variables override the file. The important ones:

| Variable | What it does |
| --- | --- |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | Turns on "Continue with GitHub" |
| `DATABASE_URL` | `postgresql://…` to use Postgres instead of SQLite (`pip install -r requirements.txt`) |
| `PUBLIC_URL` | Your public `https://…` address (secure cookies, GitHub redirects) |
| `SHIPHUB_ADMINS` | Comma-separated usernames that can delete any idea or comment |
| `SHIPHUB_DEMO` | `1` locally; set `0` on a public site (sample accounts get random passwords, demo button hidden) |
| `SHIPHUB_MAX_UPLOAD_MB` | Upload limit for covers/avatars (default 5) |
| `TRUST_PROXY` | `1` behind Fly/Render/nginx so rate limits see the real client IP |

## GitHub sign-in

1. Go to https://github.com/settings/developers → **New OAuth App**.
2. Homepage URL: `http://127.0.0.1:8000` (or your public URL).
3. Authorization callback URL: `http://127.0.0.1:8000/auth/github/callback`
   (deployed: `https://YOUR-DOMAIN/auth/github/callback`).
4. Put the Client ID and a generated Client secret in `config.env` (or your host's secrets) and restart.

Signing in with GitHub creates an account (username from your GitHub login, plus
name, bio and avatar). Already have a password account? Use **Edit profile →
Connect your GitHub account** to link it.

## Image uploads

Cover images (button, drag-and-drop or paste in the composer) and profile photos.
The browser shrinks big photos to WebP before upload. The server accepts
PNG/JPEG/GIF/WebP only (checked by file signature, not the filename), stores them in
the database and serves them from `/uploads/…` with long cache headers and a
sandbox CSP.

## Deploy

The repo includes a `Dockerfile` (works on any Docker host), `render.yaml` and `fly.toml`.

**Render (free to start, easiest):** push this folder to a GitHub repo → Render
dashboard → **New → Blueprint** → pick the repo. It creates the web service and a
Postgres database. Then set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` and
`SHIPHUB_ADMINS` in the service's Environment tab.
Notes: free web services sleep after ~15 min idle (first visit takes a moment);
free Postgres expires after 30 days unless you upgrade.

**Fly.io (about $2–3/month, no free tier for new accounts):**

```
fly launch --copy-config --no-deploy     # pick a unique app name
fly volumes create shiphub_data --size 1
fly secrets set GITHUB_CLIENT_ID=... GITHUB_CLIENT_SECRET=... SHIPHUB_ADMINS=yourname
fly deploy
```

This keeps SQLite on the volume. For Postgres instead, set a `DATABASE_URL` secret.

Health check: `GET /healthz`.

## What's inside

- `server.py`: Python standard-library HTTP server + JSON API. SQLite or Postgres (same SQL, rewritten for Postgres).
  PBKDF2 passwords, HttpOnly session cookies, CSRF protection, rate limits on logins and writes, strict CSP, gzip + ETags.
  Old SQLite databases are upgraded automatically on startup.
- `static/`: framework-free single-page app (`index.html`, `app.js`, `app.css`, `theme.js`).

## Not done yet

Password reset by email, reporting/flagging content, and email notifications.
