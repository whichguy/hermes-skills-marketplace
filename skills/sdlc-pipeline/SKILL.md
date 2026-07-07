---
name: sdlc-pipeline
description: SDLC-specific decomposition playbook for routing research→implement→review
  chains through Kanban with shared git worktree workspaces. Knows how to create
  Hermes projects, worktree branches, and linked task chains with the right assignees
  and skills. Use when the user's request involves software development lifecycle
  patterns (research, design, implement, test, review, deploy, verify).
version: 1.0.0
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - kanban
    - sdlc
    - multi-agent
    - orchestration
    related_skills:
    - kanban-orchestrator
    - test-driven-development
    - multi-model-code-review
    config:
    - key: sdlc-pipeline.enabled
      description: Enable SDLC pipeline auto-decomposition
      default: true
    category: devops
author: The User
license: MIT
---

> **RETIRED (2026-07-01): the legacy SDLC engine this playbook drove (`sdlc.py`,
> `sdlc_state.py`, `sdlc_parallel.py`, `kanban-sdlc.sh`) was deleted — devloop
> (`skills/software-development/devloop/`) is the SDLC engine now. Build/debug tasks
> route to devloop automatically via the `ask` pipeline; do NOT follow the
> engine-specific instructions below. This file is kept as a historical record of the
> decomposition patterns and pitfalls.**


# SDLC Pipeline — Decomposition Playbook

> This skill provides **SDLC-specific** decomposition knowledge. The generic
> Kanban Auto-Routing trigger lives in SOUL.md. This skill knows *how* to
> decompose an SDLC request into the right Kanban tasks with the right
> worktree, assignees, skills, and parent links.

## When to Load This Skill

Load this skill when the user's request matches an SDLC pattern:
- "Research X, then implement Y, then review Z"
- "Design and build a REST API"
- "Build a CLI tool with tests and code review"
- "Analyze, refactor, and verify the codebase"
- Any request involving 3+ SDLC phases (research/design/implement/test/review/deploy/verify)

**Do NOT load** for single-phase work ("fix this bug", "answer this question").

## Prerequisites

Before using this skill, ensure:
1. `kanban-orchestrator` skill is loaded (provides the base decomposition playbook)
2. Available profiles are known (run `hermes profile list` if not cached)
3. Skills are synced to all profiles (run `python3 /opt/data/projects/kanban-auto-routing/sync-profile-skills.py` if unsure)

## Phase Mapping

| SDLC Phase | Kanban Title Prefix | Assignee | Skill | Workspace |
|---|---|---|---|---|
| Research/Analysis | `research:` | worker | spike | worktree (shared) |
| Design/Architecture | `design:` | worker | spike | worktree (shared) |
| Implementation | `implement:` | worker | test-driven-development | worktree (shared) |
| Testing | `test:` | worker | test-driven-development | worktree (shared) |
| Code Review | `review:` | reviewer | multi-model-code-review | worktree (shared) |
| Deployment | `deploy:` | worker | (none) | worktree (shared) |
| Verification | `verify:` | reviewer | (none) | worktree (shared) |

## Decomposition Steps

### Step 1: Identify the SDLC Phases

Parse the user's request to identify which phases are needed:
- **Minimum viable chain:** research → implement → review (3 tasks)
- **Extended chain:** research → design → implement → test → review → deploy → verify (7 tasks)
- **Custom:** only the phases the user explicitly mentioned

### Step 2: Ensure Git Repo + Project Exist

If the target directory doesn't have a git repo, initialize one:

```bash
cd /opt/data/projects/<project-name>
git init && git add -A && git commit -m "initial state before SDLC chain"
```

Create a Hermes project if one doesn't exist:

```bash
hermes project create "<Project Name>" /opt/data/projects/<project-name> \
    --primary /opt/data/projects/<project-name> \
    --board kanban --use
```

If a project already exists, just `hermes project use <slug>`.

### Step 3: Create Task Chain with Shared Worktree

All tasks in the chain share the same git worktree branch. This ensures:
- Each stage operates on the same files
- The reviewer can see the full diff
- Git history provides an audit trail
- Multiple SDLC chains can run in parallel without conflicts

**Branch naming:** `wt/sdlc-<chain-name>` (e.g., `wt/sdlc-fastapi-tasks`)

```python
import subprocess, json

HERMES = "/opt/hermes/bin/hermes"
PROJECT_DIR = "/opt/data/projects/<project-name>"
BRANCH = "wt/sdlc-<chain-name>"
PROJECT_SLUG = "<project-slug>"

def create_task(title, assignee, body, skill=None, parent=None):
    cmd = [HERMES, "kanban", "create", title,
           "--assignee", assignee,
           "--workspace", f"worktree:{PROJECT_DIR}",
           "--branch", BRANCH,
           "--project", PROJECT_SLUG,
           "--json"]
    if skill:
        cmd.extend(["--skill", skill])
    if parent:
        cmd.extend(["--parent", parent])
    cmd.extend(["--body", body])
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    idx = output.find("{")
    if idx >= 0:
        data = json.loads(output[idx:])
        return data.get("id")
    print(f"ERROR creating task: {output}")
    return None

# T1: Research
t1 = create_task(
    "research: <topic>",
    "worker",
    "Research <topic>. Deliverable: Write RESEARCH.md to <project_dir>/ with findings, recommendations, and verdict.",
    skill="spike"
)

# T2: Implement (depends on T1)
t2 = create_task(
    "implement: <feature>",
    "worker",
    "Implement <feature> based on RESEARCH.md. Use TDD. Write tests first. Use uv for packages. Run tests with python3 -m unittest. Write CHANGES.md.",
    skill="test-driven-development",
    parent=t1
)

# T3: Review (depends on T2)
t3 = create_task(
    "review: code quality of <feature>",
    "reviewer",
    "Review the implementation at <project_dir>/. Check: code quality, error handling, test coverage, API design, security, documentation. Write REVIEW.md with APPROVED or CHANGES REQUESTED.",
    skill="multi-model-code-review",
    parent=t2
)
```

**Critical:** Capture every task ID from the `--json` response before creating the next task. You need these IDs for `--parent` links.

### Step 4: Report Task Graph to User

After creating all tasks, report the chain:

```
📋 SDLC Chain Created: <chain-name>

  T1: research: <topic>           → worker   (spike)  [ready]
    ↓
  T2: implement: <feature>         → worker   (TDD)   [todo, waits for T1]
    ↓
  T3: review: <feature>            → reviewer         [todo, waits for T2]

  📁 Worktree: /opt/data/kanban/worktrees/wt/sdlc-<chain-name>
  🌿 Branch: wt/sdlc-<chain-name>
  
  Dashboard monitoring: cron job will post status updates to this thread every 2 min.
```

### Step 5: Set Up Monitoring

Create or refresh the dashboard cron job to monitor this chain:

```bash
# Dashboard cron (every 2 min, delta-aware, posts Block Kit to Slack thread)
hermes cron create --name "sdlc-dashboard-<chain-name>" \
  --schedule "every 2m" --no-agent \
  --script "kanban-dashboard.py" \
  --deliver local
```

Also start the real-time watcher as a background process:

```python
# Start watcher in background
subprocess.Popen(["python3", "/opt/data/projects/kanban-auto-routing/kanban-watcher.py"])
```

### Step 6: Handle Completion

When all tasks are done:
1. Post a completion summary to the user
2. Suggest merging the worktree branch to main:
   ```bash
   cd /opt/data/projects/<project-name>
   git merge wt/sdlc-<chain-name>
   ```
3. Archive the completed Kanban tasks (optional)
4. Stop the dashboard cron job and watcher process

