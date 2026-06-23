---
name: hermes-whatsapp-gateway
description: Configure, pair, verify, and troubleshoot the Hermes Gateway WhatsApp
  platform (Baileys bridge).
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - whatsapp
    - gateway
    - baileys
    - qr-pairing
    - troubleshooting
    - hermes
    created_by: agent
    related_skills:
    - hermes-agent
    - hermes-email-gateway
    config:
    - key: hermes-whatsapp-gateway.enabled
      description: Enable hermes-whatsapp-gateway skill behavior
      default: true
      prompt: Enable hermes-whatsapp-gateway skill?
    category: productivity
platforms:
- linux
- macos
- windows
---
---

# Hermes WhatsApp Gateway

Use this skill when setting up or diagnosing the Hermes Gateway **WhatsApp** platform. Hermes connects via a built-in **Baileys** bridge (a Node.js process emulating a WhatsApp Web "linked device") — **not** the official WhatsApp Business API. No Meta account is needed. Authoritative docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp

There's a separate **WhatsApp Business Cloud API** adapter (official, no ban risk, needs Meta Business account + public webhook URL). This skill is for the Baileys bridge.

## Prerequisites
- **Node.js v18+ and npm** — the bridge runs as a Node process.
- A phone with WhatsApp installed to scan the QR code.
- No Chromium/Puppeteer needed (current bridge is Baileys-based, not browser-driven).

## Two modes
| Mode | How it works | Best for |
|------|-------------|----------|
| **bot** (recommended) | Dedicate a phone number to the bot; people message it directly. Lower ban risk. | Clean UX, multiple users |
| **self-chat** | Use your own WhatsApp; message yourself to talk to the agent. | Quick single-user test |

⚠️ Unofficial API → small ban risk. Use a **dedicated number** for bot mode, keep usage conversational, don't cold-message strangers.

## Core workflow
1. **Resolve the active HERMES_HOME first** (see pitfall below) — config, `.env`, logs, and the WhatsApp session all live under it, which may NOT be `~/.hermes`.
2. **Stage config in `.env`** (do not print secrets):
   ```
   WHATSAPP_ENABLED=true
   WHATSAPP_MODE=bot                  # or self-chat
   WHATSAPP_ALLOWED_USERS=1XXXXXXXXXX # comma-separated, country code, NO + or spaces
   # or WHATSAPP_ALLOWED_USERS=*  /  WHATSAPP_ALLOW_ALL_USERS=true to allow everyone
   ```
   The allowlist is **who may message the bot** (the user's *personal* number they'll text *from*), NOT the bot's own number. Without an allowlist set, the gateway denies all incoming messages.
3. **Optional: silence strangers** in `config.yaml`:
   ```yaml
   whatsapp:
     unauthorized_dm_behavior: ignore   # default global is "pair" (sends a pairing code)
   ```
   `ignore` is usually right for a private number. Edit the EXISTING `whatsapp:` key — don't append a duplicate (see pitfall).
4. **Pair via QR — interactive, user must do it themselves:** `hermes whatsapp`. Prints a QR code; on the bot phone: WhatsApp → Settings → Linked Devices → Link a Device → scan. Wait for the wizard to print "connected" and exit on its own; closing early aborts pairing. QR refreshes ~20s; needs a ≥60-column Unicode terminal.
5. **Restart the gateway** so it loads the new env: `hermes gateway restart`. A gateway that was already running snapshots env at startup and will NOT pick up `WHATSAPP_ENABLED=true` until restarted.
6. **Verify** (see checklist). The tell-tale of success is a `session/` directory appearing under `$HERMES_HOME/platforms/whatsapp/` (next to `pairing/`).

## Pitfalls

### Pairing silently fails if bridge node_modules aren't installed
The bridge lives at `<hermes install>/scripts/whatsapp-bridge/` (e.g. `/opt/hermes/scripts/whatsapp-bridge/`). If its `node_modules/` is missing, `hermes whatsapp` tries to install deps on first run and can hang/error before ever showing a usable QR — so no session is saved and the user thinks they paired when they didn't. **Pre-install to de-risk:**
```bash
cd <hermes install>/scripts/whatsapp-bridge
npm install --no-audit --no-fund      # ~20s; pulls Baileys from a git dep
ls node_modules/@whiskeysockets/baileys   # verify
```
`npm install` for this bridge routinely exceeds 60s on a cold cache (git dependency on WhiskeySockets/Baileys) — run it backgrounded or with a generous timeout, never assume a 60s timeout means failure.

