# WhatsApp Reconnect Troubleshooting (Jim's OrbStack/Docker setup)

## The recurring failure pattern (Jun 2026, confirmed)

### Symptom
Gateway stuck in reconnect loop: "Reconnect whatsapp failed, next retry in 300s"
— logged every 5 min indefinitely. `/health` never reached.

### Root causes found (in order of frequency)

#### 1. Device removed / session expired (401 conflict:device_removed)
```
stream errored out — {"tag":"conflict","attrs":{"type":"device_removed"}}
❌ Logged out. Delete session and restart to re-authenticate.
```
**Fix:** clear the dead session + re-pair.
```bash
# On Mac host:
mv /opt/data/whatsapp/session /opt/data/whatsapp/session.dead-$(date +%Y%m%d)
docker exec -it hermes /opt/hermes/bin/hermes whatsapp   # scan QR on bot phone
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

#### 2. Watchtower killed bridge mid-session (SIGTERM / exit code -15)
Watchtower auto-updates the container image during active use, sending SIGTERM to
the bridge. After the new image starts, the gateway's reconnect loop fails because
the bridge crashes on startup (root-owned `node_modules`).

**Tell-tale in gateway.log:**
```
Fatal whatsapp adapter error (whatsapp_bridge_exited): WhatsApp bridge process exited unexpectedly (code -15).
```
**Fix:** see item 3 (permissions) then restart gateway.

#### 3. Root-owned bridge dir blocks npm install (EACCES -13)
After a Watchtower image update, `/opt/hermes/scripts/whatsapp-bridge/` is owned
by root. The `hermes whatsapp` wizard tries `npm install` and fails:
```
npm error EACCES: permission denied, mkdir '/opt/hermes/scripts/whatsapp-bridge/node_modules'
```
**Fix (from Mac host, not from inside the agent):**
```bash
docker exec -it --user root hermes chown -R hermes:hermes /opt/hermes/scripts/whatsapp-bridge/
docker exec -it hermes bash -c "npm install --prefix /opt/hermes/scripts/whatsapp-bridge/ --no-audit --no-fund"
# ⚠️ See double-chown pitfall below before restarting
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

#### 3a. Double-chown pitfall — npm re-roots node_modules (confirmed Jun 2026)

**Symptom:** after running the fix above, gateway still fails immediately (~170ms
per reconnect attempt). `Reconnect whatsapp failed, next retry in 300s` continues
unchanged. Bridge JS file is found but the process crashes before connecting.

**Root cause:** `npm install` ran as root (via `docker exec --user root` or root
default), so `node_modules/` was **created fresh as root** even though the parent
`whatsapp-bridge/` dir is now `hermes:hermes`. The first `chown` fixed the static
files; `npm` then wrote new root-owned files on top.

**Diagnose:**
```bash
ls -la /opt/hermes/scripts/whatsapp-bridge/node_modules/
# If owner is root → this is the problem
```

