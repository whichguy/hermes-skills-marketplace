---
name: hermes-whatsapp-gateway
description: Configure, pair, verify, and troubleshoot the Hermes Gateway WhatsApp
  platform (Baileys bridge).
version: 1.2.0
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

### Pitfall: using the wrong phone number for pairing
When generating a phone-number pairing code (Method 3), you must pass the **bot's own phone number** to `requestPairingCode()`, not the user's personal number from the allowlist. The allowlist (`WHATSAPP_ALLOWED_USERS`) controls who can *message* the bot; the bot's number is the one the bridge is paired to. Using the user's personal number generates a code that tries to link a device to the *user's* WhatsApp account, not the bot's — the user will see the code appear under the wrong WhatsApp account and pairing fails. Always check `session.dead-*/creds.json` for the bot's JID if unsure.

### .env is read-protected from file tools
`read_file` refuses the Hermes `.env` ("credential store"). Inspect non-secret keys via terminal `grep` (report presence only, never echo secret values).

### Docker overlay keeps the bridge in the image
The local security overlay makes `/opt/hermes/scripts/whatsapp-bridge/` writable by the `hermes` user, bakes and stamps `node_modules`, and causes `resolve_whatsapp_bridge_dir()` to use the image path directly. `/opt/data` persists the WhatsApp session, not Node dependencies. If the live command uses `${HERMES_HOME}/scripts/whatsapp-bridge/bridge.js`, treat that as a regression in image ownership or the package stamp; rebuild the overlay instead of recreating persistent module symlinks.

### Pitfall: WhatsApp account restriction from automated activity
The Baileys bridge is an **unofficial API**. WhatsApp will temporarily restrict accounts (~6h ban) that show automated/bulk messaging patterns. This was triggered Jun 2026 by repeated re-pair attempts + rapid test messages. During restriction: can reply to existing chats but cannot start new ones. **Prevention:** rate-limit outgoing messages (30s min between sends), no rapid re-pairing (wait 30 min between attempts), test gently (one message, wait 5 min). For production use, migrate to WhatsApp Cloud API (official, no ban risk). A `no_agent` watchdog cron (`whatsapp-bridge-health-watch.py`, every 15m, delivers to Slack) alerts when the bridge is down — see `scripts/` if available.

### Pitfall: missing link-preview-js / cheerio causes device_removed cascade
The local overlay installs `link-preview-js` and `cheerio` into `/opt/hermes/scripts/whatsapp-bridge/node_modules` and tests their imports during the image build. If either is missing, rebuild `hermes-agent:stable` with `~/.hermes/scripts/update-hermes-overlay.sh`; do not install packages into `/opt/data`.

## Troubleshooting (Jim's OrbStack/Docker setup)

Five failure modes confirmed in production — diagnostic sequence, per-mode fix,
and key paths documented in:
`references/whatsapp-reconnect-troubleshooting.md`

**Bridge remediation (Jun 2026)** — image-layer dependency ownership,
missing `link-preview-js`/`cheerio` → `device_removed` cascade, and account restriction:
`references/whatsapp-bridge-remediation.md`

**Bridge health watchdog script** — `no_agent` cron script that checks bridge health
every 15m and alerts to Slack with re-pairing instructions when down:
`scripts/whatsapp-bridge-health-watch.py`

**TL;DR decision tree:**

> **First stop for any unexplained ~150ms failure:** check the s6-log, NOT just gateway.log.
> `gateway.log` only captures Python `logger.*()` calls; `connect()` uses bare `print()` for npm/bridge
> messages that only appear in `/opt/data/logs/gateways/default/current`.

1. `bridge.log` says `device_removed` / `Logged out` → re-pair (fresh QR via `hermes whatsapp`)
2. `gateway.log` says `bridge_exited (code -15)` → Watchtower killed it → fix perms + re-pair
3. `creds.json` exists, bridge connects manually but gateway fails → verify the live process uses `/opt/hermes/scripts/whatsapp-bridge/bridge.js`
4. Bridge healthy (`/health` returns `{"status":"connected"}`) but gateway still fails → restart gateway
5. Gateway logs `Installing WhatsApp bridge dependencies` → the image stamp or ownership is wrong; rebuild the overlay rather than mutating `/opt/data`
6. ESM import failure → verify the dependency exists under `/opt/hermes/scripts/whatsapp-bridge/node_modules`
7. Bridge connected for ~9 min then `device_removed` → verify `link-preview-js`/`cheerio` imports in the image and inspect account restrictions
8. Bridge healthy (`/health` → `{"status":"connected"}`) but `hermes gateway status` still shows `⚠ whatsapp: not paired` → **gateway permanently dropped WhatsApp from retry queue** (non-retryable error from missing creds.json). `hermes gateway restart` from Mac host is the only fix. See "Pitfall: gateway drops WhatsApp from its retry queue permanently" above.

