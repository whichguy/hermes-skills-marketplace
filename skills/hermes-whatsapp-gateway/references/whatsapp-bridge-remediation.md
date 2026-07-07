# WhatsApp Bridge Remediation (Jun 2026)

## Root Cause Analysis

Three causes identified for repeated bridge session invalidation:

### 1. Watchtower Image Update → Baileys Version Mismatch
- Container hostname changes (e.g. `0d18826c774e` → `6862353ffcaa`)
- New image may include different Baileys version → protocol mismatch → `device_removed` (code 401)
- **Fix:** Use `hermes whatsapp` (gateway's own bridge) for re-pairing, not `bridge.js --pair-only` (standalone, may have different version)

### 2. Missing `link-preview-js` / `cheerio` → device_removed Cascade
- Image's `package.json` doesn't list `link-preview-js` or `cheerio`, but `bridge.js` uses them
- When a URL message is sent, `require('cheerio')` fails → error level 40 logs → cascades into `device_removed` within ~9 minutes of pairing
- **Current fix:** The security overlay installs and tests both packages in `/opt/hermes/scripts/whatsapp-bridge/node_modules` during image build.

### 3. Broken `node_modules` in Persistent Bridge Dir (historical)
- Gateway's `resolve_whatsapp_bridge_dir()` mirrors bridge code to `${HERMES_HOME}/scripts/whatsapp-bridge/` (persistent volume) when image dir is read-only
- That copy had a real `node_modules` directory (not a symlink to `bridge_modules/`), with a double-nested `node_modules/node_modules/` structure
- Package resolution failed silently
- **Current fix:** The overlay chowns the image bridge to `hermes`, writes the 16-character dependency stamp, and keeps the complete Node dependency tree in the image. The resolver now uses `/opt/hermes`; `/opt/data` keeps only session/user data.

## Current Overlay Architecture (Jun 29 2026)

`~/.hermes/docker/security-overlay/Dockerfile.security`:
1. Installs patched Baileys, `link-preview-js`, `cheerio`, `protobufjs`, and `ws` versions.
2. Runs ESM imports, bridge tests, and the high/critical audit gate.
3. Writes `node_modules/.hermes-pkg-hash` and owns the bridge as `hermes`.
4. Leaves `/opt/data/whatsapp/session` persistent while keeping Node dependencies ephemeral and replaceable with the image.

Do not recreate `/opt/data/whatsapp/node_modules`, `/opt/data/whatsapp/bridge_modules`, or the retired `whatsapp-bridge-fix.sh` mount. Rebuild with `~/.hermes/scripts/update-hermes-overlay.sh` when dependencies need patching.

## WhatsApp Account Restriction

The Jeeves bot number (925-276-0266) received a ~6h temporary restriction from WhatsApp
for suspected automated/bulk messaging. Triggered by repeated re-pair attempts + rapid
test messages.

**During restriction:**
- ✅ Can reply to existing chats/groups
- ❌ Cannot start new chats
- ⏱️ Timer shown on phone

**Prevention:**
- Rate-limit outgoing messages (30s min between sends, 5s between batch approvals)
- No rapid re-pairing (wait 30 min between attempts)
- Test gently (one message, wait 5 min before next)
- For production: migrate to WhatsApp Cloud API (official, no ban risk)

## Watchdog: `whatsapp-bridge-health-watch.py`

`no_agent` cron, every 15m, delivers to Slack. Checks:
- Bridge health endpoint (`GET localhost:3000/health`)
- Bridge log for `Logged out` / `device_removed` signals

Silent when healthy. Alerts with Docker CLI re-pairing instructions when down.
1h cooldown between same-type alerts.

State file: `/opt/data/cron/state/wa_bridge_health.json`

## Re-pairing (Recommended Path)

```bash
# From Mac host terminal:
docker exec -it hermes bash -c 'pkill -f "node.*bridge.js" || true'
docker exec -it hermes rm -rf /opt/data/whatsapp/session/
docker exec -it hermes /opt/hermes/bin/hermes whatsapp
# Scan QR on Jeeves phone → wait for "connected"
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
docker exec -it hermes curl -s http://localhost:3000/health
```

⚠️ Use `hermes whatsapp` (not `bridge.js --pair-only`) — pairs through the gateway's own
bridge process, avoiding Baileys version mismatch that caused "Logged out" loops.