**Fix — second targeted chown on node_modules only:**
```bash
docker exec -it --user root hermes \
  chown -R hermes:hermes /opt/hermes/scripts/whatsapp-bridge/node_modules/
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

**Correct final ownership (all three must be hermes:hermes):**
- `/opt/hermes/scripts/whatsapp-bridge/` → `hermes:hermes`
- `/opt/hermes/scripts/whatsapp-bridge/node_modules/` → `hermes:hermes`
- `/opt/hermes/scripts/whatsapp-bridge/node_modules/@whiskeysockets/baileys/` → `hermes:hermes`

**Shortcut to avoid this entirely:** run npm as hermes from the start:
```bash
docker exec -it --user root hermes chown -R hermes:hermes /opt/hermes/scripts/whatsapp-bridge/
docker exec -it hermes bash -c "npm install --prefix /opt/hermes/scripts/whatsapp-bridge/ --no-audit --no-fund"
# npm now runs as hermes → node_modules created as hermes:hermes in one pass
```

#### 3b. Root-owned symlink blocks npm even after node_modules chown (confirmed Jun 2026)

**Symptom:** after fixing node_modules ownership AND the pkg-hash stamp exists AND
`node --version` works AND bridge connects fine manually — gateway still fails in
~150ms. `Reconnect whatsapp failed, next retry in 300s` continues unchanged.
The s6-log (`/opt/data/logs/gateways/default/current`) shows:
```
[Whatsapp] Installing WhatsApp bridge dependencies...
[Whatsapp] npm install failed: 
```
Note the **empty error message** — `--silent` suppresses stderr, so the gateway
just sees a non-zero exit code with nothing to report.

**Root cause:** The `node_modules` entry in bridge dir is a **symlink pointing to
`/opt/data/whatsapp/bridge_modules`**. The symlink itself is `lrwxrwxrwx 1 root root`
— root-owned. npm's **reify algorithm** sees a symlink where it expects a directory
and calls `unlink()` on it to replace it with a real `node_modules/` directory.
`unlink` on a root-owned path fails with `EACCES -13` for the hermes user.
npm returns non-zero; `--silent` swallows stderr; gateway reports "npm install
failed: " (empty string) and returns `False` from `connect()` in ~141ms.

**Why does this trigger even though the pkg-hash stamp matches?** The stamp check
uses `Path("node_modules").exists()` — a symlink resolves as `True`, so the gateway
DOES check the stamp. If stamp matches, it skips npm. But: if npm was previously
run (by root, during a previous reconnect attempt), it may have overwritten the
stamp as root-owned, making it unreadable by hermes → `OSError` → `deps_fresh=False`
→ npm runs again → EACCES loop. Always check stamp ownership too:
```bash
ls -la /opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash
# Must be owned by hermes, not root
```

**Diagnose:**
```bash
ls -la /opt/hermes/scripts/whatsapp-bridge/node_modules
# Look at the SYMLINK ownership, not the target dir:
# lrwxrwxrwx 1 root root  33 Jun 20 03:02 node_modules -> /opt/data/whatsapp/bridge_modules
#              ^^^^ ^^^^  — root-owned symlink is the blocker
```

**Fix — chown the symlink itself:**
```bash
docker exec -it --user root hermes \
  chown -h hermes:hermes /opt/hermes/scripts/whatsapp-bridge/node_modules
# -h flag chowns the symlink itself, not its target
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

Or if the symlink was root-created and can't be chowned in place, recreate it:
```bash
docker exec -it --user root hermes bash -c "
  rm /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  ln -sfn /opt/data/whatsapp/bridge_modules /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  chown -h hermes:hermes /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  echo done
"
```

#### 3c. `.hermes-pkg-hash` stamp missing — gateway runs npm every connect attempt

**Symptom:** gateway reconnect attempts take 60+ seconds (instead of ~150ms for the
fast failures), always fail, loop at 300s intervals.

**Root cause:** The gateway writes a `.hermes-pkg-hash` stamp file inside `node_modules/`
after a successful `npm install`. If missing (e.g. node_modules was restored from a
backup, manually created, or installed in a non-standard way), the gateway runs a full
`npm install --silent` on every connect attempt. If npm fails for any reason (permissions,
network), the whole connect() returns False.

**Diagnose:**
```bash
ls /opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash
# "No such file" → stamp missing → gateway runs npm every time
```

**Fix — write the stamp manually:**
```bash
python3 -c "
import hashlib
from pathlib import Path
pkg = Path('/opt/hermes/scripts/whatsapp-bridge/package.json')
stamp = Path('/opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash')
# CRITICAL: gateway uses hexdigest()[:16] — only first 16 hex chars, NOT full 64-char hash
h = hashlib.sha256(pkg.read_bytes()).hexdigest()[:16]
stamp.write_text(h)
print(f'Stamp written: {h}')
"
```
Then restart the gateway.

