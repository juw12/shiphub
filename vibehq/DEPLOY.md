# Deploying vibeHQ (≈30 minutes)

Target: one small Linux VPS (1 vCPU / 1 GB RAM is plenty for the first few hundred users),
Docker, and a domain. Caddy gets HTTPS certificates automatically.

## 1. Server + domain
1. Create a VPS (Hetzner, DigitalOcean, Vultr, Lightsail…) with Ubuntu 24.04.
2. Point a DNS **A record** (e.g. `vibehq.example.com`) at the server's IP.
3. Install Docker: `curl -fsSL https://get.docker.com | sh`
4. Open ports 80 and 443 in the provider's firewall.

## 2. Copy the app and configure
```bash
scp -r vibehq/ root@YOUR_SERVER:/opt/vibehq     # or git clone your repo
cd /opt/vibehq
cp .env.example .env
nano .env
```
Minimum `.env`:
```
DOMAIN=vibehq.example.com
PUBLIC_URL=https://vibehq.example.com
VAPID_SUBJECT=mailto:you@example.com
```
Leave Stripe/GitHub empty at first. The app runs in demo-payments mode and is fully usable.

## 3. Start
```bash
docker compose up -d --build
docker compose logs -f app          # watch startup
curl https://vibehq.example.com/api/health
```
Open the site, register the first account, set a **command PIN** in Profile → Security.

## 4. Turn on integrations (any time)
| Feature | Steps |
|---|---|
| GitHub login | github.com/settings/developers → New OAuth App → callback `https://DOMAIN/api/auth/github/callback` → put ID/secret in `.env` |
| Stripe (test first!) | Dashboard → API keys → `STRIPE_SECRET_KEY=sk_test_…`; enable **Connect** (Express); Webhooks → endpoint `https://DOMAIN/api/stripe/webhook`, events `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `account.updated` → `STRIPE_WEBHOOK_SECRET=whsec_…` |
| Phone push | Works automatically over HTTPS. iPhone users: Share → Add to Home Screen first |

After editing `.env`: `docker compose up -d` (recreates the app container).

## 5. Backups
```bash
# nightly hot backup at 03:00, keeps 14 copies inside the data volume
echo '0 3 * * * cd /opt/vibehq && docker compose exec -T app python backup.py' | crontab -
# copy them off the server too (example)
docker compose cp app:/data/backups ./backups
```

## 6. Updating
```bash
cd /opt/vibehq && git pull     # or copy new files
docker compose up -d --build
```
Schema changes are applied automatically on startup (in-place migrations). Back up first.

## 7. Connect devices
On each machine you want to monitor:
```bash
python agent.py --server https://DOMAIN --key vhq_xxx
# allow agent tasks, but ask on this machine before each one:
python agent.py --server https://DOMAIN --key vhq_xxx --allow-agent --approve --agent-cmd "claude -p" --workdir ~/code/app
```

## Security checklist before inviting people
- [ ] HTTPS works and `PUBLIC_URL` starts with `https://`
- [ ] `.env` is not committed anywhere (`chmod 600 .env`)
- [ ] You set a command PIN on your own account
- [ ] Stripe in **test mode** until you've done a full test purchase + payout
- [ ] Backups run and you've tried restoring one (`cp backup.db /data/vibehq.db` with the app stopped)

## Limits of this setup
- One process + SQLite: great to ~hundreds of concurrent users. Beyond that: Postgres, Redis pub/sub for live events and rate limits, and multiple app instances.
- Rate limits are in-memory and reset on restart.
