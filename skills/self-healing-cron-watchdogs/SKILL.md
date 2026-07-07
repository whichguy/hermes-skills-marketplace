---
name: self-healing-cron-watchdogs
description: 'Four cooperating cron watchdogs that keep Hermes self-healing: trace
  diagnostic+auto-fix, npm dependency updates (3-day-behind), pip dependency updates
  (3-day-behind), and a self-patching runtime auto-updater for Node.js/npm/uv
  that installs to /opt/data/.local/bin — no root, no host crontab required.'
version: 1.0.0
author: Hermes Agent
license: MIT
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - cron
    - automation
    - self-healing
    - dependencies
    - no-agent
    - cost-control
    related_skills:
    - script-first-cron-design
    - hermes-agent
    config:
    - key: self-healing-cron-watchdogs.enabled
      description: Enable self-healing-cron-watchdogs skill behavior
      default: true
      prompt: Enable self-healing-cron-watchdogs skill?
    category: devops
---


# Self-Healing Cron Watchdogs

Four cooperating cron jobs that implement the "Loop Engineering" pattern
(Karpathy/Chawla): schedule drives the loop, maker produces fixes, checker
verifies, state lives on disk, exit conditions are set before the loop runs.

## Architecture

```
Schedule (cron) → Precheck script (deterministic) → LLM (maker+checker) → State file
                     ↓                                    ↓
                 Empty stdout = silent              delegate_task for fixes
                 Non-empty = JSON payload            Verify fix, update state
```

All three follow script-first design:
- **Silent when nothing needs attention** (zero tokens)
- **State on disk** for idempotency (survives restarts, picks up mid-repair)
- **3-day-behind strategy** for dependency updates (let someone else hit the bugs)
- **Auto-fix where safe, surface to Jim where not**

## The Three Watchdogs

### 1. Self-Healing Cron Trace Diagnostic (`cron_trace_diagnostic.py`)

**Cron job:** `Self-healing cron watchdog`
**Schedule:** Every 1h
**Model:** glm-5.2:cloud via ollama-glm
**Toolsets:** terminal, file, skills, delegation
**State:** `/opt/data/cron/state/trace_repairs.json`

Scans all cron jobs for failures (`last_status != "ok"`), classifies the error,
and applies the right fix strategy:

| Error type | Fix strategy | Auto-fix? |
|---|---|---|
| Provider/credit exhausted | Check if provider healthy → retry or swap model | ✅ Yes |
| Script syntax error | delegate_task patches script, verify with py_compile | ✅ Yes |
| Script timeout (no_agent job) | Bump `cron.script_timeout_seconds` or reduce internal subprocess timeouts | ✅ Yes |
| Missing dependency | Install via `uv pip install` or modify script | ✅ Yes |
| Container/image issue | Run `hermes_auto_update_check.py`, Watchtower handles rest | ✅ Yes |
| Rate limited | Wait for next tick | No action needed |
| Google OAuth expired | Surface to Jim | ❌ Surface |
| Google OAuth token malformed (int expiry) | Strip non-string expiry from token file, force refresh | ✅ Yes |
| Script file not found (script_path_fix) | Script field contains full command instead of bare filename — fix via `hermes cron edit <job_id> --script "<filename>.py"` | ✅ Yes |
| Unknown error | delegate_task diagnoses, applies safe fix | ✅ If safe |

**Safe fixes** (always auto-applied, even on sensitive jobs):
- `model_swap` — changes which LLM provider runs the job (config-only, never touches data)
- `watchtower_check` — checks container image freshness (read-only)
- `rate_limit_wait` — no action needed
- `script_timeout_fix` — changes cron timeout config or script subprocess timeouts (config-only, never touches data/prompts)

**Sensitive jobs** (inbox-triage-heartbeat, personal-context-review, followup-sweep, email-wiki-ingest, morning-brief, eod-wrap, weekly-review): must NOT be auto-fixed at all — no model swaps, no script patches, no retries. Always surface to Jim. The runtime instructions override the fix-type classification: even if the precheck says `auto_fixable: true`, `is_sensitive: true` wins and the job is off-limits.

**Exit condition:** Max 3 repair attempts per failure ID, then escalate to human.

**Dedup:** Stable failure ID = `job_id[:8] + classification + sha256(error_text)[:12]`. Same job failing with same error = same ID. State file tracks attempts per ID.

### 2. Node.js Dependency Update (`npm_dependency_watch.py`)

**Cron job:** `Node.js dependency update watchdog`
**Schedule:** Daily 9:00 AM UTC
**Model:** glm-5.2:cloud via ollama-glm
**Toolsets:** terminal, file
**State:** `/opt/data/cron/state/npm_update_state.json`

Scans `package.json` projects for outdated npm dependencies, queries `npm view
<pkg> --json` for the latest version + publish date, and reports only packages
where the latest version was published >3 days ago.

**Projects scanned:**
- `/opt/data/whatsapp/bridge` (WhatsApp bridge: baileys, express, pino, qrcode-terminal)
- `${HERMES_HOME}/scripts/whatsapp-bridge` (scripts copy of the same)
- `/opt/data/lsp` (LSP servers: bash-language-server, pyright, yaml-language-server)