### HERMES_HOME may not be ~/.hermes — find it before looking for session/logs
Containerized/managed installs set `HERMES_HOME` (and `HOME`) to a project dir like `/opt/data`, so config/`.env`/logs/sessions live there, NOT `~/.hermes`. Multiple `.hermes` dirs may exist and mislead you. Resolve it authoritatively:
```bash
tr '\0' '\n' < /proc/$(pgrep -f 'hermes gateway run'|head -1)/environ | grep -E 'HERMES_HOME|^HOME='
hermes config path        # prints the active config.yaml path
hermes config env-path    # prints the active .env path
```
Then check `$HERMES_HOME/platforms/whatsapp/session`, `$HERMES_HOME/logs/gateway.log`, etc. Looking in `~/.hermes` on such a host yields empty/stale results and false "it didn't work" conclusions.

### Don't create a duplicate `whatsapp:` YAML key
Fresh configs often already contain `whatsapp: {}`. Appending a new `whatsapp:` block makes a duplicate top-level key (invalid/ambiguous YAML). Replace the existing `whatsapp: {}` in place instead. The `patch` tool refuses to edit Hermes config files ("security-sensitive configuration"); use the terminal (with approval) or `hermes config set`. Validate with a Python that has PyYAML — the bare `python3` may lack the `yaml` module; use the Hermes venv python (e.g. `/opt/hermes/.venv/bin/python -c "import yaml,sys;yaml.safe_load(open('config.yaml'))"`).

### .env is read-protected from file tools
`read_file` refuses the Hermes `.env` ("credential store"). Inspect non-secret keys via terminal `grep` (report presence only, never echo secret values).

## Troubleshooting (Jim's OrbStack/Docker setup)

Five failure modes confirmed in production — diagnostic sequence, per-mode fix,
and key paths documented in:
`references/whatsapp-reconnect-troubleshooting.md`

**TL;DR decision tree:**

> **First stop for any unexplained ~150ms failure:** check the s6-log, NOT just gateway.log.
> `gateway.log` only captures Python `logger.*()` calls; `connect()` uses bare `print()` for npm/bridge
> messages that only appear in `/opt/data/logs/gateways/default/current`.

1. `bridge.log` says `device_removed` / `Logged out` → re-pair (fresh QR)
2. `gateway.log` says `bridge_exited (code -15)` → Watchtower killed it → fix perms + re-pair
3. `creds.json` exists, bridge connects manually but gateway fails → path mismatch → symlink fix
4. Bridge healthy (`/health` returns `{"status":"connected"}`) but gateway still fails → restart gateway
5. `npm install EACCES` → root-owned bridge dir → `chown -R hermes:hermes` as root first
6. Gateway still fails ~170ms after npm install → **double-chown**: npm re-owned `node_modules/` as root → chown `node_modules/` separately (see pitfall 3a)
7. s6-log shows `[Whatsapp] npm install failed: ` (empty error) AND ~150ms failure → **root-owned symlink**: npm tries to `unlink()` the symlink and fails; `ls -la node_modules` — if `lrwxrwxrwx 1 root root`, fix with `chown -h hermes:hermes` (see pitfall 3b)
8. Reconnect attempts take 60+ seconds → **missing pkg-hash stamp** → write it manually (see pitfall 3c)
9. s6-log shows `Installing...` + `npm install failed:` even though stamp file exists → **wrong-length stamp**: manually written stamps often contain full 64-char sha256 but gateway compares against `hexdigest()[:16]` (16 chars only) — always mismatches → fix: rewrite stamp with `hashlib.sha256(pkg.read_bytes()).hexdigest()[:16]` (see pitfall 3c)

**Permanent Watchtower-proof fix — DEPLOYED (Jun 20 2026):** store `node_modules` in `/opt/data/whatsapp/bridge_modules/` (persistent volume) and symlink into the bridge dir. Survives image updates. Full recipe in `references/whatsapp-reconnect-troubleshooting.md` under "Permanent fix".

