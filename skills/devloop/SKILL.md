---
name: devloop
description: >
  Autonomous end-to-end build/debug engine. Use it when asked to build, implement,
  fix, or debug a module/feature: it runs the WHOLE loop unattended — drafts a
  checkable Definition of Done, fail-closed gates it (vague or ambiguous requests
  come back with the blocking questions instead of guesses), generates tests, then
  loops implement -> lint -> evidence until coverage + two distinct-model judges +
  real exit codes + a whole-suite regression gate all pass — and on COMPLETE
  AUTO-MERGES the work into the target repo's current branch (no repo named = a
  fresh workspace under the write-safe root is the deliverable). Prefer this over
  the `dev` skill for any multi-file task whose outcome should be verified, merged
  code rather than role-by-role assistance. NOT for trivial one-shot asks (a quick
  answer, a one-line edit, running a command) — just do those directly.
  Run: `devloop "<request>" [--repo PATH]` (or python3
  ${HERMES_HOME}/skills/software-development/devloop/scripts/devloop_cli.py) —
  see "How to run".
version: 1.0.0
author: agent
metadata:
  hermes:
    tags: [sdlc, autonomous, multi-file, correctness, dod, headless]
    related_skills: [ask]
    category: software-development
---

# devloop — the SDLC engine

> **This file is documentation, not a prompt.** The ENGINE never loads it; a chat model
> reads it (via skill discovery) to learn the run commands below. Edit code/prompts in
> `dispatch.py` to change behavior; edit this file only to keep the description honest.

## How to run

```bash
# greenfield (no repo named): builds in a fresh scratch workspace = the deliverable
devloop "Create slug.py with slugify(text): lowercase, trim, hyphen-join words."

# modify an existing repo (path must be a git repo; NOT the write-safe root itself)
devloop "Make normalize(s) raise ValueError on empty input" --repo /opt/data/myproject

# debug form: fold failing code + error into the request
devloop "fix the retry logic" --repo /opt/data/myproject \
        --debug-code "$(cat client.py)" --error "AssertionError: expected 3 attempts"

# PR-style workflow: keep the verified branch instead of auto-merging (exit 0 iff kept)
devloop "add rate limiting to the client" --repo /opt/data/myproject --keep-branch

# host one-liner (the `devloop` shim lives at /opt/data/.local/bin, on the container PATH):
docker exec hermes devloop "build ..." [--repo ...] [--keep-branch]
# canonical form if the shim is ever missing:
python3 ${HERMES_HOME:-/opt/data}/skills/software-development/devloop/scripts/devloop_cli.py "..."
```

### Invocation surfaces

1. **`scripts/devloop_cli.py`** (primary; the `devloop` shim) — a chat model discovers this
   skill and runs the CLI; a human runs it via `docker exec`. Repo targeting is EXPLICIT
   (`--repo` or a fresh scratch workspace — never the implicit cwd, which from an agent session
   can be the ~/.hermes data repo itself).
2. **`ask`'s `pipeline.py` CLI** (`skills/productivity/ask/scripts/pipeline.py "<msg>"`) —
   triage + routing decide; `test_first`/`debug_cascade` dispatch to
   `devloop_bridge.run_build`/`run_debug`.
3. **`scripts/devloop_pipeline_cli.py`** — the SCOUT → BUILD pipeline for goals that need a
   plan first: relentless-solve scouts the happy path read-only, then each returned step runs
   through verified devloop. See `references/scout-pipeline.md`.

Both surfaces default to a **fresh scratch workspace** when no repo is named. Both go through
`call_guarded` (any runtime error fails CLOSED as a HUMAN_REVIEW-shaped error, never a silent
single-shot) → `runner.run_task` → `loop.run_v1`. Debug is not a separate engine: `run_debug`
folds the failing code + error into the request and runs the same build loop.

### Environment knobs

