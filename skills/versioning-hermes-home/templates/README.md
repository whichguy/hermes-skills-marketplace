# Hermes Agent — [Your Name] Deployment

This repo version-controls the customization layer for a [Hermes Agent](https://hermes-agent.nousresearch.com/) instance. It contains config, skills, scripts, cron jobs, wiki, and memories — **not** secrets.

## What's Tracked

| Path | What |
|------|------|
| `config.yaml` | Main Hermes configuration (verified no inline secrets) |
| `SOUL.md` | Agent persona/personality |
| `docker-compose.yml` | Container + Watchtower setup |
| `skills/` | Installed skills (bundled + custom) |
| `scripts/` | Cron precheck scripts, sync tools, bridge code |
| `cron/` | Job definitions (`jobs.json`) + prompt templates |
| `wiki/` | LLM Wiki knowledge base |
| `memories/` | `MEMORY.md` + `USER.md` (private repo only) |
| `agent-hooks/` | Shell hook scripts |

## What's NOT Tracked (fail-closed gitignore)

`.env` / `.env.*` · `auth.json` · `google/` / `google_*.json` · `channel_directory.json` ·
`whatsapp/` / `pairing/` · `state.db*` / `kanban.db*` · `sessions/` / `logs/` ·
`personal-context/` · `cron/state/` / `cron_state/` · `skills/.hub/` ·
`scripts/whatsapp-bridge/node_modules/` · `hermes-agent/` · `*.bak*`

## Quick Start (Clone & Deploy)

```bash
# 1. Clone to your HERMES_HOME directory
git clone <repo-url> ~/.hermes
cd ~/.hermes

# 2. Create .env with API keys (NOT in this repo)
#    At minimum: OPENROUTER_API_KEY=*** or ANTHROPIC_API_KEY=***
chmod 600 .env

# 3. Install WhatsApp bridge dependencies (if using WhatsApp)
cd scripts/whatsapp-bridge && npm install && cd ../../

# 4. Start the stack
docker compose up -d

# 5. Verify
docker compose logs -f hermes
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HERMES_HOME` | `/opt/data` | Root path for all Hermes data |
| `HERMES_SOURCE` | `/opt/hermes` | Hermes source code root (imports, bridge) |
| `HERMES_BIN` | `/opt/hermes/.venv/bin/hermes` | Path to hermes binary |
| `WIKI_PATH` | `$HERMES_HOME/wiki` | Wiki knowledge base path |

All scripts use `os.environ.get("HERMES_HOME", "/opt/data")` — works with any mount point.

## Git Sync

Daily backup via `scripts/git-sync/hermes-sync-cron.sh`:
- Watchdog pattern: **silent on success**, alerts only on failure
- Fail-closed gitignore: secrets never leave the machine

Manual sync: `./scripts/git-sync/hermes-sync.sh "description of changes"`