**Skips:**
- GitHub/git dependencies (can't check registry)
- Packages published <3 days ago (too fresh)
- Already-notified versions (state file dedup)

**Apply:** `cd <project_path> && npm update <package>`, verify with `npm list`.

### 3. Python Dependency Update (`pip_dependency_watch.py`)

**Cron job:** `Python dependency update watchdog`
**Schedule:** Daily 9:00 AM UTC
**Model:** glm-5.2:cloud via ollama-glm
**Toolsets:** terminal, file
**State:** `/opt/data/cron/state/pip_update_state.json`

Scans the Hermes venv (127 packages) using `uv pip list --outdated`, queries
PyPI JSON API for each package's latest version publish date, and reports only
packages where the latest was published >3 days ago.

**Venv:** `/opt/hermes/.venv` (Python 3.13.5, uv-managed)

**Critical packages** (flagged, still updated but with caution):
- anthropic, openai (LLM providers — core to Hermes)
- pydantic, pydantic-core (data validation)
- fastapi, starlette, uvicorn (web server stack)
- google-api-python-client, google-auth (Google Workspace)
- slack-bolt, slack-sdk, python-telegram-bot, discord-py (messaging platforms)
- mcp (MCP protocol)
- cryptography, protobuf (security/serialization)

**Skips:**
- `hermes-agent` itself (managed by Watchtower via Docker image updates)
- Packages published <3 days ago (too fresh)
- Already-notified versions (state file dedup)
- apt packages are surfaced but NOT auto-applied (handled by image update cycle)

**Apply:** pip updates are auto-applied by the **security overlay build** (see
`references/security-overlay-pipeline.md`). The overlay Dockerfile runs
`upgrade-pip-packages.py` as root during `docker build`, upgrades all eligible
packages in one shot, validates with `uv pip check`, then recreates the
container. No manual in-container `uv pip install` needed — the `hermes` user
can't write to the root-owned venv anyway. The watchdog script
(`pip_dependency_watch.py`) now reports what's pending for the next overlay
build rather than instructing manual application.

**Batch strategy:** The overlay's `upgrade-pip-packages.py` upgrades all
eligible packages in a single `uv pip install` call (bulk is safe during
build — if any conflict, `uv pip check` catches it and the candidate image
is rejected). The 3-day age gate and skip list (hermes-agent, overlay-pinned
packages) are applied before the bulk upgrade.

### 5. WhatsApp Bridge Health Watchdog (`whatsapp-bridge-health-watch.py`)

**Cron job:** `WhatsApp bridge health watchdog`
**Schedule:** Every 15 minutes
**Delivery:** Slack (origin)
**no_agent:** true (script-only, zero tokens on healthy path)
**State:** `/opt/data/cron/state/wa_bridge_health.json`

Checks WhatsApp bridge health via two signals:
1. `GET http://localhost:3000/health` — bridge HTTP endpoint
2. Tail `/opt/data/whatsapp/bridge.log` for `Logged out` / `device_removed` signals

Silent when bridge is connected and healthy. Alerts when:
- Health endpoint returns disconnected / unreachable
- Bridge log shows `Logged out` (session invalidated, needs re-pair)
- Bridge log shows `device_removed` (WhatsApp server killed the session)

Alert includes full Docker CLI re-pairing instructions. Cooldown: 1h between
same-type alerts (no spam). Created Jun 2026 after repeated bridge session
invalidation — see `hermes-whatsapp-gateway` skill for root cause analysis.

## Integration with the Security Overlay Build

The Hermes Docker container is labeled `com.centurylinklabs.watchtower.enable=true`.
Watchtower runs daily at 10:30 UTC and auto-updates the container image when a
new one is pushed to `nousresearch/hermes-agent:latest`.

The self-healing watchdog (watchdog #1) integrates with Watchtower via the
`watchtower_check` fix type: when a cron job fails with a container/image error,
the LLM runs `hermes_auto_update_check.py` to verify the container is running
the latest image. If stale, Watchtower will update it on its next cycle.

The pip watchdog (watchdog #3) explicitly does NOT update `hermes-agent` —
that's the base image's job. But all other pip packages are now upgraded by
the **security overlay build** (not Watchtower directly). The overlay runs
daily via launchd → `update-hermes-overlay.sh` → `docker build` (with
`upgrade-pip-packages.py`) → container recreate. This is the same pipeline
that handles apt upgrades, cryptography pinning, and the Baileys bridge patch.
See `references/security-overlay-pipeline.md` for the full architecture.

## 3-Day-Behind Strategy

All dependency watchdogs use a 3-day stability window:
- Packages published within the last 3 days are held back
- Packages published >3 days ago are considered safe to update
- The cutoff is configurable via `NPM_DAYS_BEHIND` and `PIP_DAYS_BEHIND` env vars

Rationale (from Avi Chawla quoting Karpathy): "Remove yourself as the
bottleneck." Let other users hit the bugs first, then update when stable.

## Testing

All three scripts can be tested independently:

```bash
# Self-healing: should find weekly-review failure
python3 ${HERMES_HOME}/scripts/cron_trace_diagnostic.py

# npm: should find express/pino/baileys updates
python3 ${HERMES_HOME}/scripts/npm_dependency_watch.py

# pip: should find ~50 outdated packages >3 days old
python3 ${HERMES_HOME}/scripts/pip_dependency_watch.py

# Runtime auto-updater: should be silent (all current after bootstrap)
python3 ${HERMES_HOME}/scripts/runtime_auto_update.py

# Idempotency test: second run should be silent
python3 ${HERMES_HOME}/scripts/cron_trace_diagnostic.py  # silent if no new failures
python3 ${HERMES_HOME}/scripts/npm_dependency_watch.py   # silent (state file dedup)
python3 ${HERMES_HOME}/scripts/pip_dependency_watch.py  # silent (state file dedup)
python3 ${HERMES_HOME}/scripts/runtime_auto_update.py    # silent (all current)
```

## State Files

| File | Purpose |
|---|---|
| `cron/state/trace_repairs.json` | Failure → repair tracking (attempts, status, fix applied) |
| `cron/state/npm_update_state.json` | Already-notified npm versions |
| `cron/state/pip_update_state.json` | Already-notified pip versions |
| `.state/runtime_auto_update.json` | Runtime auto-updater state (last run + per-runtime versions) |
| `.state/runtime_updates.log` | Runtime auto-updater run log (timestamps + results) |

### Provider health check (non-sensitive jobs only)

Before swapping a failing job's provider, verify whether the provider is actually unhealthy or if the failure was transient:

1. `hermes cron list` — scan all jobs' `Last run` lines for the same provider/model
2. If other jobs using the same provider are succeeding → failure was likely transient → force-retry: `hermes cron run <job_id>`
3. If other jobs using the same provider are also failing → provider is unhealthy → swap model via `hermes cron edit <job_id>` (or `hermes config set` if global)
4. Also run `python3 ${HERMES_HOME}/scripts/anthropic_credit_guard.py --dry-run` to check the credit guard's view of Anthropic API health

This cross-reference technique prevents unnecessary model swaps when a single job hit a one-off upstream error.

**`hermes cron edit` has no `--model` or `--provider` flag** — the edit subcommand only supports `--schedule`, `--prompt`, `--name`, `--deliver`, `--repeat`, `--skill`, `--script`, `--no-agent`, `--agent`, `--workdir`. To swap a non-sensitive job's model or provider, edit `jobs.json` directly (same pattern as pitfall #8 for `no_agent`): read the file, find the job by ID, update the `model` and `provider` fields, write back. Alternatively, use `hermes config set` to change the global default model/provider (affects all jobs that don't override). Never edit the `prompt` or `skills` field when doing a model swap — only `model` and `provider`.

**Notification dedup for already-surfaced failures** — before surfacing a `needs_human` failure, check the state file (`trace_repairs.json`). If the failure ID is already recorded with `status: "needs_human"` from a recent scan (same day), do NOT re-surface it. Go `[SILENT]` instead — Jim already knows, and a duplicate notification is noise. Update the `last_rescan` timestamp in the state entry to show the scan ran, but don't deliver a new message. This is the notification-level complement to the repair-attempt dedup: repair attempts are capped at 3 per failure ID, and notifications are capped at 1 per day per failure ID.

## Pitfalls

1. **`last_status: null` for new jobs** — the trace diagnostic script filters out jobs that have never run (`last_run_at` is null). New cron jobs won't false-alarm. Also filter `last_status is None and not last_error` — some jobs have null status without having ever failed.
2. **`None` propagation in error classification** — `classify_error()` receives `last_error or last_status`, but both can be `None`. Always guard: `error_text = last_error or last_status or "unknown"` before passing to regex matching. Same for `get_failure_id()` — `safe_text = (error_text or "no_error")[:500]` before hashing. And in the failure dict: `(last_error or "")[:500]` not `last_error[:500]`. These three `None` crashes were found during initial testing of `cron_trace_diagnostic.py`.
3. **GitHub/git npm deps** — can't query registry for publish dates. Skipped automatically.
4. **PyPI API rate limits** — the pip watchdog queries pypi.org/pypi/<pkg>/json for each outdated package. With ~58 packages, this takes ~30-60 seconds. If PyPI is slow, individual package queries may timeout (10s each).
5. **uv vs pip** — always use `uv pip install --python /opt/hermes/.venv/bin/python` to target the right venv. Never bare `pip install`.
6. **apt inside Docker** — apt updates inside the container are generally not persistent (Watchtower recreates the container on image update). Surface them but don't auto-apply.
7. **Anthropic credit fallback on sensitive jobs** — the weekly-review failure showed an Anthropic "credit balance too low" error even though the job uses ollama-glm. Even if all other jobs on the same provider are healthy (meaning a retry would likely succeed), sensitive jobs must NOT be force-retried or model-swapped. Surface to Jim and note: (a) the provider appears healthy because N other jobs succeed with it, (b) the error may have been transient, (c) the job's next scheduled run will likely succeed, (d) Jim can force-run if he wants: `hermes cron run <job_id>`. Give Jim the health evidence so he can decide confidently.
8. **`no_agent` cannot be flipped via cronjob API** — edit `jobs.json` directly to change `no_agent` on existing jobs. See script-first-cron-design skill pitfall #13.
9. **Sensitive-job sensitive-list names drift** — the precheck payload uses full job names (e.g. `inbox-triage-heartbeat`, `personal-context-review`, `email-wiki-ingest`). The sensitive list in the skill must use these exact names, not abbreviations. Always copy from the runtime instructions block of the current precheck payload.
10. **`hermes` not on PATH in cron sessions** — the binary lives at `/opt/hermes/bin/hermes`. Export PATH at the start of the session: `export PATH="/opt/hermes/bin:$PATH"`. Without this, `hermes cron list` returns "command not found."
11. **`hermes cron` has no `show` or `status <job_id>` subcommand** — use `hermes cron list` and grep for the job. `hermes cron status` (no args) shows a global status summary.
12. **Idempotency test for the diagnostic precheck** — run `cron_trace_diagnostic.py` twice; the second run must produce the same failure IDs (stable hash from job_id + classification + error_text). If IDs differ, the dedup state file will never converge.
13. **Precheck misclassifies `no_agent` script timeouts as "provider_timeout"** — when a job has `no_agent: true`, `model: null`, and `provider: null`, the precheck's regex-based classifier used to match "timed out after" in the error string and label it `provider_timeout` with a `model_swap` fix. This was wrong: there's no model or provider to swap. **Fixed (Jun 2026):** added a dedicated `script_timeout` classification that matches "Script timed out after" and "Command timed out after" BEFORE the `provider_timeout` patterns. The new `script_timeout_fix` fix type recommends either bumping `cron.script_timeout_seconds` in config.yaml or reducing the script's internal subprocess timeouts. This fix type is in `ALWAYS_SAFE_FIXES` because it only changes config/script timing, never touches job data or prompts. The cron runner timeout is configurable (default 120s) via `cron.script_timeout_seconds` in config.yaml, `HERMES_CRON_SCRIPT_TIMEOUT` env var, or module-level `_SCRIPT_TIMEOUT`.
14. **`hermes cron run` requires full path** — in cron sessions, `hermes` is not on PATH. Use `/opt/hermes/.venv/bin/hermes cron run <job_id>` (or export PATH first). The `hermes cron run` subcommand triggers an immediate run of a scheduled job and returns the result inline.
15. **`script_timeout_fix` must be in `ALWAYS_SAFE_FIXES`** — the `script_timeout` classification (added Jun 2026) produces a `script_timeout_fix` fix type. This fix only changes `cron.script_timeout_seconds` in config.yaml or the script's internal subprocess timeout values — it never touches job data, prompts, or output content. Adding it to `ALWAYS_SAFE_FIXES` ensures it auto-applies even on sensitive jobs (e.g. if a sensitive job's script times out, bumping the cron timeout is safe — it doesn't expose or modify the job's private data).
16. **Google OAuth token `expiry` field can be an integer, not a string** — when a token file (e.g. `google/accounts/personal/token.json`) has `"expiry": 3599` (integer) instead of an ISO timestamp string, the Google OAuth library's `from_authorized_user_info()` calls `.rstrip("Z")` on it and crashes with `AttributeError: 'int' object has no attribute 'rstrip'`.

17. **`script_file_not_found` caused by full-command script field, not missing file** — when a cron job's `script` field contains the full shell command (e.g. `python3 ${HERMES_HOME}/scripts/whatsapp-bridge-health-watch.py`) instead of just the bare filename (e.g. `whatsapp-bridge-health-watch.py`), the cron runner prepends its scripts directory to the value, producing a doubled path like `${HERMES_HOME}/scripts/python3 ${HERMES_HOME}/scripts/whatsapp-bridge-health-watch.py` that doesn't exist. The error reads `Script not found: ${HERMES_HOME}/scripts/python3 ${HERMES_HOME}/scripts/...` — the `python3` in the middle of the path is the telltale sign. The precheck correctly classifies this as `script_file_not_found` with fix_type `script_path_fix`. **Fix:** use `hermes cron edit <job_id> --script "<bare_filename>.py"` to set the script field to just the filename (no `python3` prefix, no full path). The cron runner resolves bare filenames relative to the scripts directory automatically. **Do NOT** try to create the file at the doubled path — the file exists fine; the script field format is wrong. After fixing, force-retry with `hermes cron run <job_id>` and verify `last_status: ok`. This was found when the WhatsApp bridge health watchdog (job `YOUR_CRON_JOB_ID`) failed on Jun 2026.

18. **`script_file_not_found` caused by subdirectory prefix in script field** — a second variant: the `script` field contains a relative path with a subdirectory prefix (e.g. `scripts/usaw_event_info_sync.py`), which the cron runner resolves relative to its scripts directory (`${HERMES_HOME}/scripts/`), producing a doubled nested path like `${HERMES_HOME}/scripts/scripts/usaw_event_info_sync.py` that doesn't exist. The error reads `Script not found: ${HERMES_HOME}/scripts/scripts/usaw_event_info_sync.py` — the doubled `scripts/scripts/` in the path is the telltale sign. The precheck classifies this as `script_file_not_found` with fix_type `script_path_fix` and recommends `hermes cron edit --script "<bare_filename>.py"`. **However**, when the actual script lives in a skill directory (e.g. `/opt/data/skills/sports/usaw-event-info/scripts/`) and the job uses `no_agent: true` with a `workdir` pointing to the skill dir, the correct fix may be to make the script available at the cron runner's expected path instead of editing the script field (the job may rely on the subdirectory prefix for its own path resolution). **Symlink does NOT work** — the cron runner blocks script paths that resolve (via symlink) outside the scripts directory: `Blocked: script path resolves outside the scripts directory`. **Fix that works:** copy the actual script file into the expected doubled path location (`cp <skill_script_path> ${HERMES_HOME}/scripts/scripts/<filename>.py`). The script must use absolute paths internally (not relative imports or `__file__`-based resolution) for the copy to work correctly — verify by reading the script before copying. After copying, verify with `python3 -m py_compile <path>` then force-retry: `hermes cron run <job_id>`. This was found when the usaw-event-info-sync job (ID `YOUR_CRON_JOB_ID`) failed on Jun 2026. **Caveat:** the copy will not track upstream changes to the skill script — if the skill is updated, the copy must be refreshed manually.

19. **`script_file_not_found` caused by `HERMES_HOME` override — script exists in default home but not in overridden home** — a third variant: the script file exists in the default Hermes home scripts directory (`~/.hermes/scripts/`) but the deployment uses `HERMES_HOME` set to a different path (e.g. `/opt/data`), so the cron runner resolves scripts to `$HERMES_HOME/scripts/` (e.g. `${HERMES_HOME}/scripts/`) — a different directory where the file doesn't exist. The error reads `Script not found: ${HERMES_HOME}/scripts/<filename>.py` with NO doubled path, NO `python3` mid-path — just a clean path to a file that genuinely doesn't exist at that location. The telltale sign: the file exists at `~/.hermes/scripts/<filename>.py` but NOT at `$HERMES_HOME/scripts/<filename>.py`. **Fix:** copy the script from the default home to the overridden home: `cp ~/.hermes/scripts/<filename>.py $HERMES_HOME/scripts/<filename>.py`. After copying, the job may be auto-disabled (`enabled: false, state: completed`) — resume it first (`hermes cron resume <job_id>`), then force-run (`hermes cron run <job_id>`). Verify `last_status: ok`. This was found when the Kanban SDLC Dashboard Monitor v2 job (ID `a4e218be5d9f`) failed on Jun 2026. **Note:** this is distinct from the full-command variant (pitfall #17, `python3` mid-path) and the subdirectory-prefix variant (pitfall #18, doubled `scripts/scripts/`). The `HERMES_HOME` mismatch variant has a clean path — the file simply isn't where the runner expects it because the home directory was overridden.

20. **Auto-disabled jobs need resume before force-run** — when a cron job fails, the scheduler may auto-disable it (`enabled: false, state: completed`). A `hermes cron run <job_id>` on a disabled job returns `Already being fired by the scheduler; not run again.` — it won't execute. **Fix:** resume first (`hermes cron resume <job_id>`), then force-run (`hermes cron run <job_id>`). After the run succeeds, the job may auto-disable again (if it's a `once` schedule with `repeat.times` exhausted) — check `enabled` and `state` after the run to confirm the final state. This was found when the Kanban SDLC Dashboard Monitor v2 job (ID `a4e218be5d9f`) was disabled after its first failure and `hermes cron run` silently refused to execute.

This affects ALL jobs that go through `google_api.py get_credentials()` (Drive, Gmail, Calendar, Sheets). The precheck classifies this as a generic `runtime_error` with fix_type `diagnose`. The fix is to patch `google_api.py` to strip non-string `expiry` values from the token file before passing it to `Credentials.from_authorized_user_file()` — this forces the refresh path, which writes back a proper ISO timestamp. The fix was applied to both `get_credentials()` and `_normalize_authorized_user_payload()` in `google_api.py`. When diagnosing this class of error, look at the full traceback for `from_authorized_user_info` and `rstrip` — the root cause is in the token file, not the calling script.

### 4. Runtime Auto-Updater (`runtime_auto_update.py`)

**Self-patching runtime updater** that keeps Node.js, npm, and uv current —
all from inside the container, no root, no Docker socket, no host crontab.

**Cron job:** `Runtime auto-updater`
**Schedule:** Daily 10:00 UTC
**Delivery:** Telegram (no_agent, script-only)
**State:** `/opt/data/.state/runtime_auto_update.json`
**Log:** `/opt/data/.state/runtime_updates.log`

**The privilege problem — solved:** The Hermes container runs as
`uid=10000(hermes)` with no root/sudo and no Docker socket access.
`/usr/local/bin` is not writable. **Solution:** Install runtimes to
`/opt/data/.local/bin/` — writable by the hermes user and persisted via the
`~/.hermes:/opt/data` volume mount. Add `PATH=/opt/data/.local/bin:...` to
`docker-compose.yml` environment so locally-installed runtimes shadow system
binaries for ALL processes (gateway, cron, interactive sessions).

**Architecture:**
```
Hermes cron (daily 10:00 UTC, no_agent, script-only)
  └→ runtime_auto_update.py (runs as hermes user)
       ├→ Node.js: download v22 LTS tarball → extract to .local/lib/node/ → symlink to .local/bin/
       ├→ npm: npm install to .local/lib/npm/ → symlink to .local/bin/
       ├→ uv: download musl binary → copy to .local/bin/
       └→ Silent when all current. Telegram message with ✅/❌ only when something changed.
```

**Bootstrap logic:** If `.local/bin` doesn't have a binary yet, the script
installs it there even if the system version is current. This ensures future
updates always go to the writable location. Once bootstrapped, the script
only acts when `.local/bin` version differs from latest upstream.

**Node.js:** Downloads the v22 LTS binary tarball from nodejs.org, extracts
to `/opt/data/.local/lib/node/`, symlinks `node`, `npx`, `corepack` to
`.local/bin/`. Does NOT symlink npm from the Node tarball — npm is handled
separately to avoid version conflicts.

**npm:** Installs via `npm install npm@latest --prefix /opt/data/.local/lib/npm -g`,
then symlinks `npm` and `npx` from there to `.local/bin/`. npm is pure JS so
no compilation needed.

**uv:** Downloads the musl binary tarball from GitHub releases, extracts,
copies `uv` and `uvx` binaries directly to `.local/bin/`. Falls back to the
astral.sh install script if the GitHub download fails.

**Dedup:** The script is naturally idempotent — if versions match latest, it
exits silently (no state tracking needed for the no-update case). State file
records what was updated and when for auditability.

**Output format:** Human-readable Telegram markdown with ✅/❌ per runtime
and version transitions. NOT raw JSON — `no_agent=true` delivers stdout
verbatim to the user.

**docker-compose.yml PATH change:** Adding `PATH=/opt/data/.local/bin:...` to
the `environment:` section requires a container restart (`docker compose up -d
hermes` from the host) to take effect. Until then, the script self-manages
its own PATH by prepending `.local/bin` at the top of the script.

**Quick reference:** See `references/runtime-update-commands.md` for the
host-side manual fallback commands (when the container is down or you need
to update system-level binaries directly).

### Installer quirks (encountered Jun 2026)

- **uv installer path mismatch:** `curl -LsSf https://astral.sh/uv/install.sh |
  UV_INSTALL_DIR=/usr/local sh` installs the binary to `/usr/local/uv`, NOT
  `/usr/local/bin/uv`. Must follow with `cp /usr/local/uv /usr/local/bin/uv`
  to replace the old binary on PATH. The in-container auto-updater avoids this
  by using the GitHub releases tarball directly and copying to `.local/bin`.
- **npm global install prefix:** `npm install -g npm@latest` alone may install
  to a different prefix than where Node.js bundled npm lives. Use
  `npm install -g npm@latest --prefix /usr/local` to ensure it replaces the
  bundled npm at `/usr/local/lib/node_modules/npm`. The in-container auto-updater
  uses `--prefix /opt/data/.local/lib/npm` to install to the writable location.
- **Node.js binary tarball:** Replace via `tar -xJ --strip-components=1 -C
  /usr/local` from the official `node-v<ver>-linux-<arch>.tar.xz`. No package
  manager needed — the binary tarball overwrites in place. The in-container
  auto-updater extracts to `/opt/data/.local/lib/node/` (writable, persists).
- **uv musl vs gnu:** The container uses the musl build (`aarch64-unknown-linux-musl`).
  The astral.sh installer downloads the gnu build by default. Both work, but
  for consistency the GitHub releases tarball (`uv-aarch64-unknown-linux-musl.tar.gz`)
  is used by the auto-updater. The gnu build from astral.sh also works fine.
- **uv GitHub tarball structure:** The tarball extracts to
  `uv-aarch64-unknown-linux-musl/uv` and `uv-aarch64-unknown-linux-musl/uvx`
  (not `bin/uv`). Use `rglob("uv")` and check `p.is_file()` to find the binary
  — `rglob` matches directories too, so the `is_file()` guard is essential.

15. **Container privilege limits runtime self-updates — SOLVED** — The Hermes
container runs as `uid=10000(hermes)` with no root/sudo and no Docker socket
access. `/usr/local/bin` is not writable. **Previous approach** (Jun 2026):
host-side crontab running `docker exec -u root` + in-container verifier.
**Current approach** (Jun 2026): fully self-contained in-container updater
that installs to `/opt/data/.local/bin/` (writable, persisted via volume mount).
The host-side approach required a host crontab entry that could silently break
(Mac asleep, Docker down). The in-container approach is self-healing — the
Hermes cron runs it, and it works as long as Hermes itself is running. Host-side
`docker exec -u root` commands remain as manual fallback for system-level
binaries or when the container is down. See watchdog #4 above.

16. **no_agent scripts deliver stdout verbatim** — when `no_agent=true`, the
script's stdout is sent directly to the delivery channel (Telegram, Slack,
etc.) with NO LLM processing. Output must be human-readable markdown, NOT raw
JSON. The runtime auto-updater uses emoji (✅/❌) and version transitions in
its output. This is the same pattern as `hermes_auto_update_check.py`.