**Permanent fix — DEPLOYED (Jun 29 2026):** the local security overlay owns the complete bridge dependency tree. Its build installs patched Node packages, runs imports/tests/audits, writes the 16-character package stamp, and chowns the bridge to `hermes`. Compose no longer mounts `whatsapp-bridge-fix.sh`, and no `node_modules` or `bridge_modules` directory should exist under `/opt/data`.

**Agent cannot self-restart the gateway** — `hermes gateway restart` is blocked from inside the running gateway process (SIGTERM propagation). However, the agent CAN: generate pairing codes, start the bridge manually to verify the session, and deliver pairing instructions to the user. The agent should do all of this autonomously and then instruct the user to run `docker exec -it hermes /opt/hermes/bin/hermes gateway restart` from the Mac host as the final step.

**Known WhatsApp group IDs:**
- **TO Changes** (USAW meet coordination) = `YOUR_WHATSAPP_GROUP_ID`
- Jim's home/personal channel = `YOUR_WHATSAPP_GROUP_ID` ⚠️ this is NOT the TO Changes group
- Family Member's group = `YOUR_WHATSAPP_GROUP_ID`

**To identify an unknown group ID:** send a test ping (`{"chatId": "<id>@g.us", "message": "test"}`), then ask the user which group it landed in. The bridge log at `/opt/data/whatsapp/bridge.log` also shows outbound `chatId` values for recently sent messages.

**`link-preview-js` missing — URL previews silently fail:**
The Baileys bridge depends on `link-preview-js` to generate rich link previews when messages contain URLs. If the package is absent, the bridge logs `"url generation failed"` warnings (level 40) for every outgoing URL message but continues sending — messages arrive as plain text with no preview card. Worse, the missing `cheerio` dependency of `link-preview-js` can cascade into `device_removed`. In the current deployment this indicates a bad or stale overlay image.

Fix:
```bash
cd /opt/data
./scripts/update-hermes-overlay.sh
docker exec hermes sh -lc 'cd /opt/hermes/scripts/whatsapp-bridge && node -e '\''Promise.all([import("link-preview-js"),import("cheerio")]).then(()=>console.log("ok"))'\'''
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

**Bot's dedicated phone number (Jim's setup):** The bridge is paired to a **dedicated bot number**, NOT Jim's personal number. The bot number is **19252760266** (display name "Jeeves"). The allowlist (`WHATSAPP_ALLOWED_USERS=19255770755,19253360644`) lists the numbers allowed to *message* the bot — those are Jim's and Family Member's personal numbers. When generating a pairing code, you must use the bot's number (19252760266), not the personal numbers from the allowlist. Check the dead session's `creds.json` to confirm: `cat /opt/data/whatsapp/session.dead-*/creds.json | python3 -c "import sys,json; print(json.load(sys.stdin).get('me'))"`.

**Bridge REST API field name is `chatId`, not `to`:** The Baileys bridge listens on port 3000. The correct POST body is `{"chatId": "<jid>", "message": "<text>"}` — using `"to"` returns `400 {"error":"chatId and message are required"}`. Verified working shape:
```bash
curl -s -X POST http://localhost:3000/send \
  -H "Content-Type: application/json" \
  -d '{"chatId":"YOUR_WHATSAPP_GROUP_ID","message":"your message"}'
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
- [ ] `link-preview-js` + `cheerio` import from `/opt/hermes/scripts/whatsapp-bridge`; no dependency tree exists under `/opt/data`.

## Re-pairing
If the session breaks (phone reset, WhatsApp protocol update, manual unlink), gateway logs show connection errors. Re-run `hermes whatsapp` for a fresh QR. After a WhatsApp Web protocol change, update Hermes (refreshes the bridge dep) then re-pair.

### Re-pairing from the Mac host via Docker CLI (PREFERRED)

When the session dies, the cleanest re-pairing path is from the **Mac host terminal** via `docker exec -it hermes ...`. This uses the gateway's own bridge process and Baileys version, avoiding the session-rejection pitfall (see below).

**Step 1 — Clear the dead session:**
```bash
docker exec -it hermes rm -rf /opt/data/whatsapp/session/
```

**Step 2 — Pair using the gateway's own bridge (preferred, avoids version mismatch):**
```bash
docker exec -it hermes /opt/hermes/bin/hermes whatsapp
```
Prints a QR to the terminal. On the bot phone: WhatsApp → Settings → Linked Devices → Link a Device → scan. Wait for "connected" and the wizard to exit on its own.