**Deployment state:** The fix is live. `/opt/data/scripts/whatsapp-bridge-fix.sh` is mounted into the container as `/etc/cont-init.d/03-whatsapp-bridge-fix` via the `docker-compose.yml` volume entry `~/.hermes/scripts/whatsapp-bridge-fix.sh:/etc/cont-init.d/03-whatsapp-bridge-fix`. The s6 init script recreates the symlink (`/opt/hermes/scripts/whatsapp-bridge/node_modules` → `/opt/data/whatsapp/bridge_modules`) and rewrites the 16-char pkg-hash stamp on every container boot before the gateway starts. No action needed after Watchtower updates.

**Agent cannot self-restart the gateway** — all interactive commands (QR, npm, restart)
must come from a Mac host terminal via `docker exec -it hermes ...`

**Known WhatsApp group IDs:**
- **TO Changes** (USAW meet coordination) = `120363426893630875@g.us`
- Jim's home/personal channel = `120363409212843238@g.us` ⚠️ this is NOT the TO Changes group
- Kelly's group = `120363408898559658@g.us`

**To identify an unknown group ID:** send a test ping (`{"chatId": "<id>@g.us", "message": "test"}`), then ask the user which group it landed in. The bridge log at `/opt/data/whatsapp/bridge.log` also shows outbound `chatId` values for recently sent messages.

**`link-preview-js` missing — URL previews silently fail:**
The Baileys bridge depends on `link-preview-js` to generate rich link previews when messages contain URLs. If the package is absent, the bridge logs `"url generation failed"` warnings (level 40) for every outgoing URL message but continues sending — messages arrive as plain text with no preview card. This is a persistent-volume issue: `bridge_modules/package.json` may be read-only after the s6 init script recreates it.

Fix:
```bash
chmod u+w /opt/data/whatsapp/bridge_modules/package.json
cd /opt/data/whatsapp/bridge_modules && npm install link-preview-js
```
Then restart the bridge process (kill the PID — the gateway respawns it):
```bash
kill -TERM $(pgrep -f 'whatsapp-bridge/bridge.js')
# wait ~8s, then verify new PID has no "url generation failed" in bridge.log
```
To verify the fix took hold — check the NEW process PID's log entries only:
```bash
tail -20 /opt/data/whatsapp/bridge.log | grep -v '"pid":<OLD_PID>'
```
No `url generation failed` lines from the new PID = fixed.

**Bridge REST API field name is `chatId`, not `to`:** The Baileys bridge listens on port 3000. The correct POST body is `{"chatId": "<jid>", "message": "<text>"}` — using `"to"` returns `400 {"error":"chatId and message are required"}`. Verified working shape:
```bash
curl -s -X POST http://localhost:3000/send \
  -H "Content-Type: application/json" \
  -d '{"chatId":"120363409212843238@g.us","message":"your message"}'
# → {"success":true,"messageId":"...","messageIds":["..."]}
```
From Python: `requests.post("http://localhost:3000/send", json={"chatId": jid, "message": text})`.

## Verification checklist
- [ ] `$HERMES_HOME` resolved from the running gateway's env, not assumed.
- [ ] Bridge `node_modules/@whiskeysockets/baileys` present.
- [ ] `.env` has `WHATSAPP_ENABLED=true`, a `WHATSAPP_MODE`, and an allowlist (specific number, `*`, or allow-all flag).
- [ ] `config.yaml` has a single `whatsapp:` key, valid YAML.
- [ ] After scanning QR, `$HERMES_HOME/platforms/whatsapp/session/` exists (credentials saved). `chmod 700` it.
- [ ] Gateway restarted AFTER env changes; `gateway.log` shows WhatsApp/Baileys connection lines.
- [ ] Live test: from an allowlisted phone, message the bot number; reply arrives (prefixed "⚕ Hermes Agent" by default unless `whatsapp.reply_prefix` is customized/disabled).

## Re-pairing
If the session breaks (phone reset, WhatsApp protocol update, manual unlink), gateway logs show connection errors. Re-run `hermes whatsapp` for a fresh QR. After a WhatsApp Web protocol change, update Hermes (refreshes the bridge dep) then re-pair.
