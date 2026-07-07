---
name: multi-model-code-review
description: "Iterative code review using multiple LLM subagents (Kimi for review, Deepseek for gap analysis) to find bugs and test coverage gaps."
version: 1.0.0
---

# Multi-Model Code Review Pipeline

Use different LLMs to review code changes. Each model catches different things — Kimi excels at structural/logic review, Deepseek excels at edge-case/gap analysis.

## When to Use

- Implementing a feature patch against an upstream codebase
- Wanting thorough review beyond a single pass
- Looking for bugs, test coverage gaps, and edge cases

## Recommended Method: `ask qa` (primary)

**Use `ask qa` for most code reviews.** It's faster (~80s for 3 files / ~10K lines), simpler, and avoids the delegate_task model-override pitfalls. See the `ask` skill "QA Code Review" section for the full workflow.

```bash
# Agent mode (recommended — full file access, reads code directly)
python3 /opt/data/skills/productivity/ask/scripts/ask.py qa \
    -p "Review routing.py, model_utils.py, and triage.py for bugs" \
    --mode agent --thinking low --timeout 180 \
    --toolsets file,terminal
```
**Note:** `--max-turns` is intentionally omitted — Hermes config `agent.max_turns` (120) is the source of truth. Do not override it unless the user explicitly requests a specific value. Same config-deference principle as the `ask` and `advisors` skills.

**Proven results** (Jun 2026, 4 files): 40 findings (10 HIGH, 20 MEDIUM, 10 LOW) in ~80s. All 10 HIGH + 1 MEDIUM fixed, 115/115 tests pass, 0 regressions.

**Proven results** (Jun 2026, pipeline test suite): Kimi designed 8 test classes (~50 tests) for the SDLC pipeline. After implementation, Kimi re-reviewed and found 15 gaps (7 HIGH). All 7 HIGH fixed + 21 new tests added. Final: 230 tests (213 non-live), all passing.

### QA Fix Workflow (after review)

1. **Verify findings** — read actual lines; some may be false positives. **This is critical: advisors can hallucinate issues.** In a 2026-06-28 3-seat review of `sdlc_state.py`, 2/4 Kimi HIGH findings were false positives (K-H1: claimed `_emit_preview` was called before definition — it was defined 20 lines earlier; K-H4: claimed `_remaining_time` had a division-by-zero — the function uses `max(1, elapsed)` as denominator). Always cross-reference each finding against the actual code before applying fixes. A finding that sounds plausible may be completely wrong.
2. **Write a fix plan** — table with file, issue, fix, line references. Mark false positives as "NOT A BUG — [reason]" so the user can see what was reviewed and dismissed.
3. **Batch fixes** — all fixes in one pass, grouped by file
4. **Verify** — compile all changed files, ad-hoc checks, full test suite
5. **Commit** — one commit with descriptive message

**Verification discipline:** The system tracks changed paths and flags "unverified" after a commit even when verification was already done pre-commit. After committing, re-run a quick ad-hoc verification (compile + test suite) to satisfy the flag. Pattern: verify → commit → system flags unverified → re-verify (quick compile + test suite).

## Fallback: delegate_task Pipeline (for very large or multi-model reviews)

Use `delegate_task` when you need multiple models reviewing in parallel, or when the codebase is too large for a single `ask qa` call. **⚠️ Per-task `model` overrides do NOT work reliably** — all subagents inherit `delegation.model` from config.yaml. Use `ask` with different aliases instead for per-call model diversity.

### Pipeline Steps

### Option A: Parallel Dispatch (for plan+code reviews)

When you have both a plan and code to review, dispatch Kimi and DeepSeek **simultaneously** in a single batch call. This cuts wall-clock time in half:

```python
delegate_task(tasks=[
    {
        "goal": "Review the code changes for correctness, edge cases, and security",
        "context": "The source is at /path. Run `git diff` to see changes. [specific instructions]",
        "model": "kimi-k2.7-code:cloud",
        "toolsets": ["terminal", "file"],
    },
    {
        "goal": "Review the plan and test coverage for architectural gaps",
        "context": "The plan is at /path/to/plan.md. Verify every claim against the actual codebase.",
        "model": "deepseek-v4-pro:cloud",
        "toolsets": ["terminal", "file"],
    },
])
```