**Step 3 — Restart the gateway:**
```bash
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

**Step 4 — Verify (~10s later):**
```bash
docker exec -it hermes curl -s http://localhost:3000/health
# → {"status":"connected"}
```

### Pitfall: gateway drops WhatsApp from its retry queue permanently after "not paired"
When the gateway starts and `creds.json` doesn't exist, the WhatsApp adapter raises a **non-retryable** error (`whatsapp_not_paired`). The reconnect watcher (`_platform_reconnect_watcher` in `gateway/run.py`) then removes WhatsApp from `_failed_platforms` entirely — it will **never** automatically retry, even after creds.json is later created by a successful pairing. This means:
- After pairing succeeds (QR or phone code), the gateway still shows `⚠ whatsapp: WhatsApp enabled but not paired` in `hermes gateway status`.
- The bridge may be running and healthy (`GET /health` → `{"status":"connected"}`), but the gateway's Python adapter has no knowledge of it and won't route messages.
- **A gateway restart is mandatory** — not optional — to make the gateway create a fresh adapter and re-discover the WhatsApp platform.
- Confirm this is the issue in `gateway.log`: look for `"Reconnect whatsapp: non-retryable error (...), removing from retry queue"`.

### Re-pairing from inside the container (when `hermes whatsapp` is blocked)
`hermes whatsapp` and `hermes gateway restart` are blocked from inside the running gateway process (the gateway would SIGTERM the child command). If you are running inside the container (e.g., as a Hermes agent session or cron job), you can run the bridge directly to generate a QR or pairing code.

⚠️ **Prefer `hermes whatsapp` from the Mac host** when possible — it pairs through the gateway's own bridge process, avoiding Baileys version mismatch that caused "Logged out" loops after Watchtower updates.

**After pairing succeeds from inside the container, start the bridge manually to verify the session before asking the user to restart the gateway:**
```bash
# Start the bridge in full server mode (background, via terminal background=true)
cd /opt/data/whatsapp/bridge
WHATSAPP_MODE=bot WHATSAPP_ALLOWED_USERS=<allowlist> \
  node bridge.js --port 3000 --session /opt/data/whatsapp/session
# Wait ~8s, then check:
curl -sf http://localhost:3000/health
# → {"status":"connected","queueLength":0,...}
```
This confirms the session credentials are valid before the gateway restart. The gateway restart (from the Mac host) will replace this manually-started bridge with its own s6-managed one.

**Method 1 — Bridge pair-only mode (ASCII QR in terminal):**
```bash
# 1. Delete the dead session credentials
rm -f /opt/data/whatsapp/session/creds.json