⚠️ **CRITICAL: stamp must be 16 hex chars, not 64.** The gateway uses
`_file_content_hash()` which does `hashlib.sha256(...).hexdigest()[:16]` — only the
first 16 hex characters. If the stamp contains a full 64-char sha256 (written manually
or by an older script), the comparison `stamp_value == pkg_hash` always fails because
`"73e6336b402bec06b7b9c09caa4c31cd..."` ≠ `"73e6336b402bec06"`.

**Symptom of wrong-length stamp:** s6-log shows `[Whatsapp] Installing WhatsApp bridge
dependencies...` even though the stamp FILE EXISTS and was recently written. Running
`npm install` then fails (EACCES on the symlink), so every attempt fails in ~145ms.

**Diagnose:**
```bash
python3 -c "
import hashlib
from pathlib import Path
pkg = Path('/opt/hermes/scripts/whatsapp-bridge/package.json')
h16 = hashlib.sha256(pkg.read_bytes()).hexdigest()[:16]
stamp = Path('/opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash')
sv = stamp.read_text().strip()
print(f'Stamp  : {sv!r}  (len={len(sv)})')
print(f'Want   : {h16!r}  (len=16)')
print(f'Match  : {sv == h16}')
"
```

#### 4. Session path mismatch (whatsapp/session vs platforms/whatsapp/session)
The pairing wizard writes creds to `/opt/data/whatsapp/session/creds.json` but
the gateway (via `get_hermes_dir`) looks for it at
`/opt/data/platforms/whatsapp/session/creds.json`. These diverge when the
`HERMES_HOME` differs from what the bridge uses by default.

**Diagnose:**
```bash
# Run bridge manually with explicit session path — if it connects, the path is the issue:
timeout 8 node /opt/hermes/scripts/whatsapp-bridge/bridge.js \
  --session /opt/data/whatsapp/session --mode bot --port 3000
# If you see "✅ WhatsApp connected!" but gateway still fails → path mismatch

# Fix: symlink to where gateway expects it
mkdir -p /opt/data/platforms/whatsapp
ln -sfn /opt/data/whatsapp/session /opt/data/platforms/whatsapp/session
```
Then restart gateway.

#### 5. Bridge healthy but gateway startup race
The gateway polls `/health` for up to 15s in 1s intervals. If the bridge's Node
process needs slightly longer to authenticate (especially with a cold session),
the gateway times out and marks the platform failed.

**Diagnose:**
```bash
# Run bridge in background, then hit /health:
node /opt/hermes/scripts/whatsapp-bridge/bridge.js \
  --session /opt/data/whatsapp/session --mode bot --port 3000 &
sleep 5 && curl -s http://localhost:3000/health
# If returns {"status":"connected",...} — bridge is fine, gateway has a race
```
**Fix:** restart the gateway; on a clean start it gives the bridge a fresh 15s window.

---

## Permanent fix: persist node_modules to survive Watchtower updates

The root cause of issues 3–3c is that Watchtower replaces `/opt/hermes` on every
image update, wiping or root-re-owning node_modules. The permanent fix is to store
node_modules in `/opt/data` (the persistent volume) and symlink it into the bridge dir.

```bash
# One-time setup (from Mac host, as root):

# 1. Create persistent location in /opt/data
docker exec -it hermes mkdir -p /opt/data/whatsapp/bridge_modules

# 2. Install deps directly into the persistent location
#    (copy package.json there first so npm can find it)
docker exec -it hermes bash -c "
  cp /opt/hermes/scripts/whatsapp-bridge/package.json /opt/data/whatsapp/bridge_modules/ && \
  cp /opt/hermes/scripts/whatsapp-bridge/package-lock.json /opt/data/whatsapp/bridge_modules/ && \
  npm install --prefix /opt/data/whatsapp/bridge_modules --no-audit --no-fund
"

# 3. Write the pkg hash stamp
docker exec -it hermes python3 -c "
import hashlib
from pathlib import Path
h = hashlib.sha256(Path('/opt/hermes/scripts/whatsapp-bridge/package.json').read_bytes()).hexdigest()
Path('/opt/data/whatsapp/bridge_modules/.hermes-pkg-hash').write_text(h)
print('Stamp written')
"

# 4. Replace node_modules with a hermes-owned symlink to the persistent location
docker exec -it --user root hermes bash -c "
  rm -rf /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  ln -sfn /opt/data/whatsapp/bridge_modules /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  chown -h hermes:hermes /opt/hermes/scripts/whatsapp-bridge/node_modules && \
  echo done
"

# 5. Restart gateway
docker exec -it hermes /opt/hermes/bin/hermes gateway restart
```

