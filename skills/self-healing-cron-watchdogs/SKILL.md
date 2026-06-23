---
name: self-healing-cron-watchdogs
description: 'Three cooperating cron watchdogs that keep Hermes self-healing: trace
  diagnostic+auto-fix, npm dependency updates (3-day-behind), and pip dependency updates
  (3-day-behind).'
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

Three cooperating cron jobs that implement the "Loop Engineering" pattern
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
| Missing dependency | Install via `uv pip install` or modify script | ✅ Yes |
| Container/image issue | Run `hermes_auto_update_check.py`, Watchtower handles rest | ✅ Yes |
| Rate limited | Wait for next tick | No action needed |
| Google OAuth expired | Surface to Jim | ❌ Surface |
| Unknown error | delegate_task diagnoses, applies safe fix | ✅ If safe |

**Safe fixes** (always auto-applied, even on sensitive jobs):
- `model_swap` — changes which LLM provider runs the job (config-only, never touches data)
- `watchtower_check` — checks container image freshness (read-only)
- `rate_limit_wait` — no action needed

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
- `/opt/data/scripts/whatsapp-bridge` (scripts copy of the same)
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

**Apply:** `uv pip install --python /opt/hermes/.venv/bin/python <package>==<version>` (one at a time, never bulk)

**Batch strategy:** Non-critical/non-major first → critical → major bumps last.

## Integration with Watchtower

The Hermes Docker container is labeled `com.centurylinklabs.watchtower.enable=true`.
Watchtower runs daily at 10:30 UTC and auto-updates the container image when a
new one is pushed to `nousresearch/hermes-agent:latest`.

The self-healing watchdog (watchdog #1) integrates with Watchtower via the
`watchtower_check` fix type: when a cron job fails with a container/image error,
the LLM runs `hermes_auto_update_check.py` to verify the container is running
the latest image. If stale, Watchtower will update it on its next cycle.

The pip watchdog (watchdog #3) explicitly does NOT update `hermes-agent` —
that's Watchtower's job via image updates.

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
python3 /opt/data/scripts/cron_trace_diagnostic.py

# npm: should find express/pino/baileys updates
python3 /opt/data/scripts/npm_dependency_watch.py

# pip: should find ~50 outdated packages >3 days old
python3 /opt/data/scripts/pip_dependency_watch.py

# Idempotency test: second run should be silent
python3 /opt/data/scripts/cron_trace_diagnostic.py  # silent if no new failures
python3 /opt/data/scripts/npm_dependency_watch.py   # silent (state file dedup)
python3 /opt/data/scripts/pip_dependency_watch.py  # silent (state file dedup)
```

## State Files

| File | Purpose |
|---|---|
| `cron/state/trace_repairs.json` | Failure → repair tracking (attempts, status, fix applied) |
| `cron/state/npm_update_state.json` | Already-notified npm versions |
| `cron/state/pip_update_state.json` | Already-notified pip versions |

### Provider health check (non-sensitive jobs only)

Before swapping a failing job's provider, verify whether the provider is actually unhealthy or if the failure was transient:

1. `hermes cron list` — scan all jobs' `Last run` lines for the same provider/model
2. If other jobs using the same provider are succeeding → failure was likely transient → force-retry: `hermes cron run <job_id>`
3. If other jobs using the same provider are also failing → provider is unhealthy → swap model via `hermes cron edit <job_id>` (or `hermes config set` if global)
4. Also run `python3 /opt/data/scripts/anthropic_credit_guard.py --dry-run` to check the credit guard's view of Anthropic API health

This cross-reference technique prevents unnecessary model swaps when a single job hit a one-off upstream error.

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

## Related Skills

- `script-first-cron-design` — the foundational pattern all three watchdogs follow
- `hermes-agent` — CLI reference for cron job management
- `cron-llm-review-house-style` — shared formatting style for cron output