When the reviewer requests changes:
1. The review task stays `blocked` with a comment containing the feedback
2. Create a fix task as an **independent ready task** (NO parent link to the blocked review task):
   ```bash
   hermes kanban create "fix: address review feedback" \
     --assignee worker \
     --workspace worktree:<project_dir> \
     --branch wt/sdlc-<chain-name> \
     --project <slug> \
     --skill test-driven-development
   ```
3. After the fix task completes, unblock the original review task for re-review:
   ```bash
   hermes kanban unblock <review_task_id>
   ```
5. The reviewer task re-runs automatically (or create a new review task if preferred)

> **Important:** Do NOT create a fix task with `parent=<blocked-review-task-id>`. A blocked parent never reaches `done`, so the fix task stays in `todo` forever. The dependency engine only promotes children when every parent is `done`. Create the fix task as an independent `ready` task, then unblock the review task for re-review.

## Worktree Lifecycle

```
T1 dispatched → git worktree add <worktree_path> -b wt/sdlc-<chain>
T1 completes → worktree persists (T2 will reuse)
T2 dispatched → reuses same worktree (same branch, same files)
T2 completes → worktree persists (T3 will reuse)
T3 dispatched → reviewer works in worktree, can git diff, git log
T3 completes → chain done → suggest merge to main
```

**Important:** All tasks in the chain MUST use the same `--branch` and `--workspace worktree:<path>`. The worktree is created on first dispatch and reused by subsequent tasks.

## Delegation Transparency

When you create an SDLC chain, you are acting on a delegation from the user. The user should have full visibility:

1. **Report immediately** — task graph, worktree path, branch name, monitoring setup
2. **Notify on transitions** — watcher posts within 15s of any status change
3. **Thread-scoped** — all notifications post to the same Slack thread
4. **Interpretable replies** — if the user replies in the thread, interpret it as a directive about the active chain:
   - "use SQLite not Postgres" → add comment to active task
   - "stop" → block the active task
   - "also do X" → create a follow-up task
   - "resume" → unblock the task
5. **Final summary** — when chain completes, report deliverables and suggest merge

## Council-Reviewed Adoption Plan (2026-06-27)

A 3/3 advisors panel (DeepSeek, Kimi, GLM) reviewed the hybrid SDLC adoption plan
comparing our current setup against the `hermes-sdlc-loop.html` guide. Full
results in `advisors` skill reference: `real-run-sdlc-hybrid-plan-2026-06-27.md`.

**Priority order (advisors consensus):**
1. Crash recovery + circuit breaker (3 failures, 5-min cooldown, failure-type classification)
2. Metadata handoff + `review-required:` convention (both files + JSON, atomic writes)
3. `skills.external_dirs` + 4 custom phase skills (native sync, keep rsync as daily check for 1 sprint)
4. `qa-dev` profile (local `qwen3.6:27b` primary, `glm-5.2:cloud` fallback)
5. Orchestrator isolation (no-write policy via prompt, not toolset restriction)

**Key decisions:**
- QA model: local first, cloud fallback (high confidence)
- Metadata + files: use both, files are source of truth (high confidence)
- Orchestrator: do NOT restrict to `[kanban]` only — needs read access for planning (high confidence)
- Circuit breaker: 3 failures for local models, 2 for cloud (high confidence)
- `external_dirs`: adopt as primary, keep rsync as daily backup during burn-in (medium confidence)

- **E2E test suite design: progressive complexity** — when validating the SDLC orchestrator, design E2E tests with increasing difficulty to exercise different code paths: (1) simple single-file project (calculator with separate operations module + imports), (2) class-based project with edge cases (stack with push/pop/peek, empty stack errors), (3) project designed to trigger the debug loop (binary search with intentionally missing module file), (4) project designed to trigger stagnation (complex multi-file with tight iteration budget). This progression validates: basic flow, class-based code generation, debug cascade, and stagnation detection — all in one suite. Each test should have a PROJECT.md with acceptance criteria, a max_iterations budget, and a wall_clock_budget. Run sequentially (not parallel) to avoid model API rate limits. See `references/v6-e2e-suite-4-tests-2026-06-28.md` and `references/v6-e2e-round2-2026-06-28.md` for the 7-test suite that validated the v6 state machine (81 total tests passing across both rounds).

## References