**After each Watchtower update:** only the bridge JS files in `/opt/hermes` change.
The symlink is recreated by Watchtower as root-owned (pitfall 3b), but node_modules
itself in `/opt/data` is untouched. The boot-time fix script (below) handles this automatically.

**Note:** `npm install --prefix /opt/data/whatsapp/bridge_modules` requires
`package.json` to exist at the prefix path. Copy it from the bridge dir each time
before running npm (or keep a permanent copy there). The `package-lock.json` can
also be copied but is optional.

**IMPORTANT: `chown -h` cannot fix the symlink if the parent dir is root-owned.**
Even after `chown -h hermes:hermes /opt/hermes/scripts/whatsapp-bridge/node_modules`
succeeds, npm still fails with EACCES when it tries to `unlink()` the symlink —
because `unlink()` requires write permission on the **parent directory**
(`/opt/hermes/scripts/whatsapp-bridge/`), which is `root:root dr-xr-xr-x`.
The symlink ownership being correct is necessary but not sufficient.
The correct fix is the stamp approach (step 3 above) + the boot script below —
so the gateway never calls npm at all.

---

## Truly permanent fix: boot-time init script via docker-compose volume mount

The cleanest solution that survives all Watchtower updates without an image rebuild:
store a fix script in `/opt/data/scripts/` (persistent volume) and mount it into the
container as a `cont-init.d` script that runs as root on every boot.

**Step 1: create the fix script** (already present at `/opt/data/scripts/whatsapp-bridge-fix.sh`).
If missing, recreate it — the script does:
- Ensures `/opt/data/whatsapp/bridge_modules/` exists and is `hermes:hermes`
- Removes and recreates the `node_modules` symlink as `hermes:hermes` if needed
- Writes/updates the 16-char pkg-hash stamp so the gateway skips npm entirely

**Step 2: add the volume mount to docker-compose.yml** (`~/.hermes/docker-compose.yml`):
```yaml
    volumes:
      - ~/.hermes:/opt/data
      - ~/.hermes/scripts/whatsapp-bridge-fix.sh:/etc/cont-init.d/03-whatsapp-bridge-fix
```

**Step 3: apply the change** (one-time from Mac):
```bash
cd ~/.hermes && docker compose up -d
```
The `up -d` recreates the container with the new volume mount. The script then runs on
every subsequent container start (including Watchtower updates) before the gateway launches.

**Why this works:** s6-overlay's `cont-init.d` scripts run as root in lexicographic order
at every container start, before supervised services launch. Mounting our script as
`03-whatsapp-bridge-fix` ensures it runs after Hermes' own `02-reconcile-profiles` but
before the gateway process starts (via the CMD / Architecture B main-wrapper).

---

## Diagnostic sequence (in order)

1. Check `bridge.log` for the actual disconnect reason:
   ```bash
   grep -iE "logged out|conflict|401|stream errored|device_removed" /opt/data/whatsapp/bridge.log | tail -5
   ```
2. Check `gateway.log` for the Python-logger failure mode:
   ```bash
   grep -iE "whatsapp|baileys|bridge" /opt/data/logs/gateway.log | tail -20
   ```
   ⚠️ **`gateway.log` only captures Python `logger.*()` calls.** The WhatsApp
   `connect()` method also uses bare `print()` for per-attempt messages like
   "Installing WhatsApp bridge dependencies…" and "npm install failed: ".
   These go to **s6-log**, not `gateway.log`. If `gateway.log` shows
   "Reconnect whatsapp failed" but no detail, check s6-log first:
   ```bash
   tail -40 /opt/data/logs/gateways/default/current
   # Key patterns to look for:
   #   "[Whatsapp] npm install failed: "    → see pitfall 3b (root-owned symlink)
   #   "[Whatsapp] Installing WhatsApp..."  → dep check is failing (stamp mismatch or npm error)
   #   "[Whatsapp] Bridge process died"     → Node crashed; check bridge.log
   #   "[Whatsapp] Bridge HTTP server did not start in 15s" → auth/connect timeout
   ```