After both land, consolidate findings into a single issues list, apply all fixes, then re-verify.

**⚠️ Batch mode hides progress.** When using `delegate_task(tasks=[...])`, the system waits for ALL subagents to complete before returning results. There is no intermediate progress API. For deep reviews (5+ agents, large files), this can mean 20-30+ minutes of silence. When the user is actively waiting, prefer individual `delegate_task(goal=...)` calls — each returns independently as it finishes, so results stream in one at a time. Total wall-clock time is the same (they still run in parallel), but the user sees partial results instead of waiting for the slowest subagent. See `subagent-driven-development` skill for the full pitfall.

### Option B: Sequential Pipeline (for iterative refinement)

### Step 1: Implement + Self-Verify
- Write the code changes
- Run existing test suite to establish baseline
- Run ad-hoc verification script (tempfile with `hermes-verify-` prefix)

### Step 2: Kimi Review (structural)
- Dispatch to `kimi-k2.7-code:cloud` with `toolsets: ["terminal", "file"]`
- Ask for: correctness, edge cases, security, backward compatibility, architectural fit
- Have it read the live `git diff`

### Step 3: Apply Fixes + Re-Verify
- Apply Kimi's recommended fixes
- Run pytest suite + ad-hoc verification
- Confirm zero regressions

### Step 4: Kimi Re-Review (confirmation)
- Dispatch again to verify all fixes are resolved
- Ask specifically: "are the 3 prior issues fully resolved?"

### Step 5: Kimi Coverage Review
- Dispatch with goal: "identify which tests need to be introduced"
- Ask for: missing edge cases, interaction with other features, error paths
- Prioritize by risk level

### Step 6: Deepseek Test Plan
- Dispatch to `deepseek-v4-pro:cloud` with the gap list
- Ask for: exact test name, setup/patches, assertion strategy, mock structure
- Read existing test patterns to match style

### Step 7: Deepseek Gap Audit
- After implementing planned tests, dispatch again to Deepseek
- Ask for: cases NOT already covered — "do NOT duplicate existing coverage"
- This catches crashes and type safety issues other models miss

### Step 8: Consolidate
- Update plan doc with all learnings, bugs found, test count
- Save as skill if the pipeline itself was reusable

## Dual-Review Cross-Validation Pattern (NEW — 2026-06-29)

When you need high-confidence findings (not just a single review), use the **parallel dual-review + cross-validation** pattern:

1. **Dispatch Reviewer A** (e.g., Qwen-coder) — full code review of all files, structured findings
2. **Dispatch Reviewer B** (e.g., Kimi) — same files, BUT also asked to **validate/challenge Reviewer A's findings**
3. **Cross-reference**: Reviewer B produces a table marking each finding as VALID / PARTIALLY VALID / FALSE POSITIVE
4. **Implement only confirmed bugs** — bugs both reviewers agree on. This eliminates false positives (Qwen had 2/7 HIGH false positives in a real session).
5. **Reviewer B also finds NEW issues** — the second reviewer catches blind spots the first missed (Kimi found 10 new issues Qwen missed).

**Why this works:**
- Different models have different blind spots (Qwen: false positives on role injection, "nothing to commit" handling; Kimi: caught the real race condition on SET vs RESTORE)
- Cross-validation eliminates rubber-stamping — Reviewer B must read the actual code at cited line numbers
- The "validate or challenge" framing produces more critical analysis than a second independent review

**Proven results** (Jun 2026, 7 SDLC files, 6,944 lines):
- Qwen: 7 HIGH + 14 MEDIUM findings
- Kimi cross-validation: 5/7 HIGH valid, 2 false positives; 6/14 MEDIUM valid, 4 false positives
- Kimi new findings: 10 (3 HIGH, 7 MEDIUM)
- 8 confirmed bugs implemented and verified (14/14 ad-hoc checks pass)

**Dispatch template:**
```python
# Round 1: Reviewer A
delegate_task(
    goal="Review all files for bugs, edge cases, and design flaws. Output structured findings.",
    context="Files: [list]. Read every file. Output table: | # | File:Line | Issue | Severity |",
    toolsets=["file", "terminal"],
)

# Round 2: Reviewer B (cross-validate)
delegate_task(
    goal="Independently review the same files AND validate/challenge Reviewer A's findings. Read actual code at cited lines.",
    context="Reviewer A found: [summary]. Read all files yourself. For each finding: VALID/PARTIALLY VALID/FALSE POSITIVE. Also find NEW issues.",
    toolsets=["file", "terminal"],
)
```