- `references/sdlc-orchestrator-child-process-model.md` — **Child process model (2026-06-29):** Complete architecture of how the v6 iterative state machine spawns and manages child processes via `dispatch_single()`. Covers: the one-primitive dispatch model, state-machine-to-child mapping (which states spawn children vs run scripts), concrete IMPLEMENT example with full parameter trace, what children can/cannot do, orchestrator-as-proxy pattern, complete state transition flow diagram, data flow table (orchestrator↔child↔disk), debug cascade special case, and 6 key design properties (synchronous blocking, fresh sessions, worktree isolation, orchestrator-owned termination, no child-to-child communication, script-only states). Produced from a detailed architecture walkthrough.
- `references/sdlc-control-channel-file-lifecycle.md` — **Control channel file lifecycle design (2026-06-28):** Complete phase-by-phase specification for migrating SDLC dispatch prompts from embedded content to file references. Covers all 6 phases (PLAN, IMPLEMENT, VERIFYING, DEBUG, IMPASSE) with read/write matrices, missing-file handling, stale-file handling, update strategies, and code-level changes in `sdlc_state.py`. Includes `read_learnings_formatted()` solution for the LEARNINGS.jsonl blocker, GAPS.md lifecycle design, resume consistency rules, and fallback heuristic. Produced by DeepSeek V4 Pro after a 3-seat advisor panel (DeepSeek + Kimi + Qwen, GLM synthesis) unanimously recommended DEFER. ~60 lines of new code, 8 lines of modifications. Backward-compatible.
- `references/output-improvement-plan-2026-06-28.md` — **10-point output improvement plan (2026-06-28):** Structured plan for improving orchestrator progress reporting and final summary quality. Covers per-iteration summaries, model output previews, learning field fallback, state history in final summary, file listings, git commit info, GAPS content display, plan visibility, wall-clock progress, and garbage filtering in LEARNINGS. ~75 lines of changes in `sdlc_state.py`. Prioritized P0/P1/P2.
- `references/o1-o10-implementation-2026-06-28.md` — **O1-O10 implementation results (2026-06-28):** All 10 output improvements applied and validated. 5 new helper functions (`_emit_iteration_summary`, `_emit_preview`, `_emit_plan_preview`, `_remaining_time`, `iteration_states` tracking). Live E2E validated with binary search test (11 tests, 135s). 31/31 ad-hoc verification checks passed. Commit `18e3ba0`.
- `references/improvement-plan-2026-06-28.md` — **Structured improvement plan from v6 design session (2026-06-28):** 9 remaining code concerns (A1-A9), 8 process learnings (P1-P8), 6 design gaps (D1-D6). Prioritized into immediate/near-term/medium-term. Key unfixed items: `\bGAPS\b` word-boundary (A1), save_state before FAILED breaks (A2), live E2E test (D3), CLI entry point (D5), parallel dispatch design (D1).
- `references/v6-iterative-state-machine.md` — **v6 iterative state machine architecture (2026-06-28):** 45-iteration scaling, three independent stagnation counters, LEARNINGS.jsonl learning journal, checkpoint/resume via ITERATION_STATE.json, LINT_FIX as script-only state, tight/wide loop routing, impasse diagnosis with DeepSeek, HUMAN_REVIEW state. 4 new states (LINT_FIX, VERIFYING, FAILED, HUMAN_REVIEW) + 14 new helper functions integrated into `sdlc_state.py`. v5 backward compatible.
- `references/v6-quality-review-findings-2026-06-28.md` — **Advisor quality review of v6 implementation (2026-06-28):** 2-seat panel (DeepSeek + Kimi) independently found 5 HIGH and 6 MEDIUM issues with strong consensus. Includes 8-fix plan with before/after code snippets. Key insight: at 45 iterations, stagnation detection is the primary terminator — checkpoint/resume must actually work, gap_stagnation needs normalized comparison, and debug cascade failure needs its own stagnation signal.
- `references/v3.1-concurrent-dispatch-design.md` — **v3.1 concurrent dispatch design (2026-06-29):** Full design for parallel dispatch with per-child git worktree isolation. Covers: dispatch_parallel() and dispatch_parallel_isolated() functions, state machine integration, constraints, Phase 1/2/3 roadmap, and 7 open questions. Reviewed by 3-seat advisor panel (DeepSeek + Kimi + Qwen, GLM synthesis) — APPROVE WITH CHANGES. All P0/P1 fixes applied and committed. See Section 7 for the full advisor review summary.
- `references/worktree-uncommitted-state-workflow.md` — **Worktree uncommitted-state workflow (2026-06-29):** Complete design for capturing and applying orchestrator uncommitted state to child worktrees via `git diff HEAD --binary` patch files + selective untracked file copy. Replaces the blunt `git add -A && git commit` approach. Covers: 5-phase workflow (capture→apply→work→merge→cleanup), 37 corner cases across 6 categories, conflict resolution strategy (rebase + merge), merge-test gate, what to copy vs exclude, and risk mitigations. Produced by DeepSeek V4 Pro (201.3s, 28,923 chars) after user corrected that worktrees stay nested inside the parent project directory.
- `references/kimi-git-review-v3.1-2026-06-29.md` — **Kimi structured git/code audit of v3.1 design (2026-06-29):** Comprehensive code-level review of `dispatch_parallel_isolated()` git operations, corner conditions, and Python code quality. 14 issues found (2 HIGH, 8 MEDIUM, 4 LOW), 14 items verified correct. Used a structured 5-category audit checklist (30+ specific questions) rather than open-ended review — this produced a more thorough result than the earlier 3-seat advisor panel. Key findings: worktree leak on early exception (H2), missing imports (H1), mid-rebase detection broken in linked worktrees (M1), file handle leak (M2), silent git failures (M5). 395.5s, 14,584 chars.
- `references/v3.1-next-round-improvement-plan.md` — **GLM-5.2 improvement plan for v3.1 (2026-06-29):** Comprehensive 128-line plan covering 14 improvement items across P0/P1/P2 priorities. GLM caught critical bugs the controller missed: 5/7 tests were ERROR-ing (not passing) due to a create_worktree signature mismatch, and text=True + input=bytes mismatch. Includes recommended implementation order, minimum viable set for production (~1.5 days), and per-item effort estimates. DeepSeek V4 Pro was attempted twice but dropped mid-stream both times — GLM-5.2 was the reliable fallback for long structured output.
- `references/v3.1-implementation-bugs-2026-06-29.md` — **8 implementation bugs found during v3.1 integration (2026-06-29):** All bugs discovered and fixed in a single session after Kimi's initial implementation compiled but 7/7 integration tests failed. Covers: `_git_or_raise` double-prefix, shallow copy not stored back into list, branch deletion order (worktree before branch), merge conflict test needs pre-existing file, module-level constant frozen at import, subagent reformats unrelated files, stray test artifacts in git index, `git rm --cached` not persistent. Final result: 17/17 tests passing. Each bug includes symptom, root cause, fix, and lesson.
- `references/ollama-concurrency-benchmark-2026-06-29.md` — **Ollama concurrency benchmark (2026-06-29):** 3.25x speedup confirmed — Ollama handles concurrent requests to the same model without serializing. 3 sequential tasks = 42s, 3 parallel = 12.9s. Resolves the #1 gate for v3.1 Phase 1 speedup.
- `references/v6-14-fixes-applied-2026-06-28.md` — **All 14 advisor fixes applied and verified (2026-06-28):** 3-seat panel (DeepSeek + Kimi + GLM) found 14 issues total. GLM caught 6 issues the other two missed — validates 3-seat panels. All fixes applied to `sdlc_state.py` (13) and `sdlc_worktree.py` (1). 26-check ad-hoc verification, all pass. Key lessons: 3-seat > 2-seat, ad-hoc verification sufficient for targeted fixes, verification system's "unverified" flag is mechanical.
- `references/live-e2e-validation-2026-06-28.md` — Live E2E test results validating the `toolsets=''` + `max_turns=1` fix for output-only dispatch phases, debug cascade behavior, and multi-suite test parsing.
- `references/p12-live-e2e-findings-2026-06-28.md` — **Comprehensive P12 findings (2026-06-28):** 5 live E2E tests, 7 findings (4 fixed, 3 open), 8 advisor recommendations (DeepSeek + Kimi). Covers council quorum model, AI-generated test quality problem, model non-determinism in enhancement phases, and the `ast.parse()` extraction verification pattern.
- `references/v6-improvement-plan-v2-2026-06-28.md` — **Structured improvement plan v2 (2026-06-28):** Synthesized from all session learnings (17 reference docs, current code). 18 improvement items across 5 categories (CORRECTNESS, PERFORMANCE, ROBUSTNESS, OBSERVABILITY, ARCHITECTURE). 10 S-effort, 5 M-effort, 3 L-effort. Recommended next sprint: P1 (negated GAPS regex, P0) → P2 (repeated_root_cause double-counting, P1) → P3 (cascade/test_stagnation conflation, P1) → P5 (skip PLAN iter 1 + fast-verify, P1) → P7 (file_paths via git diff, P2). All S-effort, all independent, all low-risk. Also covers: DiminishingReturnsTracker AttributeError, CLI entry point, read_learnings O(n) growth, run_ruff filtering, per-task timeout, patch-based isolation, structured PLANNING output, import-graph analysis, events.jsonl logging, STATUS.json endpoint, model/provider env vars, LINT_FIX→HUMAN_REVIEW fallback, enhanced debug cascade context.
- `references/e2e-test-validation-2026-06-28.md` — **E2E test validation of v6 state machine (2026-06-28):** Dry-run + real-dispatch E2E tests after A1/A2 fixes. Dry run validates state machine wiring (6 states, <1s). Real dispatch validates model integration (PLAN→IMPLEMENT→LINT_FIX→DEBUG loop, stagnation detection at 3/3). 4 findings: git init needed in worktree, coder model returns text not files, stagnation detection works, field name mismatch in test script.
- `references/sdlc-inline-status-plan.md` — **Comprehensive SDLC orchestrator redesign plan (v5 final, 2266 lines, 111KB).** Covers 3 layers of inline status emission (progress_callback chain), intelligent orchestrator extension (session continuity, evaluation loop, per-phase quality gates, ContextState lifecycle), and 6 architectural concepts: (1) logical control channel with file-reference protocol, (2) context lifecycle management, (3) iterative state machine with diminishing-returns detection, (4) required final SUMMARY.md + teaching deliverable, (5) git worktree isolation per pipeline run with merge-back, (6) git-commit-per-iteration learning journal with git-history review during planning. Reviewed 5× across 3 reviewers: Kimi v3 (code-level: thread lock, dispatch_comparison, test mocks, early-return, --quiet, callback safety), DeepSeek v3 (architectural: double-emission bug, import threading, dispatch handlers, early-return inventory), Kimi v4 (orchestrator: PHASE_ALIASES, dispatch_with_evaluation, MAX_PHASE_ROUNDS, evaluators, ContextState, session save bugfix), DeepSeek v4 (orchestrator: evaluator crash, max_rounds=1, signature fix, evaluate_council, context math), Kimi v5 (state machine + worktrees + git learning: control channel, context lifecycle, SDLCState, DiminishingReturnsTracker, SUMMARY.md, worktrees, file-reference, learning_commit, structured commit messages, HISTORY.md), DeepSeek v5 (git learning: triple-quote injection bug, null byte stripping, merge conflict handling, first-run empty history, commit-after-transition). All 48 verification checks passed. Implementation started (3 new modules written: sdlc_worktree.py, sdlc_control.py, sdlc_state.py) but model_utils.py + sdlc.py updates + test suite run incomplete.