17. **Bootstrap before idempotency** — when installing runtimes to a new
location (`.local/bin`), the "are we current?" check must account for the
binary not being installed yet. If `.local/bin/node` doesn't exist, the script
must install it there even if the system `node` is already at the latest
version. Otherwise the script stays silent forever and never bootstraps. The
fix: `if current == latest and local_binary_exists: return None` — only skip
when BOTH conditions are true.

18. **npm and Node.js symlink conflicts** — the Node.js binary tarball includes
`bin/npm` (the version bundled with that Node release). If you symlink npm
from the Node tarball AND from a separate `npm install -g npm@latest`, they
conflict. Solution: `update_node()` should only symlink `node`, `npx`, and
`corepack` — NOT `npm`. The `update_npm()` function handles npm exclusively,
installing the latest npm to its own prefix and symlinking from there.

19. **PATH in docker-compose.yml needs container restart** — adding an `environment`
entry for `PATH` in `docker-compose.yml` only takes effect when the container is
recreated (`docker compose up -d hermes` from the host). Until then, scripts must
self-manage PATH by doing `os.environ["PATH"] = f"{LOCAL_BIN}:{os.environ.get('PATH', '')}"`
at the top of the script. The self-managed PATH works for the script's own
subprocess calls but does NOT affect other processes (gateway, other cron jobs).