# 2. Run the bridge in pair-only mode (generates QR, saves creds, exits)
cd /opt/hermes/scripts/whatsapp-bridge
node bridge.js --pair-only --session /opt/data/whatsapp/session --port 3000
```
This prints a QR code to the terminal using `qrcode-terminal`. The QR refreshes ~20s. Once the user scans it and the bridge prints "connected", `creds.json` is saved and the process exits. The gateway's s6 supervisor will then respawn the bridge in full server mode automatically. Use `pty=true` in the terminal tool for the QR to render (needs ≥60 columns).
⚠️ See the version-mismatch pitfall above — if the gateway rejects this session, re-pair via `hermes whatsapp` from the Mac host instead.

**Method 2 — QR as PNG image (for Slack/messaging delivery):**
ASCII QR art does NOT render in Slack, Telegram, or other messaging platforms. When delivering a QR code to the user through a chat interface, you must capture the raw QR string and render it as a PNG image:

1. Write a small `.mjs` script that imports Baileys directly, captures the `qr` field from `connection.update`, and prints it as `QRSTRING:<raw_qr>`:
```javascript
// qr_capture.mjs — place in a writable dir with node_modules linked to the image bridge
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';
async function main() {
    const { state, saveCreds } = await useMultiFileAuthState('/opt/data/whatsapp/session');
    const { version } = await fetchLatestBaileysVersion();
    const sock = makeWASocket({ auth: state, version, printQRInTerminal: false, logger: pino({ level: 'silent' }) });
    sock.ev.on('connection.update', (u) => {
        if (u.qr) process.stdout.write('QRSTRING:' + u.qr + '\n');
        if (u.connection === 'open') { process.stdout.write('CONNECTED\n'); process.exit(0); }
    });
    sock.ev.on('creds.update', saveCreds);
    setTimeout(() => process.exit(1), 20000);
}
main();
```
2. Run it: `cd /opt/data/whatsapp/qr_workdir && timeout 15 node qr_capture.mjs 2>&1 | grep QRSTRING:`
   - The script dir must have `node_modules` linked to the image dependencies: `ln -sfn /opt/hermes/scripts/whatsapp-bridge/node_modules /opt/data/whatsapp/qr_workdir/node_modules`
   - Must be `.mjs` (ESM) — Baileys is an ESM-only package, `require()` fails with `ERR_REQUIRE_ASYNC_MODULE`
   - Keep generated QR helper files in `/opt/data`; only dependencies stay in the image
3. Render the QR string as PNG: `uv run --with qrcode --with Pillow python3 -c "import qrcode; qr=qrcode.QRCode(box_size=10,border=4); qr.add_data('<QRSTRING>'); qr.make(fit=True); img=qr.make_image(fill_color='black',back_color='white'); img.save('/opt/data/whatsapp_qr.png')"`
4. Deliver to user: include `MEDIA:/opt/data/whatsapp_qr.png` in your response. The image uploads as a photo attachment in Slack.
⚠️ **QR codes expire in ~20 seconds.** By the time a PNG is generated, delivered through Slack, and rendered on the user's screen, it may already be dead. If QR scanning fails with "Can't link new devices right now / Try again later" (WhatsApp rate-limiting from repeated QR attempts), switch to **Method 3** (phone-number pairing code) which doesn't require QR at all.

**Method 3 — Phone-number pairing code (no QR needed):**
When QR scanning is rate-limited or the user can't scan fast enough, Baileys supports `requestPairingCode(phoneNumber)` — the user enters a code manually instead of scanning. The user taps "Link with phone number instead" in WhatsApp → Linked Devices and enters the code.

1. Write a `.mjs` script that calls `sock.requestPairingCode(botPhoneNumber)`:
```javascript
// pair_code.mjs — place in same dir as qr_capture.mjs (needs node_modules symlink)
import { makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';
import { unlinkSync, existsSync } from 'fs';

async function main() {
    const credsPath = '/opt/data/whatsapp/session/creds.json';
    if (existsSync(credsPath)) unlinkSync(credsPath);
    const { state, saveCreds } = await useMultiFileAuthState('/opt/data/whatsapp/session');
    const { version } = await fetchLatestBaileysVersion();
    const sock = makeWASocket({ auth: state, version, printQRInTerminal: false, logger: pino({ level: 'silent' }) });
    let codeRequested = false;
    sock.ev.on('connection.update', async (update) => {
        if (update.qr && !codeRequested) {
            codeRequested = true;
            const phoneNumber = process.env.WHATSAPP_BOT_PHONE;
            if (!phoneNumber) { process.stdout.write('ERROR: Set WHATSAPP_BOT_PHONE\n'); process.exit(1); }
            const code = await sock.requestPairingCode(phoneNumber);
            const formatted = code.match(/.{1,3}/g)?.join('-') || code;
            process.stdout.write('PAIRCODE:' + formatted + '\n');
        }
        if (update.connection === 'open') { process.stdout.write('CONNECTED\n'); process.exit(0); }
    });
    sock.ev.on('creds.update', saveCreds);
    setTimeout(() => process.exit(0), 120000); // 2min for user to enter code
}
main();
```
2. Run it with the **bot's** phone number (NOT the user's personal number — see "Bot's dedicated phone number" above):
```bash
rm -f /opt/data/whatsapp/session/creds.json
cd /opt/data/whatsapp/qr_workdir
WHATSAPP_BOT_PHONE=19252760266 timeout 15 node pair_code.mjs 2>&1
# Output: PAIRCODE:XXX-XXX-XXX
```
3. Tell the user: **WhatsApp → Settings → Linked Devices → Link a Device → "Link with phone number instead" → enter the code**
4. The pairing code is live for the duration of the script's timeout. The bridge process stays alive waiting for the connection to open. If the code expires, just re-run the script for a fresh one.
   - **Default timeout in the script above: 120s (2 min)** — fine when a user is actively waiting.
   - **For unattended/cron scenarios** (agent generates code, delivers it to user via Slack/Telegram, user enters it on phone): increase the timeout to 300-600s. Replace `setTimeout(() => process.exit(0), 120000)` with `setTimeout(() => process.exit(0), 600000)` (10 min). The process stays alive waiting for the phone to complete pairing. When `connection.update` fires with `connection === 'open'`, the script prints `CONNECTED` and exits — even if the user takes several minutes to respond.
   - **Verify pairing success** by checking if session files appeared: `ls /opt/data/whatsapp/session/creds.json` — if it exists with a recent timestamp and 800+ accompanying session files, pairing succeeded even if the script timed out before printing `CONNECTED`.
5. ⚠️ **Must use the bot's own number** for `requestPairingCode()`, not the user's personal number. Using the wrong number generates a code under the wrong WhatsApp account and pairing fails silently.

Requirements for either method:
- A temporary work-dir `node_modules` symlink may point to `/opt/hermes/scripts/whatsapp-bridge/node_modules`; do not copy dependencies into `/opt/data`
- Node.js v18+ available in the container
- Dead session must be cleared first: `rm -f /opt/data/whatsapp/session/creds.json`
