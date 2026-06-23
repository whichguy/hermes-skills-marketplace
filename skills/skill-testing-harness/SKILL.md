---
name: skill-testing-harness
description: Validate skills before unattended/cron use — reusable test + contract
  harness in skills/_testkit. Discovers tests/ dirs, runs pytest (via uv) or stdlib
  unittest, lints frontmatter/script-refs/secrets, fail-closed.
platforms:
- linux
- macos
- windows
version: 1.0.0
author: Fortified Strength
license: MIT
metadata:
  hermes:
    config:
    - key: skill-testing-harness.enabled
      description: Enable skill-testing-harness skill behavior
      default: true
      prompt: Enable skill-testing-harness skill?
    tags:
    - skill
    category: software-development
---
---

# Skill Testing Harness

Make skills **trustworthy to run unattended** by adding reusable, rerunnable validation.
Mirrors the proven `personal-context/` pattern (manifest + fail-closed runner). Read-only,
mocks only — never hits live network.

## When to use
- Before relying on a skill for **cron / unattended** work.
- After editing any skill that ships executable scripts.
- As a periodic health gate across all skills.

## Environment facts (drive the design)
- **No `pytest`/`pip` installed**; PEP-668 managed env. `uv` IS installed.
- New tests prefer **stdlib `unittest`** (runs with bare `python3`, like personal-context),
  so they work even without uv. Existing pytest-style suites run via `uv run --with pytest`.

## Commands

```bash
# Full gate (contract check + test harness), fail-closed:
python3 /opt/data/skills/_testkit/validate_skills.py

# Filter to matching skills (substring):
python3 /opt/data/skills/_testkit/validate_skills.py google-workspace

# Stages individually:
python3 /opt/data/skills/_testkit/validate_skills.py --contract-only
python3 /opt/data/skills/_testkit/validate_skills.py --tests-only
python3 /opt/data/skills/_testkit/validate_skills.py --no-uv   # skip pytest-style suites
```

Components in `skills/_testkit/`:
- `validate_skills.py` — orchestrator (runs both stages, prints PASSED/FAILED).
- `skill_contract_check.py` — frontmatter valid, referenced scripts exist, syntax OK, no secrets.
- `run_skill_tests.py` — discovers each skill's `tests/`, runs pytest (uv) or stdlib unittest, scorecard.
- `PLAN.md` — testability scorecard / priorities across all skills.

## Test taxonomy
- **System test** — real deterministic logic with synthetic inputs (parsers, normalizers,
  routing/provenance, fail-closed guards). No network.
- **Mock test** — stub external APIs (Google, WhatsApp bridge, HTTP) to validate
  request-shaping, response-handling, retry/error paths.
- **Contract/lint check** — non-test assertions: SKILL.md frontmatter, referenced scripts
  exist, `--help` works, no secrets committed.

## Authoring a new test suite
1. Create `skills/<skill>/tests/test_*.py`.
2. Prefer stdlib `unittest` so it runs without uv. Mock all network (`unittest.mock`).
3. For API skills: assert the request URL/params, parse a **canned** response, and cover an error path.
4. Run `validate_skills.py <skill>` — must be green before cron use.

## Fixing doc-drift: verify replacement commands before writing them

When the contract check flags a SKILL.md referencing a script/command that doesn't exist
(doc-drift), the fix is to point the doc at what actually works — but a **confident-but-wrong
replacement is worse than the original honest gap.** Before writing any "use this instead"
command:

1. **Confirm the missing artifact is truly gone** — check the local skill dir AND any install
   copy (e.g. `/opt/hermes/skills/...`). It may have moved/renamed (restore the real path) vs.
   never shipped (document an equivalent).
2. **Verify the replacement actually does the job** — grep the script's argparse/usage or run
   `--help`; don't infer a flag exists. (Real example: wrote `pack.py --unpack` from inference,
   then found `pack.py` only packs — corrected to `unzip file.pptx -d out/`, since a .pptx
   genuinely IS a zip.)
3. **Prefer verifiable primitives** (`unzip`, `soffice --headless`, stdlib) over guessing at a
   skill-local helper that may not exist.
4. When a documented script simply was never bundled, **say so explicitly** in the doc (a short
   "not shipped here — use X instead" note) rather than silently rewriting as if it always worked.

This applies to ANY edit that documents a command as the canonical way to do something, not just
drift fixes. Inventing plausible commands is the doc equivalent of fabricating test output.

## Guardrails (fail-closed)
- Tests are **read-only / no network**; mocks only. Never hit live Google/WhatsApp.
- Never commit secrets/tokens into fixtures.
- Missing test dir, zero tests discovered, or import error = **FAIL**.
- Don't touch skills under another Hermes profile.