20. **Concurrent `_atomic_write` temp-file collision in `to_subscriber_lib.py`** — the shared library `to_subscriber_lib.py` used a fixed temp filename (`path.with_suffix(path.suffix + ".tmp")`) for its atomic-write helper. Three cron jobs (`to_subscriber_changes.py`, `to_subscriber_briefing.py`, `to_subscriber_reminder.py`) all fire near :00/:15/:30/:45 and share the same `failed_dms.json` state file. When two processes run simultaneously, one writes the temp file, the other writes the same temp file, then the first tries to rename it — but it's already been renamed by the second. Result: `FileNotFoundError: [Errno 2] No such file or directory: '...failed_dms.json.tmp' -> '...failed_dms.json'`. **Fix:** use a PID-suffixed temp filename (`path.with_suffix(f".{os.getpid()}.tmp")`) and `Path.replace()` (which overwrites the target atomically on POSIX). Also add `path.parent.mkdir(parents=True, exist_ok=True)` before writing and cleanup-on-failure via `try/except` with `tmp.unlink(missing_ok=True)`. This pattern applies to ANY shared state file written by multiple concurrent cron jobs — always use process-unique temp filenames in atomic-write helpers.

21. **Precheck misclassifies `FileNotFoundError` from `os.rename` as `script_file_not_found`** — when a script crashes with `FileNotFoundError` on a runtime file operation (e.g. `os.rename(tmp, target)` where the temp file was already moved by a concurrent process), the precheck's regex classifier matches `FileNotFoundError` and labels it `script_file_not_found` with fix_type `script_path_fix`. This is wrong — the script file exists fine; the `FileNotFoundError` is about the temp file path in the rename operation, not the script itself. **How to tell the difference:** in a genuine `script_file_not_found`, the error says `Script not found: <path>` or `FileNotFoundError` for the `.py` file at the top level. In a runtime `FileNotFoundError`, the traceback shows the error inside a library function (e.g. `_atomic_write`, `os.rename`, `pathlib._local.rename`) for a data file, not the script. When `diagnose` is the recommended action (not `script_path_fix`), always read the full traceback before applying any fix — the classification may be wrong. This is why the watchdog's step 1 says "Confirm the classification is correct."