## Key Learnings

1. **Different models find different bugs** — Kimi found the background dispatch bug (structural), Deepseek found the non-string crash (type safety)

**Hermes Hook Architectural Review:** When reviewing monkey-patched gateway hooks (like `suggestion-stripper/handler.py`), use the 5-dimension checklist in `references/hermes-hook-architectural-review.md`. It covers code-span regex protection edge cases, flag lifecycle, platform detection, async safety, and regression risk assessment — the dimensions that most commonly hide bugs in this class of code.
2. **`str()` coercion before `.strip()`** — when handling optional fields from LLM JSON, always `str(val or "").strip()` to handle `True`/`False`/`0`/`None`/lists
3. **Background/sync path parity** — any model override logic must be applied in BOTH the sync path and the async/background dispatch path
4. **Patch `_load_config` in tests** — environment config leaks into test runs; always mock config for hermetic tests
5. **Pyright type warnings on JSON-string args** — `_recover_tasks_from_json_string` intentionally accepts strings; Pyright warnings are expected and safe to ignore
6. **3-round iterative review pattern** — Round 1 finds structural issues (10 findings), Round 2 confirms fixes + finds edge cases (6 findings, mostly NICE TO HAVE), Round 3 gives final sign-off (PRODUCTION-READY). Each round finds progressively smaller issues. Stop after Round 3 unless new code was added.
7. **Architectural-layer check** — When reviewing a fix, ask: "Is this the right layer?" A hook-layer workaround for a gateway-level problem should be flagged as a SHOULD FIX (the fix belongs upstream). The reviewer should identify the correct layer and recommend moving the fix there.
8. **`ask qa` for single-pass review** — For quick code review without the full delegate_task pipeline, use `ask qa` (from the `ask` skill). It dispatches qwen3-coder-next via `prompt_model.py` in agent mode with file+terminal toolsets. Proven on 3 files (~10K lines): found 9 HIGH, 15 MEDIUM, 13 LOW issues in ~80s. See `ask` skill "QA Code Review" section for the prompt template and workflow.
9. **QA fix workflow** — After a review surfaces issues: (a) verify findings by reading actual lines (some are false positives), (b) write a fix plan table, (c) batch all fixes in one pass grouped by file, (d) compile + ad-hoc verify + run full test suite, (e) single commit with descriptive message. Proven on 9 fixes across 3 files — 117/118 tests pass, 0 regressions.
10. **Kimi re-review catches implementation gaps** — After implementing fixes from a Kimi review, dispatch Kimi again to re-review. It will find gaps the implementer missed: alias resolution not applied before dispatch, missing test classes for new code paths, stale mock assertions after refactoring. Proven Jun 2026: Kimi round 2 found 15 gaps (7 HIGH) in the pipeline test suite implementation. All 7 HIGH fixed + 21 new tests added.

## Dispatch Pattern

Model overrides work in both single-task and batch mode. For parallel reviews, use batch mode with per-task model overrides:

```python
# Single-task mode: dispatch one reviewer with a model override
delegate_task(
    goal="Review the code changes for correctness, edge cases, and security",
    model="kimi-k2.7-code:cloud",
    context="The source is at /path. Run `git diff` to see changes. [specific instructions]",
    toolsets=["terminal", "file"],
)

# Batch mode: dispatch different models for different review passes in parallel
delegate_task(tasks=[
    {
        "goal": "Review the code changes for correctness, edge cases, and security",
        "context": "The source is at /path. Run `git diff` to see changes. [specific instructions]",
        "model": "kimi-k2.7-code:cloud",
        "toolsets": ["terminal", "file"],
    },
    {
        "goal": "Review the plan and test coverage for architectural gaps",
        "context": "The plan is at /path/to/plan.md. Verify every claim against the actual codebase.",
        "model": "deepseek-v4-pro:cloud",
        "toolsets": ["terminal", "file"],
    },
])
```