| Env var | Default | Meaning |
|---|---|---|
| `DEVLOOP_ENABLED` | ON | Kill-switch for the `ask` pipeline seam only. `0/false/no/off` = pipeline falls back to one unverified single-model dispatch. |
| `DEVLOOP_DIR` | derived from pipeline.py | Import path for the bridge (override for a relocated devloop tree). |
| `DEVLOOP_PLANNER` / `DEVLOOP_REFINER` / `DEVLOOP_ADVISOR` / `DEVLOOP_DESIGNER` / `DEVLOOP_CODER` / `DEVLOOP_JUDGE_A` / `DEVLOOP_JUDGE_B` / `DEVLOOP_DIAGNOSER` | see `dispatch.py` | Per-phase model roster. `assert_distinct_models` enforces coder ≠ designer ≠ judge_a ≠ judge_b. |
| `DEVLOOP_DISPATCH_TIMEOUT_S` | floor in `dispatch.py` | RAISE-only per-model-call ceiling (`max(floor, env)`). There is no whole-run wall clock; length is bounded by back-off caps, not time. |
| `HERMES_BIN` | `/opt/hermes/bin/hermes` | The chat binary dispatchers shell out to. |
| `DEVLOOP_GIT_NAME` / `DEVLOOP_GIT_EMAIL` | `devloop` / `devloop@hermes` | Commit identity for devloop-authored commits/merges. |
| `DEVLOOP_DEBUG` | off | `1` = capture every model call's FULL prompt + raw reply into the run's inspection bundle. |
| `DEVLOOP_NO_COMMIT_LLM` | off | `1` = skip LLM-driven commit message synthesis; use template fallback. |
| `DEVLOOP_PROGRESS` | `verbose` | `verbose` / `compact` / `quiet` — see `references/observability-testing.md`. |
| `HERMES_WRITE_SAFE_ROOT` | `/opt/data` | Scratch repos and durable traces live under it. Worktrees are IN-REPO at `<repo>/.worktrees/`. |
| `DEVLOOP_RELENTLESS_SCRIPT` | ladder | Where the scout pipeline finds relentless-solve. |

## What comes back

(devloop always prints a human summary to stdout; add `--json` for the raw dict.)

- **COMPLETE** (exit 0) → `merged into '<target branch>' at <repo>` — the work is IN the target
  tree (`devloop_result.code_path`). The `devloop/<name>` branch is deleted and the work lands as
  ONE SQUASH commit with a rich message, followed by the **grounding block**
  (`grounding (promise -> proof):` — per criterion: proving tests, judge votes, passing evidence).
  If the target branch advanced during the run, devloop first merges the target into the run branch
  and re-runs the whole-suite regression on the COMBINED tree; sync conflicts go to the coder LLM
  (never test files, no markers may remain) and a red combination gets ONE bounded LLM fix. The
  regression gate always decides. If merge still cannot apply safely (dirty target / unresolved
  conflict / red combination / detached HEAD / branch switch), it degrades to a kept
  `devloop/<name>` branch and exits 1. See `references/terminal-contract.md` for the full exit
  code contract and ref-CAS landing mechanics.
- **COMPLETE with `--keep-branch`** → the verified `devloop/<name>` branch is KEPT unmerged
  (PR-style workflows). The summary prints the manual merge command; exit 0 iff the branch was
  actually kept.
- **NEEDS YOUR INPUT** (exit 2) → blocking questions + a copy-pasteable re-run line. Every invoke
  is fresh; answer by re-running with `— ANSWERS: ...` appended. Ships the partial **grounding
  block** too — ✗ rows name exactly which promises were left unproven.
- **Failure** (exit 1) → reason + trace path. Exit code 0 is a hard contract: it means a real,
  gate-verified COMPLETE whose outcome landed (merged, or kept under `--keep-branch`) — nothing
  else.

Workspaces: `<write-safe>/devloop-workspaces/<name>`; durable inspection bundle:
`<write-safe>/devloop-traces/<name>/` — trace.jsonl, checkpoint.json, charter.json,
design_spec.json, rendered_tests.json, judge_verdicts.json, attempts.jsonl, grounding.json,
**progress.jsonl** (2026-07-07), and (with `DEVLOOP_DEBUG=1`) dispatch/ with every model
call's full prompt + raw reply. Render the trace with `trace_view.py <trace>`;
`trace_view.py --chain <trace>` pivots per criterion.

## Daily digest

`scripts/devloop_digest.py` (2026-07-07) — a script-first, zero-LLM daily summary of all
devloop runs in the last 24h. Reads `progress.jsonl` (preferred) or `trace.jsonl` (fallback)
from every trace bundle. Emits markdown: run count, terminal breakdown, avg/p95 wall-clock,
failure modes, learning themes. Silent on empty (exit 0, no output). JSON mode for piping
(`--json`). Cron job `6fcb443fd52b` runs it daily at 12pm UTC (5am PT), delivers to Slack.

