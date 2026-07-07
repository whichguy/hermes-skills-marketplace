# Security Overlay Pipeline

How pip/apt/npm updates flow from detection to deployment.

## Architecture

```
Mac host (launchd, daily)
  └→ update-hermes-overlay.sh
       ├→ docker pull nousresearch/hermes-agent:latest
       ├→ docker build -t hermes-agent:candidate
       │    ├→ apt-get upgrade (all Debian packages)
       │    ├→ uv pip install (audited security pins: cryptography, starlette, etc.)
       │    ├→ upgrade-pip-packages.py (all other outdated pip, 3-day gate)
       │    ├→ uv pip check (dependency validation)
       │    ├→ npm install (Baileys bridge + overrides)
       │    └→ npm audit (HIGH/CRITICAL gate)
       ├→ hermes security audit --fail-on high (candidate image)
       ├→ docker tag candidate → stable
       └→ docker compose up -d --force-recreate
```

## Why in-container pip upgrades don't work

The Hermes venv at `/opt/hermes/.venv/` is `root:root` (created by Docker).
The container runs as `uid=10000(hermes)` with no sudo and no Docker socket.
`uv pip install` fails trying to remove old dist-info metadata files:

```
error: Failed to remove file `/opt/hermes/.venv/lib/python3.13/site-packages/...dist-info/...`
Caused by: Permission denied (os error 13)
```

The overlay build runs as root during `docker build`, so it can write to the
venv. This is the only path for pip upgrades.

## Key files

| File | Role |
|---|---|
| `docker/security-overlay/Dockerfile.security` | Multi-stage Dockerfile: apt → pip pins → pip bulk → npm |
| `docker/security-overlay/upgrade-pip-packages.py` | Discovers outdated pip packages, applies 3-day gate, bulk upgrades |
| `docker/security-overlay/relax-hermes-cryptography-pin.py` | Relaxes the exact cryptography pin for security patches |
| `scripts/update-hermes-overlay.sh` | Host-side orchestrator: pull → build → audit → promote → recreate |
| `scripts/pip_dependency_watch.py` | In-container watchdog: reports what's pending (no longer applies) |

## upgrade-pip-packages.py details

- Runs `uv pip list --python /opt/hermes/.venv/bin/python --outdated`
- Skips packages published <3 days ago (PyPI JSON API)
- Skips `hermes-agent` (editable install) and overlay-pinned packages
- Upgrades all eligible packages in one `uv pip install` call
- Validates with `uv pip check` — if conflicts, build fails, candidate rejected

## Safety gates

1. **3-day age gate** — packages published <3 days ago are held back
2. **uv pip check** — dependency conflicts reject the candidate image
3. **hermes security audit --fail-on high** — HIGH/CVEs reject the candidate
4. **npm audit** — HIGH/CRITICAL npm vulns reject the candidate
5. **Health check** — container must start and pass health check before promotion
6. **Rollback** — if candidate fails any gate, current stable container is untouched