**Variant: `FileNotFoundError` from `shutil.copy2` on broken symlink in skill `.venv` (2026-07-03).** When `sync-profile-skills.py` (the 6-hourly skill/MCP sync cron job) crashes with `FileNotFoundError` inside `shutil.copy2`, the precheck may misclassify it as `script_file_not_found`. The telltale sign: the traceback path contains `.venv/bin/python3` and the error is inside `shutil.copy2`, not at script startup. **Root cause:** a skill directory (e.g. `resumable-script/evals/`) contains a platform-specific `.venv` with symlinks pointing to paths that don't exist on the current host (e.g. macOS Xcode paths on a Linux container). **Fix:** (a) patch `sync-profile-skills.py` to skip broken symlinks during `os.walk` — add `os.path.islink(src) and not os.path.exists(src)` guard before `shutil.copy2()`; (b) remove the stale `.venv` from the skill directory. After fixing, force-retry: `hermes cron run <job_id>`. This is distinct from the `os.rename` variant — the error is in `shutil.copy2`, not `os.rename`, and the fix is a script patch + directory cleanup, not a concurrency fix.

22. **Trace diagnostic cannot detect stdout contamination on `last_status: ok` jobs** — the watchdog scans for `last_status != "ok"`, but a `sitecustomize.py` banner printing to stdout makes the script produce non-empty output that gets delivered to the user — while the script itself exits 0 (`last_status: ok`). A job delivering 12K+ spam messages over 9 days was invisible to the watchdog because every run "succeeded." **Detection gap:** jobs with `last_status: ok` that have non-empty stdout on every tick (especially high-frequency schedules like `* * * * *`) may be delivering unintended content. A future enhancement could flag `no_agent` jobs where `last_status: ok` AND output files exist for every single tick (indicating non-silent "success"). For now, see `script-first-cron-design` pitfall #24 for the `sitecustomize.py` stderr fix and detection patterns for user-reported "keeps looping" complaints.

