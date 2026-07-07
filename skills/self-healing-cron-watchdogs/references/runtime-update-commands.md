# Runtime Update Commands

## Current architecture: in-container self-patching

The runtime auto-updater (`runtime_auto_update.py`) runs as a Hermes cron
job (daily 10:00 UTC, no_agent, script-only) and self-patches Node.js, npm,
and uv — no root, no Docker socket, no host crontab required.

**Install location:** `/opt/data/.local/bin/` (writable by hermes user,
persisted via `~/.hermes:/opt/data` volume mount)

**PATH in docker-compose.yml:**
```yaml
environment:
  - PATH=/opt/data/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/games:/usr/games
```
Requires `docker compose up -d hermes` from host to take effect. Until then,
the script self-manages PATH internally.

### How it works

```
runtime_auto_update.py checks each runtime:
  1. Get current version from .local/bin/<binary> (or system fallback)
  2. Get latest version from upstream API
  3. If .local/bin doesn't have the binary → bootstrap (install it)
  4. If .local/bin version != latest → download and install
  5. If versions match → skip (silent)

Node.js → nodejs.org/dist/index.json → v22 LTS line
npm     → registry.npmjs.org/npm/latest
uv      → pypi.org/pypi/uv/json
```

### Testing

```bash
# Normal run — silent if all current
python3 ${HERMES_HOME}/scripts/runtime_auto_update.py

# Force re-install: remove .local/bin binaries first
rm /opt/data/.local/bin/node /opt/data/.local/bin/npm /opt/data/.local/bin/npx /opt/data/.local/bin/uv /opt/data/.local/bin/uvx /opt/data/.local/bin/corepack
python3 ${HERMES_HOME}/scripts/runtime_auto_update.py  # should re-bootstrap all

# Simulate old version: replace node with fake old version
echo '#!/bin/sh\nexec /usr/local/bin/node --version | sed "s/v22.23/v22.20/"' > /opt/data/.local/bin/node
chmod +x /opt/data/.local/bin/node
python3 ${HERMES_HOME}/scripts/runtime_auto_update.py  # should detect and update
```

### State files

- `/opt/data/.state/runtime_auto_update.json` — last run + per-runtime state
- `/opt/data/.state/runtime_updates.log` — timestamped log of all updates
- `/opt/data/.local/lib/node/` — Node.js distribution (extracted tarball)
- `/opt/data/.local/lib/npm/` — npm package (npm install prefix)

## Manual fallback: host-side docker exec commands

When the container is down or you need to update system-level binaries in
`/usr/local/bin` directly (requires root via `docker exec -u root`):

### Node.js (v22 LTS line)
```bash
docker exec -u root hermes sh -c 'curl -fsSL https://nodejs.org/dist/v22.23.1/node-v22.23.1-linux-arm64.tar.xz | tar -xJ --strip-components=1 -C /usr/local'
```

### npm
```bash
docker exec -u root hermes npm install -g npm@latest --prefix /usr/local
```

### uv
```bash
# Via astral.sh installer (installs gnu build to /usr/local/uv, must copy)
docker exec -u root hermes sh -c 'curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local sh && cp /usr/local/uv /usr/local/bin/uv'

# Via GitHub releases (musl build, direct binary)
docker exec -u root hermes sh -c 'curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/uv-aarch64-unknown-linux-musl.tar.gz | tar -xz -C /tmp && cp /tmp/uv-aarch64-unknown-linux-musl/uv /usr/local/bin/uv'
```

### apt packages
```bash
docker exec -u root hermes sh -c 'apt-get update && apt-get upgrade -y'
```

### Verification
```bash
docker exec hermes sh -c 'echo "node: $(node --version)"; echo "npm: $(npm --version)"; echo "uv: $(uv --version)"; echo "python: $(python3 --version)"'
```

## docker-compose.yml restart (one-time, after PATH change)

```bash
cd ~/.hermes && docker compose up -d hermes
```

This recreates the container with the new `PATH` env var that puts
`/opt/data/.local/bin` first, so all processes find user-installed runtimes
without each needing to self-manage PATH.