3. Run bridge manually to confirm session validity:
   ```bash
   timeout 8 node /opt/hermes/scripts/whatsapp-bridge/bridge.js \
     --session /opt/data/whatsapp/session --mode bot --port 3000
   ```
4. Check ownership of bridge dir and node_modules:
   ```bash
   ls -la /opt/hermes/scripts/whatsapp-bridge/ | head -8
   # Check: node_modules symlink must be hermes:hermes, not root:root
   ```
5. Check if pkg-hash stamp exists and matches:
   ```bash
   python3 -c "
   import hashlib
   from pathlib import Path
   h = hashlib.sha256(Path('/opt/hermes/scripts/whatsapp-bridge/package.json').read_bytes()).hexdigest()
   s = Path('/opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash').read_text().strip()
   print(f'Match: {h==s}')
   "
   ```
6. Simulate the gateway connect() call directly to see the exact fatal error:
   ```bash
   /opt/hermes/.venv/bin/python - <<'EOF'
   import asyncio, sys, os
   sys.path.insert(0, '/opt/hermes'); os.environ.setdefault('HERMES_HOME','/opt/data')
   async def test():
       from gateway.platforms.whatsapp import WhatsAppAdapter
       from gateway.config import PlatformConfig
       cfg = PlatformConfig(enabled=True, extra={
           'bridge_script': '/opt/hermes/scripts/whatsapp-bridge/bridge.js',
           'session_path':  '/opt/data/whatsapp/session', 'mode': 'bot'})
       adapter = WhatsAppAdapter(cfg)
       try:
           result = await asyncio.wait_for(adapter.connect(), timeout=10.0)
           print(f"connect() -> {result}")
       except asyncio.TimeoutError:
           print("Timeout — likely healthy, auth took >10s")
       if adapter.has_fatal_error:
           print(f"FATAL [{adapter.fatal_error_code}]: {adapter.fatal_error_message}")
   asyncio.run(test())
   EOF
   ```

## Key paths (Jim's OrbStack setup)
| Item | Path |
|---|---|
| Session / creds | `/opt/data/whatsapp/session/creds.json` |
| Bridge log | `/opt/data/whatsapp/bridge.log` |
| Gateway expects session at | `/opt/data/platforms/whatsapp/session/` |
| Bridge script | `/opt/hermes/scripts/whatsapp-bridge/bridge.js` |
| Baileys node_modules | `/opt/hermes/scripts/whatsapp-bridge/node_modules/@whiskeysockets/baileys` |
| Persistent node_modules | `/opt/data/whatsapp/bridge_modules/` |
| Pkg hash stamp | `/opt/hermes/scripts/whatsapp-bridge/node_modules/.hermes-pkg-hash` |

## Important: agent cannot self-restart gateway
The gateway blocks `hermes gateway restart` from inside its own process.
All interactive commands (QR pairing, npm install, gateway restart) must be run
from a **Mac host terminal** via `docker exec -it hermes ...`

## WhatsApp group IDs (Jim's known groups)
| Group | Chat ID |
|---|---|
| Kelly's group (active, "can you reply to this group?") | `120363408898559658@g.us` |
| TO Changes | `120363409212843238@g.us` |

To identify an unknown group: have someone send a message from it to the bot,
then `grep "inbound message: platform=whatsapp" /opt/data/logs/gateway.log | tail -5`
— the `chat=` field is the group ID. Group IDs end in `@g.us`; DMs end in a phone
number with no suffix.
