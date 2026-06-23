# HERMES_HOME path classification (keep / exclude)

Canonical keep-vs-exclude map, derived from auditing a real production
`HERMES_HOME` (`/opt/data`). Use it to build the fail-closed allow-list.
Sizes are illustrative; always re-audit (`du -sh`) on the actual instance.

## ✅ VERSION (safe customizations)

| Path | What it is | Notes |
|---|---|---|
| `config.yaml` | Main config | **Verify no inline secrets first.** Usually clean: `api_key: ollama`, empty `''`, Bitwarden refs an env var. |
| `skills/` | Skills | Exclude `.hub/` (cache, ~25MB), `.curator_backups/`, `.archive/`, `.usage.json`, `__pycache__/`. |
| `wiki/` | Knowledge wiki | Exclude `**/*.lock`. |
| `scripts/` | Custom scripts | Exclude `__pycache__/`, `*.pyc`. |
| `cron/` | `jobs.json` + prompt templates | **Exclude `cron/state/`** (tick state, churns every run) and `*.bak*`. |
| `memories/` | `MEMORY.md`, `USER.md` | **Private repo + explicit user OK only.** Exclude `*.bak*`, `*.lock`. |
| `plans/` | Saved plan markdown | Clean. |
| `agent-hooks/` | Hook scripts | Clean (scan for secrets if any reference creds). |
| `SOUL.md` / persona | Persona/config | Clean. |
| `docker-compose.yml`, `slack-manifest.json`, `start-*.sh`, `shell-hooks-allowlist.json`, `.install_method` | Setup artifacts | Scan, usually clean. |

## 🔒 NEVER (secrets / credentials)

`.env` and all `.env.*` backups · `auth.json` / `auth.lock` ·
`google_*.json` and `google/` (OAuth `token.json` + `client_secret.json`) ·
`google_client_secret.json`, `google_token.json` · `channel_directory.json` ·
`whatsapp/` · `pairing/` · `*token.json`, `*client_secret*` anywhere.

## 🗑️ EXCLUDE (runtime state / bloat — not config, churns or huge)

| Path | Why |
|---|---|
| `cron/state/*.json` | `*_seen.json`, `token_baseline.json` etc. rewritten every tick. NOTE: `token_baseline.json` is **LLM usage counters**, not auth — false-positive on a "token" grep, but still exclude as churn. |
| `state.db*`, `kanban.db*` | Live SQLite DBs — huge (100MB+), contain everything incl. transcripts. |
| `sessions/`, `logs/` | Transcripts and logs. |
| `plugins/` | If it holds only `state.json`/`scan_*.json` runtime state (no plugin code). |
| `disk-cleanup/` | Logs + tracked.json. |
| `*cache*`, `.cache/`, `cache/`, `audio_cache/`, `image_cache/`, `models_dev_cache.json` | Runtime caches. |
| `hermes-agent/` | Upstream source — its OWN git repo (embedded-repo trap). |
| `skills/.hub/index-cache/` | Skills hub catalog cache, ~25MB single file. |
| `scripts/whatsapp-bridge/node_modules/` | Generated npm deps — 49MB+, regeneratable via `npm install`. Exclude from git; provide a `setup.sh` to install on fresh clones. |
| `cron_state/` | Alternate cron state dir (no slash — different from `cron/state/`). Some scripts write here. Exclude. |

## ⚠️ JUDGMENT CALL — default EXCLUDE, ask the user

| Path | Why it's tricky |
|---|---|
| `personal-context/` | Mixes real customization (custom `.py` builders, `.md` schema, `policy.yaml`) with **sensitive data**: `approved-context.yaml`, relationship graphs, `audit-log.jsonl`, contact reviews. Default exclude the whole dir; only split code-vs-data if the user explicitly wants the scripts versioned. |
| `memories/` | Personal but often the point of the backup. Private repo + explicit yes. |

## Grep patterns

Pre-push secret gate (run on staged list AND on the pushed remote tree):
```
^\.env|auth\.json|google_.*\.json|^google/|state\.db|kanban\.db|channel_directory|^whatsapp/|^pairing/|^sessions/|^logs/|^personal-context/|token\.json|client_secret
```

config.yaml inline-secret scan (real values, not empty/dummy):
```
tvly-|sk-|ghp_|gho_|AIza|xox[bp]-
```