## Pitfalls

- **Wrong SOUL.md** — always verify `echo $HERMES_HOME` first. Active file is `$HERMES_HOME/SOUL.md`.
- **Missing skills in profiles** — run `python3 /opt/data/projects/kanban-auto-routing/sync-profile-skills.py` before creating tasks that pin skills.
- **No git repo** — worktree workspace requires a git repo. Initialize one first.
- **Branch conflicts** — use unique branch names per chain: `wt/sdlc-<name>-<timestamp>`.
- **Task ID not captured** — always capture ID from `--json` response before creating the next task. Never guess IDs.
- **Bitwarden warning prefix** — strips non-JSON output from `hermes kanban` commands. Use `find("{")` to locate JSON start.
- **One-shot sessions can't decompose** — `hermes chat -q` ends after one response. Full decomposition requires a gateway session (Slack/Telegram/etc.).
- **All child processes get all tools — `toolsets='file,terminal,web'` everywhere** — per user policy (2026-06-29), every dispatched child process in the SDLC pipeline gets full tool access. This reverses the earlier `toolsets=''` policy for output-only phases. The rationale: models should have the tools they need to do their job, and restricting tools caused more problems (empty output, inability to read files for context) than it solved. All v5 and v6 dispatch sites now use `toolsets='file,terminal,web'`: `implement`, `tech_docs`, `simplify_code`, `council_review`, `debug_cascade`, `plan`, `design_test_suites`, and all v6 state machine phases. The `max_turns` parameter still defers to Hermes config (`max_turns=None`).
- **Dual-review cross-validation for SDLC code quality (2026-06-29)** — when reviewing the SDLC orchestrator code itself (or any mission-critical codebase), use the parallel dual-review + cross-validation pattern from `multi-model-code-review` skill. Dispatch two reviewers independently, then have Reviewer B validate/challenge Reviewer A's findings. Implement only bugs both reviewers agree on. Proven on 7 SDLC files (6,944 lines): Qwen found 7 HIGH + 14 MEDIUM, Kimi cross-validated (5/7 HIGH valid, 2 false positives) and found 10 new issues. 8 confirmed bugs implemented and verified (14/14 ad-hoc checks pass). See `references/dual-review-8-bug-fixes-2026-06-29.md` for the full session trace.\n- **Kimi full-codebase review pattern: 6 files, 11 issues, one agent call** — when you need a comprehensive code review across multiple files, dispatch Kimi (kimi-k2.7-code:cloud) with `--thinking high` + `file,terminal` toolsets and a prompt that lists every file to review. Kimi will read all files, trace the full orchestration/dispatch/state flow, and produce a structured findings report. This is more efficient than dispatching separate reviewers per file. Real example (2026-06-29): Kimi reviewed 6 SDLC files (~5,400 lines total), found 11 issues across 3 files, and produced a 24K-char report in 62.5s. All 11 fixes were applied and verified (387 tests, 0 failures). The key to success: give Kimi the full file list and ask it to trace end-to-end flows, not just read individual files.
- **Verification discipline: verify → commit → re-verify** — after making changes and verifying them, the system may flag files as "unverified" after a commit even when verification was done pre-commit. This is a mechanical re-check, not a new verification. Pattern: (1) make changes + run tests + verify, (2) commit, (3) system flags changed paths as "unverified", (4) run quick re-verify (compile + targeted tests), (5) clean up `/tmp/hermes-verify-<phase>.py` scripts. The actual verification happened pre-commit; the re-verify is fast and mechanical.
- **Ad-hoc verification script gotchas** — when writing `/tmp/hermes-verify-*.py` scripts, these patterns cause false failures: (1) `grep -n` line-number prefix (`1255:`) breaks `stripped.startswith("#")` — strip with `re.sub(r'^\d+:\s*', '', line)` first; (2) `grep -c` with multiple files returns per-file counts like `file1.py:3\nfile2.py:0`, not a single integer — grep each file separately; (3) indented comments (`        # comment`) aren't detected by `line.strip().startswith("#")` when the grep output includes the line-number prefix; (4) passthrough kwargs (`thinking=thinking`, `max_turns=max_turns`) look like hardcoded values to naive regex — exclude them explicitly; (5) expect 3-5 iterations to get the regex right. Clean up `/tmp/hermes-verify-*.py` after the final pass. Discovered Jun 2026 during the hardcoded-values audit (5 iterations: v1 multi-file bug, v2 passthrough false positive, v3 indented-comment false positive, v4 line-number prefix bug, v5 16/16 passed).
- **`os.rmdir` fails on non-empty dirs** — use `shutil.rmtree` instead when cleaning up workdirs that may contain files.
- **AI-generated test suites can have incorrect assertions** — the pipeline only checks whether tests pass, not whether assertions are correct. A generated test that asserts `is_palindrome("Was it a car or a cat I saw")` is False will pass (the assertion is wrong, not the code), and the pipeline reports success. Mitigation: add a test oracle or validation phase that runs the generated tests against known-correct inputs. Until then, always manually spot-check generated test assertions.
- **Enhancement phases are non-deterministic** — `tech_docs()`, `simplify_code()`, and other enhancement phases can return None content due to model non-determinism. The pipeline should treat enhancement phases as optional: log warnings, don't crash. Tests should handle None gracefully (e.g., `assert result is not None or "tech_docs returned None (model non-determinism)"`).
- **Council quorum model** — instead of binary pass/fail, use a 3-status model: `success` (all seats responded), `partial` (some seats responded), `failed` (no seats or all API errors). Filter seats with `is_api_error()` before counting. Return `status` and `total_seats` in the result dict. This prevents a single API error from collapsing the entire council.
- **`extract_python_code()` lenient fallback is dangerous** — when the strict extraction (triple-backtick blocks) fails, a lenient fallback that matches `return`/`if __` keywords can return prose or error text as "code." Always verify extracted code with `ast.parse()` before returning it. If `ast.parse()` fails, the extraction is invalid — return None and set `pipeline_status='implement_failed'`.
- **Substring negation matching causes false positives — use word-boundary regex** — when checking verdict text for negation (e.g., "NOT" near "SATISFIED", "GAPS" in a negative sentence), plain substring matching (`"NOT" in text`, `"GAPS" in text`) matches inside words like "noting", "notification", "notebook", or in negated phrases like "No GAPS found, all SATISFIED". A benign verdict like "SATISFIED, noting no issues" would be misclassified as GAPS because "NOT" appears inside "noting". Similarly, "No GAPS found, all SATISFIED" would be misclassified as GAPS because "GAPS" appears in a negated sentence. Always use word-boundary regex: `re.search(r'\bNOT\b', text)` and `re.search(r'\bGAPS\b', text)`. This was caught by a 3-seat advisor panel reviewing 14 bug fixes — Kimi flagged the NOT case as a REGRESSION, DeepSeek as a CONCERN. The fix (v2) replaced `"NOT" in upper` with `re.search(r'\bNOT\b', upper)` and added a test case for "SATISFIED, noting no issues" → SATISFIED. The GAPS case (same class of bug) was identified in the improvement plan (A1) but not yet fixed — apply the same `\bGAPS\b` treatment. See `references/v6-14-fixes-applied-2026-06-28.md` §Fix 11 v2 and `references/improvement-plan-2026-06-28.md` §A1.
- **Advisor review pattern for plan validation** — when a plan needs review, dispatch DeepSeek + Kimi in parallel as individual `delegate_task` calls (not batch). DeepSeek catches architectural/design issues; Kimi catches code-level issues and can auto-implement fixes. Both return independently — results stream in as each finishes. Use the `advisors` skill for true model diversity (per-subagent model overrides on `delegate_task` don't work).
- **Plan review workflow: Kimi first, then DeepSeek** — for SDLC plan reviews, run Kimi (kimi-k2.7-code:cloud) FIRST for code-level review (test mocks, line numbers, missing imports, dispatch_comparison plumbing, early-return coverage), then DeepSeek (deepseek-v4-pro:cloud) SECOND for architectural review (double-emission bugs, design flaws, early-return correctness). Sequential, not parallel — DeepSeek reviews the Kimi-updated plan, catching issues Kimi missed. Both must approve before implementation. Plans live in `sdlc-pipeline/references/`. Use `prompt_model.py` with `-t file,terminal` for DeepSeek (needs to read source files + write updated plan).
- **Multi-file implementation: cloud models for full runs, local for single files** — when implementing a plan that touches 5+ files, prefer cloud models (GLM, DeepSeek, Kimi) for the full implementation. Local models (qwen3-coder-next:q4_K_M) with `--max-turns 25` may complete 3/5 files and time out, leaving partially-edited files with broken imports. Recovery: (1) verify each modified file compiles with `python3 -c "import module"`, (2) fix any broken imports (usually a one-line patch), (3) re-dispatch only the remaining steps with a cloud model. Reserve local models for single-file edits or quick reviews where partial completion is acceptable.
- **delegate_task subagents are unreliable for multi-file implementation** — a delegate_task subagent dispatched for implementation work may complete 47+ API calls over 15 minutes but make zero changes to target files. The subagent's self-reported summary may claim success while no files were actually modified. For implementation work, prefer `prompt_model.py` with cloud models (which writes output to a verifiable file) or implement directly in the controller. delegate_task is better suited for reasoning-heavy tasks (code review, research synthesis) where the output is analysis, not file edits. Always verify file modification timestamps after a delegate_task implementation subagent completes — do not trust the self-reported summary alone.
- **Multi-linter gate (ruff → pyflakes → mypy) in both v5 and v6** — the SDLC lint phase runs three linters in sequence after each IMPLEMENT, before tests. ruff auto-fixes first (format, check --fix --unsafe-fixes), then pyflakes diagnoses undefined names/unused vars, then mypy catches type errors. ruff handles what it can auto-fix, so pyflakes/mypy only see post-fix code — their reports are clean of fixable issues and only surface real problems. All unfixable issues are merged and fed back to the coder on retry. Both v5 `lint_code()` (in `sdlc.py`) and v6 `run_all_linters()` (in `sdlc_state.py`) use this pattern. All linter binaries use the venv path (`/opt/data/.venv/bin/ruff`, `/opt/data/.venv/bin/python3 -m pyflakes`, `/opt/data/.venv/bin/mypy`) — no `uv run` indirection. Added Jun 2026 (v6: commit `83718e7`, v5: commit `82f841d`).
- **Integrate into existing skill modules, don't build standalone scripts** — when extending the SDLC pipeline with new state machine logic, extend the existing `sdlc_state.py` module rather than creating a standalone `orchestrator.py`. The user corrected this explicitly (2026-06-28): the v6 iterative state machine belongs in the SDLC skill's codebase, not as a separate script. Standalone scripts create fragmentation and duplicate imports. Always ask: "does this extend an existing module, or is it genuinely new functionality?" If it extends, patch the existing module.
- **`dispatch_single` needs `cwd` parameter for worktree isolation** — when dispatching `hermes chat -q` subprocesses for SDLC phases (planner, coder, verifier), the subprocess inherits the parent's working directory, not the worktree. The model's terminal tool then creates files in the wrong directory. Fix: add `cwd: Optional[str] = None` to `dispatch_single()` signature and pass `cwd=cwd` to both `subprocess.run()` calls (initial + retry). Then pass `cwd=worktree` from all v6 dispatch sites. This complements the prompt-level "cd {worktree} &&" enforcement — belt (cwd) + suspenders (prompt). See `model_utils.py` `dispatch_single()` for the implementation.
- **Negated GAPS detection — "No GAPS found" is SATISFIED, not GAPS** — the `\bGAPS\b` word-boundary fix (A1) prevents matching "GAPS" inside words, but doesn't handle negated GAPS phrases like "No GAPS found, all SATISFIED." The regex `\bGAPS\b` matches "GAPS" in "No GAPS found" and returns GAPS verdict — a false positive. Fix: add a pre-check for negation words before the GAPS check: `gaps_negated = bool(re.search(r'\b(?:NO|NONE|WITHOUT|ZERO)\s+GAPS\b', upper))`. If negated, skip the GAPS check and fall through to SATISFIED detection. This is fix A1b, building on the A1 word-boundary fix. See `extract_verdict()` in `sdlc_state.py`.
- **Pytest/ruff venv path resolution** — `run_tests_in_worktree()` and `run_ruff()` call `python3 -m pytest` and `ruff` directly, but these may not be installed in the system Python. Fix: resolve venv paths at module load time (`_VENV_PYTHON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.venv', 'bin', 'python3')`), check if they exist, and use them when available. Fall back to system `sys.executable` / `ruff` if the venv isn't present. This makes the orchestrator work in environments where dev tools are only in a venv.
- **E402 lint blocks pipeline on test files** — `ruff check` flags `E402` (module-level import not at top of file) when test files have section comments followed by imports. This is common in AI-generated test files where the coder places integration-test imports after unit-test functions. `ruff --fix` cannot auto-fix E402 (requires code reorganization), so the LINT_FIX phase correctly identifies it as unfixable and retries — but the coder model can't fix it either, leading to MAX_LINT_RETRIES exit even though all tests pass. Fix: add `--ignore E402` to `run_ruff()` in `sdlc_state.py`. E402 is cosmetic in test files and should not block the pipeline. Also filter "Found N errors" summary lines from the unfixable list to avoid counting them as individual issues. See `references/v6-e2e-suite-4-tests-2026-06-28.md` for the full 4-test E2E suite that surfaced this.
- **LINT_FIX max retries with unfixable lint** — when lint issues are unfixable but all tests pass, the pipeline should not exit with LINT_FIX. Consider adding a HUMAN_REVIEW fallback or a "lint warning, not error" classification for unfixable-but-cosmetic issues. Currently MAX_LINT_RETRIES=3 is hardcoded.
- **LINT_FIX → HUMAN_REVIEW fallback must check test files exist first (2026-06-29)** — when LINT_FIX exhausts retries, the fallback to HUMAN_REVIEW assumes the coder created test files. If the coder didn't create any test files (0 tests found), HUMAN_REVIEW is wrong — the pipeline should FAILED instead. Fix: before the HUMAN_REVIEW fallback, check `any(f.startswith('test_') and f.endswith('.py') for f in os.listdir(worktree))`. If no test files exist, emit "coder didn't create tests" and break to FAILED. This was discovered in E2E Round 3 where the JSON Parser test hit HUMAN_REVIEW with 0 test files. See `references/e2e-round3-results-2026-06-29.md`.
- **HUMAN_REVIEW summary must show total test count, not just pass count (2026-06-29)** — the HUMAN_REVIEW summary line showed `Tests: {run.prev_pass_count}` without the total, making it impossible to distinguish "10/10 tests pass" from "0/0 tests pass" (vacuously true). Fix: read `run.last_test_result.get("total", "?")` and emit `Tests: {run.prev_pass_count} passed (total: {_total})`. This was the 10th of DeepSeek's 11 proposed fixes from the E2E Round 3 diagnosis. Applied in commit `6233e05`. See `references/e2e-round3-results-2026-06-29.md`.
- **`run_tests_in_worktree` must handle missing pytest gracefully (2026-06-29)** — the function calls `subprocess.run([python, "-m", "pytest", ...])` without try/except. If pytest isn't installed or the subprocess times out, the orchestrator crashes. Fix: wrap in `try/except (subprocess.TimeoutExpired, FileNotFoundError, OSError)` and return a clean error dict. This was discovered in E2E Round 3 where the Stack test's worktree had no pytest.
- **Per-dispatch timeouts are the wrong layer — let the orchestrator handle timing (2026-06-29)** — the user explicitly directed: "the orchestrator is the only one who interacts with the user. Child processes ask the orchestrator to proxy." Per-dispatch timeouts (300s, 120s) kill child processes before the wall-clock budget is exhausted, causing false VERIFYING timeouts. Fix: make per-dispatch timeouts excessively large (3600s = 1 hour) so they're effectively unlimited. The top-level `wall_clock_budget` is the only real timeout. Child processes run to completion; the orchestrator decides when to stop. Also add a 25% remaining wall-clock warning at the loop top so the orchestrator can make informed decisions. See `references/e2e-round3-results-2026-06-29.md`.
- **Background E2E suites need active monitoring, not fire-and-forget (2026-06-29)** — when running a 21-minute E2E suite via `terminal(background=true, notify_on_complete=true)`, the controller went silent for the entire duration. The user had to ask "Status?" at 21 minutes. The `notify_on_complete` pattern works (notification fires on exit) but provides zero intermediate progress. For long-running suites (>3 min), use `watch_patterns` to get phase-level progress, or run the suite in the foreground with a generous timeout and report results inline. The fire-and-forget pattern is only acceptable for <3 minute tasks. See `references/e2e-round3-results-2026-06-29.md`.
- **Terminal state not in state_history — append after loop exits** — the v6 iterative state machine appends states to `run.state_history` at the TOP of each iteration (inside the while loop). When the loop exits (via `break` or because `state` is in the terminal set), the terminal state (COMPLETE/FAILED/HUMAN_REVIEW) is never appended. This means `run.state_history[-1]` returns the last non-terminal state (e.g., VERIFYING) instead of the actual final state. Fix: after the while loop, append `state.name` if it differs from the last entry: `if not run.state_history or run.state_history[-1] != state.name: run.state_history.append(state.name)`. This was discovered during E2E Round 2 testing (2026-06-28) where all 3 tests showed COMPLETE as the final state after the fix. See `references/v6-e2e-round2-2026-06-28.md`.
- **Orchestrator output must be self-documenting — users shouldn't need to inspect worktree files** — the v6 state machine worked functionally but progress reporting was minimal: state transitions with no context, blank learning fields, no model output previews, no file listings, no wall-clock time remaining. Users monitoring long-running projects had to inspect worktree files to understand what happened. The 10-point output improvement plan (O1-O10) fixes this: per-iteration summaries, model output previews (150 chars), learning field fallback chain, state history path in final summary, file listings, git commit hashes in progress, structured GAPS display, plan preview, and wall-clock remaining time. All implemented in `sdlc_state.py` (~127 lines). See `references/o1-o10-implementation-2026-06-28.md` for the full implementation and live E2E validation. Key pattern: `iteration_states` list reset at PLAN, appended at each state transition, emitted in `_emit_iteration_summary()` after VERIFYING resolves.
- **Subagent implementation work needs post-hoc review — don't trust self-reported "done"** — when a subagent (especially local models like qwen3-coder-next) implements a multi-item plan, it will claim success but leave subtle bugs: functions defined but never called, fields defined but never wired, scope errors (referencing `run` in a function that receives `data`), and incomplete wiring (git diff captured but never passed to append_learning). Pattern: (1) always run `git diff` after subagent implementation completes, (2) verify each new function/field is actually used (grep for call sites), (3) check for scope errors in functions that receive dicts vs objects, (4) run a targeted ad-hoc verification script covering each implemented item. The subagent's self-reported summary is unreliable — verify independently. See `references/p1-p18-implementation-2026-06-28.md` for the full 14-implemented/4-skipped session with post-hoc fixes.

- **"Defined but never called" is the #1 subagent implementation bug** — when a subagent adds a new function (like `_log_event()`) to satisfy a plan item, it often defines the function correctly but never wires it into the call sites. The function compiles, imports, and passes syntax checks — it just never executes. Detection: `grep -c "function_name(" file.py` should show 1+N occurrences (1 definition + N call sites). If it shows exactly 1, the function is defined but never called. Fix: identify every state transition or event that should trigger the function, and add a call at each. For `_log_event()`, this meant 8 call sites: INIT, PLAN, IMPLEMENT, LINT_FIX, RUN_TESTS, DEBUG, VERIFYING, and verdict SATISFIED. This bug class is so common it warrants its own verification check in every post-subagent review. See commit `73f224d` for the fix.

- **Improvement plan generation: use GLM-5.2, not DeepSeek or coder subagents** — when generating a structured improvement plan from accumulated learnings, DeepSeek (deepseek-v4-pro:cloud) tends to output diffs against existing files rather than clean standalone markdown, and its API drops mid-stream for long outputs. Coder subagents (qwen3-coder-next) with `delegate_task` can work but are unreliable for multi-file implementation. GLM-5.2:cloud is the reliable choice: it produces clean markdown, doesn't drop mid-stream, and catches bugs the controller missed. Real example (2026-06-29): GLM produced a comprehensive 128-line plan that caught critical P0 bugs (create_worktree signature mismatch, text=True + input=bytes mismatch) that the controller had reported as "7/7 pass" when 5/7 were actually ERROR-ing. See `references/v3.1-next-round-improvement-plan.md` for the resulting plan.

- **DeepSeek improvement proposal pattern: ask for S-effort, complexity-reducing proposals** — when you ask DeepSeek \"what improvements should we make to this codebase?\", it produces proposals that are consistently S-effort (small, <30 min each) and complexity-reducing (removing code, consolidating, simplifying). This is a reliable review pattern: after a major implementation session, ask DeepSeek to review the current state and propose improvements. It will find dead code, consolidation opportunities, missing reference docs, and test gaps — all small, all low-risk, all independently verifiable. Real example (2026-06-28): after implementing 7 ask-skill improvements, DeepSeek proposed 8 more — all S-effort, all complexity-reducing (consolidate, delete, document, test). All 8 were implemented and verified in one session. Use this pattern as a post-implementation cleanup step.
- **Structured audit checklist beats open-ended review for code quality** — when reviewing a complex function like `dispatch_parallel_isolated()`, a structured 5-category audit checklist with 30+ specific questions (Phase A capture, Phase B apply, Phase D merge, corner conditions, code quality) produces more thorough results than an open-ended "review this code" prompt. Kimi's structured review (2026-06-29) found 14 issues (2 HIGH, 8 MEDIUM, 4 LOW) and verified 14 items correct — more thorough than the earlier 3-seat advisor panel. The checklist forces the reviewer to examine every code path, not just the ones that catch their attention. Use this pattern for any mission-critical code review: write a detailed checklist of specific questions, not a general "review for bugs." See `references/kimi-git-review-v3.1-2026-06-29.md` for the full checklist and results.
- **Worktree cleanup gap: `finally` must sweep `created_worktrees`, not just `results`** — if an exception fires after N worktrees are created but before they're dispatched, the first N-1 worktrees are in `created_worktrees` but never in `results`, so the `finally` block never removes them. Fix: track `removed_worktrees` set and sweep the full `created_worktrees` list in `finally`, skipping already-removed ones. This is Kimi H2 from the v3.1 audit.
- **Linked worktree git state detection: use `git rev-parse --git-path`, not hardcoded `.git/` paths** — in linked git worktrees, `.git` is a file (not a directory), and per-worktree state lives under `.git/worktrees/<name>/`. Hardcoded paths like `.git/rebase-merge` miss in-progress rebases. Fix: `git rev-parse --git-path rebase-merge` returns the correct per-worktree path. This is Kimi M1.
- **File handle leak: `subprocess.run(stdin=open(...))` never closes the file** — `subprocess.run` doesn't close file objects passed via `stdin=`. For per-child loops, this leaks one handle per child. Fix: read the file once into bytes, pass via `input=patch_bytes`. This is Kimi M2.
- **Silent git failures: use `_git_or_raise()` helper, never bare `subprocess.run` for git** — many `subprocess.run` calls in the design doc don't check returncode. If `git commit` fails (missing user.name, gpg sign failure), the function silently continues with a dirty worktree. Fix: wrap all git commands in a helper that checks returncode and raises on failure, with an `ignore_nothing` flag for `git commit` when there's nothing to commit. This is Kimi M5.
- **`_merge_failures` key collision: use namespaced metadata keys** — if a planner emits `task_id="_merge_failures"`, the task result and metadata list collide. Fix: use `__sdlc_merge_failures__` (double-underscore prefix) for all metadata keys. This is Kimi M8.
- **Worktrees stay nested inside parent project directory** — per user directive (2026-06-29), child worktrees live in a `worktrees/` subdirectory of the parent project, NOT in WORKTREE_ROOT or /tmp. Path: `<project>/worktrees/parallel/<task-id>/`. This keeps everything self-contained. Do NOT move worktrees to a separate directory tree.

- **`_git_or_raise` double-prefix: audit all call sites when a helper wraps a command** — when a helper function prepends a command prefix (e.g., `_git_or_raise` prepends `"git"`), every call site must NOT include that prefix in its args. `_git_or_raise(["git", "add", ...])` produces `git git add`. Detection: `grep '_git_or_raise(\["git"' <file>` — any match is a bug. One grep catches every instance. Discovered during v3.1 integration (2026-06-29) — 4 call sites had the double-prefix.

- **Shallow copy in loop: store back into the list** — when you mutate a loop variable that's a copy of a list element (`task = dict(tasks[i])`), you MUST store it back (`tasks[i] = task`). Python's `for` loop rebinds the variable each iteration — mutations to the variable don't affect the list. Discovered during v3.1 integration: `task["cwd"] = wt_path` was set on a local copy but never stored back, causing `cwd=''` in dispatch.

- **Branch deletion order: remove worktree before deleting branch** — `git branch -d` refuses to delete a branch that's checked out in any worktree. Always `remove_worktree(wt_path)` first, then `git branch -d child_branch`. Discovered during v3.1 integration — 2 tests failed until the order was swapped.

- **Merge conflict tests need files in the merge base** — when both children add a NEW file (not in the base commit), git's 3-way merge sees no common ancestor and auto-resolves without conflict. To test merge conflicts, pre-create the file in the base commit so both children MODIFY it. Discovered during v3.1 integration — test_02 passed in isolation but the merge succeeded when it should have conflicted.

- **Module-level constants from env vars are frozen at import** — `WORKTREE_ROOT = os.environ.get(...)` is evaluated once at module import. Tests that change `os.environ` after import don't affect the already-read constant. Either set env vars before import, or use a function that reads the env var lazily at call time. Discovered during v3.1 integration — tests passed in isolation but failed when run together due to stale `WORKTREE_ROOT`.

- **Subagent implementation sessions: always `git diff --stat` before committing** — subagents with file write access will "helpfully" reformat or improve files they read for context, even when not asked. Kimi rewrote 342 lines of `sdlc_worktree.py` docstrings while implementing `sdlc_parallel.py`. After ANY subagent implementation session, run `git diff --stat` and revert files the subagent shouldn't have touched. This is the implementation-specific variant of the general "Subagents can make unsanctioned changes" pitfall.

- **Stray test artifacts: write test mocks to `/tmp/`, not the project directory** — test mocks that write files to the project directory leave artifacts that pollute `git status` and can be accidentally committed. Use `/tmp/` for mock output files. If artifacts are already committed, use `git rm --cached` followed by an immediate commit — `git add -A` will re-stage them if the removal isn't committed first. Discovered during v3.1 integration — 6 stray files (`module_*.py`, `shared.py`) appeared in the git index from test mock output.

- **`git rm --cached` is not persistent until committed** — after `git rm --cached <files>`, any subsequent `git add -A` will re-stage those files if they exist on disk or in a prior commit. Either commit the removal immediately, or use `git reset HEAD -- <files>` and ensure the files are deleted from disk before running `git add -A`. Discovered during v3.1 integration — stray test artifacts kept reappearing in `git diff --cached`.
- **DeepSeek API drops mid-stream for long outputs — use GLM-5.2 as fallback** — when dispatching DeepSeek V4 Pro for long structured outputs (improvement plans, design reviews, synthesis), the API connection can drop mid-stream (exit code 1, partial output). Retry once with a shorter timeout. If it fails again, switch to GLM-5.2:cloud — it's reliable for long structured outputs and consistently delivers complete results. Discovered during v3.1 improvement plan dispatch (2026-06-29): DeepSeek failed twice, GLM succeeded and produced a comprehensive 128-line plan that caught critical bugs (P0-1/P0-2 signature mismatch).
- **Tests can ERROR, not just FAIL — unittest exit code 0 masks ERRORs** — Python's `unittest` returns exit code 0 when all tests that RAN passed, even if some tests ERROR-ed (couldn't run at all due to ImportError, AttributeError, etc.). The test runner's summary line says "OK" but the per-test output shows "ERROR". Always scan the full output for "ERROR:" lines, not just the exit code or final summary line. Discovered during v3.1 integration (2026-06-29): the controller reported "7/7 pass" when 5/7 were actually ERROR-ing due to a signature mismatch. GLM caught this by reading the full test output.
- **GLM-5.2 is the reliable synthesis/planning model when DeepSeek is unstable** — for long structured outputs (improvement plans, multi-file synthesis, design reviews), GLM-5.2:cloud consistently delivers complete results where DeepSeek V4 Pro drops mid-stream. Use GLM for: improvement plan generation, advisor panel synthesis, long-form design review. Use DeepSeek for: short targeted reviews, code-level analysis, architectural reasoning. This is the same pattern as the advisors skill's synthesis step (GLM reads all files, writes synthesis).
- **Uncommitted state: use patch-file approach, not blunt git commit** — when creating child worktrees that need the orchestrator's uncommitted state, use `git diff HEAD --binary` to capture a patch + `git ls-files --others --exclude-standard` for untracked files (filtered to exclude `.sdlc/`). Apply with `git apply --index` in the child worktree. Do NOT use `git add -A && git commit` — it pollutes git history with checkpoint commits and leaks `.sdlc/` state files to children. Full design with 37 corner cases in `references/worktree-uncommitted-state-workflow.md`. E2E-validated with 10/10 tests passing — see `references/worktree-e2e-test-2026-06-29.md` for the test suite.
- **Pre-merge commit: dirty working tree blocks `git merge`** — when merging a child branch back to the parent worktree, `git merge` fails with "Your local changes would be overwritten by merge" if the parent has uncommitted changes. Fix: auto-commit the parent's working state before merging (`git add -A && git diff --cached --quiet || git commit -m "checkpoint: pre-merge state"`). This is corner case M5 from DeepSeek's 37-corner-case analysis. Discovered during E2E testing (2026-06-29) — tests 01 and 10 failed until this was added.
- **Dynamic branch detection — don't hardcode "main"** — `git init` creates "master" by default on older git versions, and repos can use any default branch name. Always detect the current branch dynamically with `git branch --show-current` instead of hardcoding "main" in rebase/merge targets. Discovered during E2E testing (2026-06-29) — 5/10 tests failed with `fatal: invalid upstream 'main'` until the hardcoded string was replaced with dynamic detection.
- **Coder models return code as text, don't write files to worktree** — when the IMPLEMENT phase dispatches a coder model (qwen3-coder-next, etc.), the model may return generated code as text output rather than writing files to the worktree. This causes 0/0 tests (no test files found) and eventual stagnation. Two fixes: (a) the dispatch prompt should explicitly instruct the model to write files to the worktree using the file tools, or (b) the orchestrator should extract code blocks from the model's response and write them to the worktree itself. Option (b) is more reliable since it doesn't depend on model compliance. Use `extract_python_code()` with `ast.parse()` verification, then write extracted code to the worktree.
- **v6 iteration counter off-by-one — shows "Iteration 2" on first real iteration** — `run.iteration` starts at 1 (SDLCRun default), PLAN does `run.iteration += 1` before the max_iterations check, so the first iteration shows "Iteration 2/45" instead of "Iteration 1/45". Fix: set `run.iteration = 0` before the v6 while loop on fresh start (NOT in INIT — that breaks re-plan paths). Keep `run.iteration += 1` in PLAN where it was — all re-plan paths (GAPS→PLAN, DEBUG widening→PLAN, cascade fail→PLAN) go through PLAN, so they all increment correctly. The fresh-start reset to 0 ensures the first PLAN entry produces iteration 1. **Do NOT move the increment to INIT** — that causes a regression where re-plan paths never increment, so max_iterations is never reached on re-plans, potentially causing infinite loops. This regression was caught by ad-hoc verification (2026-06-28) and the fix was corrected before commit. See `references/v6-optimization-analysis-2026-06-28.md` §BUG1.
- **v6 env vars `SDLC_WALL_CLOCK`/`SDLC_MAX_ITER` not parsed** — the orchestrator shows 7200s remaining even when `SDLC_WALL_CLOCK=300` is set. The `run_sdlc_v6()` function accepts `max_iterations` and `wall_clock_budget` parameters but doesn't check `os.environ` for overrides. Fix: add `max_iterations = int(os.environ.get("SDLC_MAX_ITER", max_iterations))` and `wall_clock_budget = int(os.environ.get("SDLC_WALL_CLOCK", wall_clock_budget))` at function entry. See `references/v6-optimization-analysis-2026-06-28.md` §BUG2.
- **Config deference: pass `None` for ALL parameters Hermes has config keys for** — the SDLC orchestrator had 15 hardcoded values across 15 dispatch sites in both `sdlc_state.py` and `sdlc.py`: 8 `max_turns` (5, 8, 1) and 7 `thinking` ("medium", "low", "high"). The user corrected both: "Hermes already has max_turns: 120 in config" and "No, don't hardcode thinking levels either. Pass None." Fix: `max_turns=None` and `thinking=None` everywhere. When `None`, `dispatch_single()` omits the flag/config mutation entirely, and the subprocess inherits the Hermes default. Only hardcode parameters with NO Hermes config key: `timeout` (safety net), `toolsets` (per-role access control), `provider` (model routing), `role` (directive injection), `cwd` (worktree isolation). Also fixed `dispatch_with_evaluation` signature from `max_turns: int` to `max_turns: Optional[int]`. Audit technique: when the user flags one hardcoded parameter, audit ALL parameters across ALL dispatch sites in ALL files — a single grep for `dispatch_single(` catches everything. See `references/hardcoded-values-audit-2026-06-28.md` for the full 15-site audit. — the first BUG3 fix used terminator matching (`". "`, `"... "`, `"— "`) to strip the warning prefix and preserve content on the same line. This caused 3 residue problems: "stopping" leaked from `"— stopping"`, "Requesting summary..." leaked from the warning's second sentence, and warning-only lines left "Requesting summary..." as the entire preview. Root cause: the warning has multiple parts (sentence 1: "Reached maximum iterations (8).", sentence 2: "Requesting summary...") and the terminator approach could only strip one part. Fix: drop the entire first line if it contains "reached maximum iterations." Tradeoff: content on the same line (e.g., "I created files") is lost, but the preview is just a 150-char glimpse — actual code is already on disk. 12/12 ad-hoc checks pass, no residue, no false positives. **Lesson: when filtering multi-part warnings, prefer whole-line drop over terminator matching.** See `references/bug3-filter-diagnosis-2026-06-28.md` for the full trace analysis.
- **v6 IMPLEMENT preview shows "reached max iterations" warning**
- **Two-level iteration counters: `--max-turns` ≠ `MAX_ITERATIONS_DEFAULT_V6`** — these are completely separate counters at different levels of the system. `--max-turns` (our `TURNS_CODER_V6=8`, `TURNS_PLANNER_V6=5`, etc.) controls the **inner loop**: how many tool-calling iterations a single `hermes chat -q` subprocess gets before Hermes forces a summary. Each iteration = one API call where the model can use tools (write_file, terminal, etc.). When the model exhausts all turns without naturally stopping, Hermes calls `handle_max_iterations()` which prints "⚠️ Reached maximum iterations (N). Requesting summary..." and forces a final text-only response. `MAX_ITERATIONS_DEFAULT_V6=45` controls the **outer loop**: how many times the orchestrator state machine cycles through PLAN→IMPLEMENT→TEST→DEBUG→VERIFY. The "Reached maximum iterations" warning in coder output is an inner-loop event — the coder used all its tool-calling turns but the orchestrator continues normally. The warning is cosmetic noise (files are already on disk) that we filter in `_emit_preview()`. Do NOT confuse this with the orchestrator hitting its iteration limit — that's a separate `run.iteration >= run.max_iterations` check in the PLAN state. See `references/v6-optimization-analysis-2026-06-28.md` §BUG3 for the full trace from `dispatch_single(max_turns=8)` → `hermes chat --max-turns 8` → `agent.max_iterations = 8` → `handle_max_iterations()` → warning in output.
- **v6 optimization: skip PLAN on iteration 1 — REJECTED by user (2026-06-28)** — proposed skipping the planner dispatch on iteration 1 (~25s savings). User explicitly rejected: "always plan and replan." The planner adds structuring (file layout, module names, test strategy) that PROJECT.md alone doesn't provide. Do NOT implement this optimization — always dispatch planner on every iteration, including iteration 1. See `references/v6-optimization-analysis-2026-06-28.md` §OPT1.
- **v6 optimization: fast-verify when all tests pass — REJECTED by user (2026-06-28)** — proposed skipping the DeepSeek verifier when all tests pass (~18s savings). User explicitly rejected: "we never know if that's correct." The verifier catches issues that passing tests miss (incorrect assertions, missing edge cases, design flaws). Do NOT implement this optimization — always run the verifier on every iteration. See `references/v6-optimization-analysis-2026-06-28.md` §OPT2.