```bash
python3 scripts/devloop_digest.py           # markdown, last 24h
python3 scripts/devloop_digest.py --hours 48  # custom window
python3 scripts/devloop_digest.py --json     # machine-parseable
```

## Trust boundary

Run devloop only on repos you own/trust, under the write-safe root. Repo content (symbol names,
test source, failing output) and the raw request flow into model prompts unescaped, and the coder
holds file+terminal tools inside the worktree — a hostile repo is a prompt-injection surface.
Evidence subprocess exit codes are the only trusted signal. Known residual: the ref-CAS protects the
ref update but not the shared index/worktree squash transaction; see `references/terminal-contract.md`.

## Pitfalls

A catalog of live-caught failure modes and current mitigations. Each entry links to the full write-up.

| Pitfall | Status | Link |
|---|---|---|
| ANSWERS from HUMAN_REVIEW never reached the designer | FIXED 2026-07-05 | [human-review-recovery.md](references/human-review-recovery.md) |
| Generated tests used string literals for datetime | FIXED 2026-07-05 | [render-py-bugs-2026-07-05.md](references/render-py-bugs-2026-07-05.md) |
| `mock.patch` at module level / Mock without call inspection | FIXED — pre-judge static gate | [three-layer-defense-2026-07-05.md](references/three-layer-defense-2026-07-05.md) |
| Judge distrust gave no actionable reason text | FIXED 2026-07-05 | [three-layer-defense-2026-07-05.md](references/three-layer-defense-2026-07-05.md) |
| Quality-lint failures routed straight to HUMAN_REVIEW | FIXED 2026-07-05 | [quality-lint-redesign-2026-07-05.md](references/quality-lint-redesign-2026-07-05.md) |
| GLM-5.2 returned bare strings for assumptions/open_questions | FIXED 2026-07-05 | [glm-charter-bare-strings-2026-07-05.md](references/glm-charter-bare-strings-2026-07-05.md) |
| Calendar-quick-add passed unit tests but failed against real gws CLI | MITIGATED | [e2e-verification-gap-2026-07-05.md](references/e2e-verification-gap-2026-07-05.md) |
| Charter under-decomposed named deliverables | MITIGATED | [validation-run-learnings-2026-07-05.md](references/validation-run-learnings-2026-07-05.md) |
| All-unit criteria missed integration surfaces | MITIGATED | [validation-run-learnings-2026-07-05.md](references/validation-run-learnings-2026-07-05.md) |
| Rich journaling / commit message extraction was incomplete | FIXED 2026-07-05 | [rich-journaling-advisor-review-2026-07-05.md](references/rich-journaling-advisor-review-2026-07-05.md) |
| Overfit audit was sequential and dominated wall-clock | FIXED 2026-07-05 | [validation-run-learnings-2026-07-05.md](references/validation-run-learnings-2026-07-05.md) |
| Zero progress output during long runs | FIXED 2026-07-06, expanded 2026-07-07 | [advisor-review-progress-phase1-2026-07-06.md](references/advisor-review-progress-phase1-2026-07-06.md) |
| Calendar-quick-add e2e dry-run gate | AGAINST by advisors | [advisor-consensus-fixes-2026-07-05.md](references/advisor-consensus-fixes-2026-07-05.md) |

See also the in-depth walkthroughs:
- `references/engine-pipeline.md` — 9-step build pipeline
- `references/scout-pipeline.md` — scout → build pipeline
- `references/terminal-contract.md` — exit codes + merge mechanics
- `references/observability-testing.md` — progress output, trace format, and testing tiers
- `references/improvement-loop.md` — how to safely improve devloop itself

## Deliberately NOT built

- **Council stop-gate** — `gate.council_gate` exists + tested but NOT wired into the stop.
- **Blocking overfit advisory** — split votes are non-blocking advisories only.
- **Holdout criteria split** — deleted (coder reads test files; hiding cannot work).
- **Project outer loop** — built + tested; live caller is the scout pipeline only.
- **Free-form designer + blast_radius.py** — deleted 2026-07-01.
- **Async HUMAN_REVIEW** (Telegram/cron resume) — not built; HUMAN_REVIEW is a synchronous terminal.
- **Token/cost accounting** — infeasible (`hermes chat -q` exposes no usage payload).
- **Multi-language verification** — pytest/Python-only; non-Python requests fail closed after
  charter/design.