**⚠️ Per-task `model` overrides do NOT work reliably.** Despite the code at `tools/delegate_tool.py` line 2225 reading the per-task model, in practice all subagents inherit `delegation.model` from config.yaml. This was verified in a live test (2026-06-27): a `delegate_task` with `model="deepseek-v4-pro:cloud"` actually ran on `qwen3-coder-next:q4_K_M` (the config default). **Use `prompt_model.py` from the `advisors` skill instead** for per-call model selection — it runs `hermes chat -q` as a subprocess with actual per-call model diversity. See the `advisors` skill and the `dev` skill for role-based development with verified model diversity.

## Pitfalls

- **Config deference: do not override Hermes config defaults.** The `--max-turns` flag defaults to `None` in `prompt_model.py` and `ask.py`, which means Hermes config `agent.max_turns` (120) is the source of truth. Do NOT hardcode `--max-turns` in review dispatches unless the user explicitly requests a specific value. Same principle as the `ask` and `advisors` skills. The `ask qa` example above intentionally omits `--max-turns`.
- **Stale background reviews: cross-reference, don't blindly apply.** When you launch a review as a background process, then apply fixes before it completes, the review lands against pre-fix code. Some findings will already be resolved. Read each finding's line reference against the current code — only apply what's still relevant. Proven Jun 2026: Kimi round 2 (launched before fixes, completed after) found 6 issues on pre-fix code; 4 were already fixed, 2 were new and valid. Cross-referencing saved ~15 min of re-fixing already-resolved issues.
- **Verification discipline: run tests after EVERY fix batch, not after accumulating multiple edits.** The system tracks changed paths and flags stale verification. If you edit 3 files, run tests, then edit 2 more files, you must run tests again — the first run's evidence is now stale. Pattern: edit → test → verify → next edit. Never batch multiple edit cycles before running tests.
- **`delegation.model` in config.yaml overrides per-task model overrides — but only due to config cache staleness.** The per-task `model` field in `delegate_task` IS read by the code (line 2225 of `tools/delegate_tool.py`), but the running agent process caches the config value at startup. If `delegation.model` was set before the session started, per-task overrides may be silently ignored because the cached config takes precedence. **Workaround:** set `delegation.model` to the model you want MOST subagents to use, then use per-task overrides for exceptions. Or use `prompt_model.py` from the `advisors` skill for guaranteed per-call model diversity. **Always verify** which model actually ran by checking the subagent's result message header (`Model: <actual>`).
- **Config changes don't take effect mid-session.** `hermes config set delegation.model <model>` writes to disk but the running agent process caches the config value at startup. Subagents dispatched in the same session will still use the OLD model. **Workaround:** use per-task `model` overrides (which bypass the config-level setting entirely — see line 2225 of `tools/delegate_tool.py`). Per-task overrides are the correct mechanism for mid-session model switching; config-level `delegation.model` is for pinning a default.
- **Config cache staleness is silent.** When you call `hermes config set delegation.model deepseek-v4-pro:cloud` and then dispatch a subagent, the subagent's result message header will show the OLD model (e.g., `kimi-k2.7-code:cloud`). There is no warning or error — the config change is simply ignored. **Always check the subagent's result message header** (`Model: <actual>`) to confirm which model actually ran. If it doesn't match your intent, the config cache is stale. **Workaround:** use per-task `model` overrides instead of config-level `delegation.model`. Per-task overrides are read fresh on each `delegate_task` call and don't depend on the cached config.
- **DeepSeek model has a strong pytest bias (2026-06-27).** When using DeepSeek as a reviewer in Kanban SDLC chains, it repeatedly tries `python3 -m pytest` even when pytest is not installed and the task body explicitly says to use `python3 -m unittest`. This causes crash loops (5+ consecutive crashes → auto-blocked). **Mitigation:** Add "DO NOT use pytest — use `python3 -m unittest`" in ALL CAPS at the top of the review task body. Better yet, use Kimi for review tasks when pytest is not available, or install pytest in the container.
- Don't skip the re-review after fixes — confirm the fix didn't introduce new issues
- Don't let Deepseek duplicate existing coverage — explicitly tell it what's already covered
- Always run the full existing test suite, not just the new tests
- Pre-existing test failures may be environment-specific (config values leaking) — stash changes and re-run to confirm they're not yours