23. **Event-bound cron jobs must be paused after the event ends** — a `* * * * *` (every-minute) alert job for a time-bound event (e.g., NCW 2026 weightlifting meet, Jun 20–24) continues firing every minute indefinitely after the event ends. The script produces empty stdout (no triggers match past dates), so it's "silent" — but the cron runner still writes an output file for every tick, accumulating thousands of empty files (12K+ files, 50MB). Worse, if the script's stdout is contaminated (see pitfall #22), the every-minute job spams the user. **Fix:** pause or remove event-bound cron jobs when the event ends: `cronjob action=pause job_id=<id>`. Add an `event_end_date` check inside the script itself as a safety net — if `date.today() > EVENT_END_DATE`, exit 0 immediately without processing. Also clean up accumulated output files: `find /opt/data/cron/output/<job_id>/ -name "*.md" -delete`.

24. **Cron output file accumulation from high-frequency jobs** — jobs running every 5–30 minutes (`every 5m`, `every 15m`, `every 25m`, `every 30m`) accumulate hundreds to thousands of output files in `cron/output/<job_id>/` over weeks. A single every-15m calendar alerts job produced 1,456 files (8.4MB); 5 high-frequency jobs together produced 3,872 files (22MB). **Fix:** routine cleanup keeping only the latest 5 files per job: `ls -t <dir> | tail -n +6 | xargs rm -f`. This should be part of the weekly system tidy-up (`hygiene_guard.py`) or a dedicated cron audit. The `cron/output/` directory is diagnostic only — old output files have no runtime purpose.

25. **WhatsApp delivery target errors when bridge is down** — when a cron job has `deliver: "telegram,whatsapp:..."` and the WhatsApp bridge is down (no `creds.json`, Baileys not paired), every cron tick produces a delivery error in `errors.log`. The Telegram delivery succeeds, but the WhatsApp failure logs an error every tick. **Fix:** remove the WhatsApp delivery target from the job (`cronjob action=update job_id=<id> deliver=telegram`) until the bridge is re-paired. The WhatsApp bridge health watchdog (watchdog #5) already alerts when the bridge is down — the delivery error is redundant noise. Do NOT disable the job itself — just narrow the delivery target.

27. **`script_file_not_found` caused by full shell pipeline in script field** — a fourth variant beyond the full-command (pitfall #17), subdirectory-prefix (pitfall #18), and HERMES_HOME-override (pitfall #19) variants. The `script` field contains a multi-command pipeline (`cd /opt/data && python3 /path/to/script.py "arg" --json 2>&1 | grep -v "banner"`). The cron runner prepends its scripts dir to the entire string, producing `${HERMES_HOME}/scripts/cd /opt/data && python3...` — shell operators (`cd`, `&&`, `|`, `2>&1`, `grep`) mid-path are the telltale sign. **Fix:** create a wrapper script at `${HERMES_HOME}/scripts/<name>.py` that calls the real script via `subprocess.run()` with timeout and output parsing, then `hermes cron edit <job_id> --script "<name>.py"`. The wrapper pattern is preferred over trying to shorten the pipeline into a one-liner — it's testable, handles timeouts, and survives future changes to the underlying script. See `script-first-cron-design` reference `cron-script-pipeline-wrapper.md` for the full template. This was found when the triage-model-warmup job (ID `YOUR_CRON_JOB_ID`) failed on Jun 2026 — the script field was `cd /opt/data && python3 /opt/data/skills/productivity/triage/scripts/triage.py "hello" --json 2>&1 | grep -v "\[slack-enhancements\]"`.

28. **Routine cron audit pattern (weekly)** — a systematic audit of all cron jobs should check: (a) stdout contamination in latest output files, (b) stale schedules (event-bound jobs still running past event end), (c) output file accumulation (high-frequency jobs with >100 files), (d) delivery errors from broken platforms, (e) jobs with `last_status: error`, (f) jobs that never ran (`last_status: null`). The audit can be a `no_agent` script that reads `cron/jobs.json` + scans `cron/output/` and reports only actionable findings. See `references/cron-audit-pattern.md` for the full implementation.

29. **Post-fix verification: force-run the job after applying a fix, don't just assume it worked.** When the trace diagnostic applies a `script_path_fix` (or any fix), the script may now execute but still fail with a different error (e.g. Google Sheets API 404 because the sheet doesn't exist). The fix was correct — the script is found and runs — but the job is still unhealthy. **Always force-run after fixing:** `hermes cron run <job_id>` and check `last_status`. If it still fails, read the latest output file to diagnose the new error. Don't mark the repair as `verified` until `last_status: ok`. If the new error is a data/permission issue (missing sheet, expired token, wrong account), pause the job to prevent repeated failures and surface to the user. This was encountered Jul 2026: the WhatsApp Approval Reply Listener's `script_file_not_found` was correctly fixed (wrapper script created, job updated), but the job then failed with a Google Sheets 404 — a separate data issue that required pausing the job.

## Related Skills

- `script-first-cron-design` — the foundational pattern all four watchdogs follow
- `hermes-agent` — CLI reference for cron job management
- `cron-llm-review-house-style` — shared formatting style for cron output
- `references/cron-audit-pattern.md` — weekly cron audit: contamination detection, stale schedule cleanup, output file accumulation, delivery error fixes