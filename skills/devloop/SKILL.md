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

# Keep the worktree directory for inspection (skip finalize, leave all artifacts in place)
devloop "add rate limiting to the client" --repo /opt/data/myproject --keep-worktree

# host one-liner (the `devloop` shim lives at /opt/data/.local/bin, on the container PATH):
docker exec hermes devloop "build ..." [--repo ...] [--keep-branch] [--keep-worktree]
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
| `DEVLOOP_PLANNER` / `DEVLOOP_REFINER` / `DEVLOOP_ADVISOR` / `DEVLOOP_DESIGNER` / `DEVLOOP_CODER` / `DEVLOOP_JUDGE_A` / `DEVLOOP_JUDGE_B` / `DEVLOOP_TIEBREAKER` / `DEVLOOP_DIAGNOSER` | see `dispatch.py` | Per-phase model roster. `assert_distinct_models` enforces coder ≠ designer ≠ judge_a ≠ judge_b ≠ tiebreaker. |
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
| Progress mechanism: open-append-close-per-event | FIXED 2026-07-07 (sync cron) | [references/progress-jsonl-test-patterns.md](references/progress-jsonl-test-patterns.md) |
| Digest schema mismatch: parser expected `kind=tool_ok`, actual format is `{ts, step, ...data}` | FIXED 2026-07-07 | [references/progress-jsonl-test-patterns.md](references/progress-jsonl-test-patterns.md), [references/progress-jsonl-contract-2026-07-08.md](references/progress-jsonl-contract-2026-07-08.md) |
| Calendar-quick-add e2e dry-run gate | AGAINST by advisors | [advisor-consensus-fixes-2026-07-05.md](references/advisor-consensus-fixes-2026-07-05.md) |
| Ruff not found on PATH — lint gate silently fell back to py-syntax-only | FIXED 2026-07-08 | [references/linter-reference.md](references/linter-reference.md) |
| 9 phases ran with no progress marker (design result, lint, frozen_tests, rebuild, replan, test_repair, commit_scope, evidence rebuild, lint_discovery) | FIXED 2026-07-08 | [references/observability-testing.md](references/observability-testing.md) |
| 13 phases had only single markers (start OR complete, not both) — user couldn't tell when long phases like judge (21s) or implement (34s) began vs finished | FIXED 2026-07-08 (start/completed pairing) | [references/observability-testing.md](references/observability-testing.md) |
| Lint discovery probed all 15 file types on every run; unknown file types silently skipped with no research flag | FIXED 2026-07-08 (discover(paths) fast path + research flag) | [references/linter-reference.md](references/linter-reference.md) |
| Pre-clarify hook checked wrong NBQ key (`result["questions"]`) — always found empty list, skipped even on vague requests | FIXED 2026-07-08 (check `bucket` then `all_scored` then `questions` as fallback) | [references/nbq-investigator-integration.md](references/nbq-investigator-integration.md) |
| Pre-clarify hook not gated behind `DEVLOOP_RUN_REAL=1` — deterministic tests with real judges hung on NBQ model call | FIXED 2026-07-08 (gate behind same env var as e2e tests) | [references/nbq-investigator-integration.md](references/nbq-investigator-integration.md) |
| No automated test to prevent drift between `linter-reference.md` and `lint._LANGUAGES` | FIXED 2026-07-08 (10 sync tests: extension coverage, linter names, discover(paths), research flag, py linter availability) | [references/linter-reference.md](references/linter-reference.md) |
| Pre-clarify hook added as default, then removed — deterministic gates already handled underspecification for free; the hook was solving a solved problem | FIXED 2026-07-08 (made opt-in; lesson: check if existing architecture already covers the need before adding a new layer) | [references/nbq-investigator-integration.md](references/nbq-investigator-integration.md) |
| 7 of 23 progress markers were unpaired (3 begin-no-end bugs: charter, ambiguity_gate, complete; 4 end-no-begin: coverage, lint_discovery, quality_lint, stop_check) — user couldn't tell when phases started vs finished | FIXED 2026-07-08 (added ✅ end markers for charter/ambiguity_gate/complete, ⏳ begin marker for lint_discovery; coverage/quality_lint/stop_check are instant single-call checks that don't need begin markers) | [references/observability-testing.md](references/observability-testing.md) |
| Pipeline return type annotations missing — `consolidate_questions` returns `list[dict]` not `tuple`, but no annotation enforced this; a mock returning a tuple caused a silent hang | FIXED 2026-07-08 (12 stage functions annotated with `from __future__ import annotations`; contract test + MOCKING.md + _helpers.py) | [references/nbq-investigator-integration.md](references/nbq-investigator-integration.md) |
| Mocking full NBQ pipeline is brittle — mocking individual stages works for fast-rank but the full pipeline path calls internal functions (`reset_usage`, `get_usage`, `voi.question_similarity`) that aren't easily mockable; the `_run_mocked` helper pattern isolates mock setup from test assertions | MITIGATED 2026-07-08 (`_run_mocked` helper in `test_nbq_contract.py`; `_mock_pipeline(n)` + `_fake_round(n)` helpers; `_helpers.py` shared module) | [references/nbq-investigator-integration.md](references/nbq-investigator-integration.md) |
| Control channel markers were thin on insight — begin markers said "coder attempt 0" without saying how many criteria, end markers said "linting" without saying how many files checked/skipped, complete marker was missing entirely | FIXED 2026-07-09 (enriched 8 markers with "what and why": implement begin/end, lint begin/end, evidence begin, judge end, overfit_audit end, complete end; every marker now carries file counts, criterion counts, and outcome context) | [references/observability-testing.md](references/observability-testing.md) |
| 5 high-risk functions had zero tests (gate.audit_tests, gate.stop_condition, loop._do_implement, devloop_bridge._regression_check, dispatch.resolve) — advisor review identified them as P1 gaps | FIXED 2026-07-09 (28 new tests across 4 files; 528→556 tests; patterns: sys.modules mocking for lazy imports, fake implement lambdas, mock _chat for dispatch, deterministic gate tests with fake Evidence) | [references/observability-testing.md](references/observability-testing.md) |
| 3 P2 areas had zero tests (worktree._resolve_conflicts, worktree._sync_and_verify, core-pipeline integration) — advisor review identified them as P2 gaps | FIXED 2026-07-09 (18 new tests across 2 files; 556→574 tests; patterns: real git repos with _init_repo, check=False for merge commands, cross-module integration pipeline, state lifecycle round-trip) | [references/observability-testing.md](references/observability-testing.md) |
| No correlation IDs in progress markers — parallel runs or retries produced interleaved markers impossible to attribute to a specific run | FIXED 2026-07-09 (8-char hex `run_id` from `uuid.uuid4().hex[:8]` in every `_progress`/`_progress_event` call; visible in stderr markers as `[a3f1]` prefix and in `progress.jsonl` records) | [references/observability-testing.md](references/observability-testing.md) |
| No crash markers — a mid-phase crash left the last marker as ⏳, indistinguishable from a hung run | FIXED 2026-07-09 (`_progress_crash(run_dir, step, exc)` emits ❌ with exception type + truncated traceback; wired into 3 exception handlers in `loop.py` + `runner.py`'s top-level `BaseException` handler) | [references/observability-testing.md](references/observability-testing.md) |
| No automated validation of control channel markers — manual audit was the only way to detect unpaired begin/end markers | FIXED 2026-07-09 (`test_marker_validation.py`: validates begin/end pairing, run_id presence, crash marker traceback, and end-to-end marker emission; 590 tests total) | [references/observability-testing.md](references/observability-testing.md) |
| Multi-file E2E test flaky (~50% HUMAN_REVIEW due to judge non-determinism) — poisoned CI signal | MITIGATED 2026-07-09 (quarantined behind `DEVLOOP_RUN_MULTIFILE=1`; per-judge verdict logging to `judge_verdicts.jsonl` for 20-run diagnostic sprint; advisors explicitly warned against retry-wrapping — the flakiness IS the signal) | [references/observability-testing.md](references/observability-testing.md) |
| Per-judge verdict log written to run_dir (inside worktree) — destroyed on finalize; E2E tests bypass the bridge so `_preserve_trace` never copies it out | FIXED 2026-07-09 (dual-write: run_dir + persistent `/opt/data/devloop-diagnostics/judge_verdicts.jsonl`; survives worktree cleanup and test teardown regardless of invocation path) | [references/observability-testing.md](references/observability-testing.md) |
| No way to keep worktree directory for inspection — `keep_branch` only controls the git branch, not the directory; E2E tests and direct `runner.run_task` calls bypass the bridge's `_preserve_trace` | FIXED 2026-07-09 (`keep_worktree=True` parameter threaded through `runner.run_task` → `devloop_bridge._run` → `run_build`/`run_debug`; skips `worktree.finalize()` on both happy and crash paths; complements `keep_branch`) | [references/observability-testing.md](references/observability-testing.md) |
| Judge non-determinism causes ~50% HUMAN_REVIEW on multi-criteria runs — split votes (judge_a YES, judge_b NO) with no resolution mechanism; retry-wrapping would mask the signal | MITIGATED 2026-07-09 (tiebreaker judge: 3rd model called ONLY on split votes; majority 2-of-3 wins; `TIEBREAKER` model config in `dispatch.py` defaults to `deepseek-reasoner:cloud` — different provider from both judges and coder; tiebreaker votes + reasons logged to `judge_verdicts.jsonl`; cost added only on disagreements, not every criterion) | [references/observability-testing.md](references/observability-testing.md) |
| `lint_discovery` progress marker always reports "0 linter(s) available" — `lint.discover()` returns a list of dicts, but `loop.py:757` calls `.get("linters", {})` as if it were a dict, so the count is always zero regardless of actual available linters | FIXED 2026-07-09 (iterate the list: `sum(len(r["available"]) for r in _discovery if r.get("covered"))`; independently caught by all 3 advisor seats — DeepSeek, Kimi, GLM — in a structured 3-area review) | [references/advisor-review-2026-07-09.md](references/advisor-review-2026-07-09.md) |
| No end-of-run summary — COMPLETE marker was missing entirely, HUMAN_REVIEW marker said only "test fault" without criteria counts, untrusted breakdown, or overfit/quality-lint findings; user had to read the grounding block to understand the full outcome | FIXED 2026-07-09 (`_run_summary` helper builds a one-line rollup from charter criteria + test_to_criterion + overfit suspects + quality findings; emitted as `✅ complete` or `❌ HUMAN_REVIEW` marker; degrades gracefully to "done" when charter is unavailable) | [references/end-of-run-summary.md](references/end-of-run-summary.md) |

See also the in-depth walkthroughs:
- `references/engine-pipeline.md` — 9-step build pipeline
- `references/scout-pipeline.md` — scout → build pipeline
- `references/terminal-contract.md` — exit codes + merge mechanics
- `references/observability-testing.md` — progress output, trace format, and testing tiers
- `references/linter-reference.md` — catalog of all 15 file types the lint gate covers, which linters are wired vs available, and priority-ranked recommendations for additions
- `references/nbq-investigator-integration.md` — how NBQ + investigator integrate with devloop (scout uses them at the goal layer; devloop's pre-clarify hook uses them at the task layer for direct calls)
- `references/improvement-loop.md` — how to safely improve devloop itself
- `references/e2e-verification-workflow.md` — three-track parallel e2e pipeline for verifying devloop changes with real models (devloop smoke + NBQ + investigator)
- `references/e2e-test-suite.md` — 9-scenario E2E test suite with structured runner (2026-07-09). Replaces the old single-scenario smoke test. Covers diverse task types including non-Python JSON output. Runner captures control channel markers, judge verdicts, and produces a structured JSON report. Run with `DEVLOOP_RUN_REAL=1 python3 tests/test_e2e_suite/runner.py`.

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
