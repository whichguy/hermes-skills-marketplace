---
name: subagent-driven-development
description: Execute plans via delegate_task subagents (2-stage review).
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - delegation
    - subagent
    - implementation
    - workflow
    - parallel
    related_skills:
    - writing-plans
    - requesting-code-review
    - test-driven-development
    config:
    - key: subagent-driven-development.enabled
      description: Enable subagent-driven-development skill behavior
      default: true
      prompt: Enable subagent-driven-development skill?
    category: software-development
---
---

# Subagent-Driven Development

## Overview

Execute implementation plans by dispatching fresh subagents per task with systematic two-stage review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration.

## When to Use

Use this skill when:
- You have an implementation plan (from writing-plans skill or user requirements)
- Tasks are mostly independent
- Quality and spec compliance are important
- You want automated review between tasks

**vs. manual execution:**
- Fresh context per task (no confusion from accumulated state)
- Automated review process catches issues early
- Consistent quality checks across all tasks
- Subagents can ask questions before starting work

## The Process

### 1. Read and Parse Plan

Read the plan file. Extract ALL tasks with their full text and context upfront. Create a todo list:

```python
# Read the plan
read_file("docs/plans/feature-plan.md")

# Create todo list with all tasks
todo([
    {"id": "task-1", "content": "Create User model with email field", "status": "pending"},
    {"id": "task-2", "content": "Add password hashing utility", "status": "pending"},
    {"id": "task-3", "content": "Create login endpoint", "status": "pending"},
])
```

**Key:** Read the plan ONCE. Extract everything. Don't make subagents read the plan file — provide the full task text directly in context.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Dispatch Implementer Subagent

Use `delegate_task` with complete context:

```python
delegate_task(
    goal="Implement Task 1: Create User model with email and password_hash fields",
    context="""
    TASK FROM PLAN:
    - Create: src/models/user.py
    - Add User class with email (str) and password_hash (str) fields
    - Use bcrypt for password hashing
    - Include __repr__ for debugging

    FOLLOW TDD:
    1. Write failing test in tests/models/test_user.py
    2. Run: pytest tests/models/test_user.py -v (verify FAIL)
    3. Write minimal implementation
    4. Run: pytest tests/models/test_user.py -v (verify PASS)
    5. Run: pytest tests/ -q (verify no regressions)
    6. Commit: git add -A && git commit -m "feat: add User model with password hashing"

    PROJECT CONTEXT:
    - Python 3.11, Flask app in src/app.py
    - Existing models in src/models/
    - Tests use pytest, run from project root
    - bcrypt already in requirements.txt
    """,
    toolsets=['terminal', 'file']
)
```

#### Step 2: Dispatch Spec Compliance Reviewer

After the implementer completes, verify against the original spec:

```python
delegate_task(
    goal="Review if implementation matches the spec from the plan",
    context="""
    ORIGINAL TASK SPEC:
    - Create src/models/user.py with User class
    - Fields: email (str), password_hash (str)
    - Use bcrypt for password hashing
    - Include __repr__

    CHECK:
    - [ ] All requirements from spec implemented?
    - [ ] File paths match spec?
    - [ ] Function signatures match spec?
    - [ ] Behavior matches expected?
    - [ ] Nothing extra added (no scope creep)?

    OUTPUT: PASS or list of specific spec gaps to fix.
    """,
    toolsets=['file']
)
```

**If spec issues found:** Fix gaps, then re-run spec review. Continue only when spec-compliant.

#### Step 3: Dispatch Code Quality Reviewer

After spec compliance passes:

```python
delegate_task(
    goal="Review code quality for Task 1 implementation",
    context="""
    FILES TO REVIEW:
    - src/models/user.py
    - tests/models/test_user.py

    CHECK:
    - [ ] Follows project conventions and style?
    - [ ] Proper error handling?
    - [ ] Clear variable/function names?
    - [ ] Adequate test coverage?
    - [ ] No obvious bugs or missed edge cases?
    - [ ] No security issues?

    OUTPUT FORMAT:
    - Critical Issues: [must fix before proceeding]
    - Important Issues: [should fix]
    - Minor Issues: [optional]
    - Verdict: APPROVED or REQUEST_CHANGES
    """,
    toolsets=['file']
)
```

**If quality issues found:** Fix issues, re-review. Continue only when approved.

#### Step 4: Mark Complete

```python
todo([{"id": "task-1", "content": "Create User model with email field", "status": "completed"}], merge=True)
```

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer:

```python
delegate_task(
    goal="Review the entire implementation for consistency and integration issues",
    context="""
    All tasks from the plan are complete. Review the full implementation:
    - Do all components work together?
    - Any inconsistencies between tasks?
    - All tests passing?
    - Ready for merge?
    """,
    toolsets=['terminal', 'file']
)
```

### 4. Verify and Commit

```bash
# Run full test suite
pytest tests/ -q

# Review all changes
git diff --stat

# Final commit if needed
git add -A && git commit -m "feat: complete [feature name] implementation"
```

## Task Granularity

**Each task = 2-5 minutes of focused work.**

**Too big:**
- "Implement user authentication system"

**Right size:**
- "Create User model with email and password fields"
- "Add password hashing function"
- "Create login endpoint"
- "Add JWT token generation"
- "Create registration endpoint"

## Controller Behavior During Subagent Execution

**Follow the `delegate-progress-protocol` skill** for all subagent dispatches.
It provides the three-phase protocol (pre-dispatch plan → incremental status →
completion summary) that applies to this and all other delegation work.

Key behaviors from that protocol:
- **Pre-dispatch plan:** Show a table of subagents, goals, toolsets, est. time before calling delegate_task
- **Status every 2 minutes:** Background `sleep 120` + `notify_on_complete=true` polling loop
- **Report immediately when results arrive:** Don't wait for the next poll cycle
- **Structured completion summary:** Table with per-subagent time, status, key result + highlights + next steps

Load `skill_view(name='delegate-progress-protocol')` for the full protocol.

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical/important issues
- Dispatch multiple implementation subagents for tasks that touch the same files
- Make subagent read the plan file (provide full text in context instead)
- Skip scene-setting context (subagent needs to understand where the task fits)
- Ignore subagent questions (answer before letting them proceed)
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → implementer fixes → review again)
- Let implementer self-review replace actual review (both are needed)
- **Start code quality review before spec compliance is PASS** (wrong order)
- Move to next task while either review has open issues
- **Dispatch parallel subagents that modify the same file without a merge plan** — see Pitfall below

## Pitfalls

### Output-only dispatch phases need `toolsets=''` + `max_turns=1`

When dispatching a model whose job is to *produce* code or text (not to use tools), strip tool access entirely. Passing `toolsets='web'` or `toolsets='file'` to a code-generation or review phase causes models to attempt tool calls (e.g. `execute_code`) instead of outputting the requested content. This manifests as `Model generated invalid tool call: execute_code` errors.

**Affected phases:** `tech_docs`, `simplify_code`, `council_review`, `implement` (code generation), and any other phase where the model's output IS the deliverable.

**Phases that genuinely need tools:** `plan` (file inspection), `design_test_suites` (codebase inspection).

**Fix pattern:**
```python
# BEFORE (broken — model tries to call tools instead of outputting code)
dispatch_single(
    model=model,
    prompt=prompt,
    toolsets='web',      # ❌ gives model tool access
    max_turns=5,         # ❌ allows tool-call iteration
    ...
)

# AFTER (correct — model outputs code/text directly)
dispatch_single(
    model=model,
    prompt=prompt,
    toolsets='',         # ✅ no tools — output only
    max_turns=1,         # ✅ single response, no iteration
    ...
)
```

### Batch delegation hides progress — prefer individual dispatch for visibility

When you dispatch multiple subagents via `delegate_task(tasks=[...])` (batch mode), the system waits for **all** subagents to complete before returning a single consolidated result. There is no intermediate progress API — you cannot peek at individual subagent state mid-run. For deep code reviews (5+ agents reading large files), this can mean 20-30+ minutes of silence.

**Decision rule (apply before every multi-subagent dispatch):**

| Scenario | Dispatch mode | Rationale |
|---|---|---|
| User is actively waiting for results | **Individual** `delegate_task(goal=...)` × N | Results stream in as each finishes; user sees progress |
| Fire-and-forget (cron, background, no human watching) | Batch `delegate_task(tasks=[...])` | Consolidation overhead acceptable; no one is waiting |
| Subagents expected to finish in <2 min each | Either — batch is fine | Short enough that silence doesn't matter |
| Subagents expected to take >5 min each | **Individual** always | Long silence erodes trust; user will ask "Status?" |
| User has already asked "Status?" or expressed frustration | **Individual** always | Trust already damaged — don't make them ask again |

**Default: when in doubt, use individual dispatch.** The cost of individual dispatch (slightly more controller turns) is negligible compared to the cost of a frustrated user who can't see progress.

**Recovery pattern — kill stuck batch, re-dispatch individually:**

If you already dispatched in batch mode and it's been >10 minutes with no results:
1. Tell the user you're killing the batch and re-dispatching individually
2. Re-dispatch the same tasks as individual `delegate_task(goal=...)` calls (one per `delegate_task` invocation)
3. Each returns independently the moment it finishes — results stream in one at a time
4. Start the 2-minute polling loop (see "Controller Behavior During Subagent Execution" above)
5. The total wall-clock time is the same (they still run in parallel), but the user sees partial results as they land

**When batch mode is still appropriate:**
- Fire-and-forget dispatches where the user doesn't need intermediate progress
- Very fast subagents (<2 min each) where the consolidation overhead of individual calls outweighs the visibility benefit
- Cron/scheduled jobs with no human watching

**When to use individual dispatch:**
- User is actively waiting for results
- Subagents are expected to take >5 min each
- The user has asked for status updates or expressed frustration about silence
- You're running a polling loop anyway — individual dispatch eliminates the need for it

### Parallel subagents modifying the same file cause silent conflicts

When you dispatch multiple subagents in parallel (via `tasks` array or multiple `delegate_task` calls) and they modify the same file (e.g., `engine.py`), conflicts are inevitable:

1. **Orphaned lines / IndentationError** — One agent's `patch` may leave stray lines from another agent's concurrent edit. The file won't compile.
2. **Abstract method drift** — Agent A adds an abstract method to a base class; Agent B modifies the concrete class but doesn't know about the new method. `TypeError: Can't instantiate abstract class`.
3. **Clobbered changes** — Agent A writes a file, then Agent B writes the same file with different content, losing A's work.

**Prevention:**
- Partition work so parallel agents touch **disjoint files**. If they must touch the same file, serialize those tasks.
- After parallel agents complete, always: (1) re-read modified files, (2) run `py_compile` or equivalent syntax check, (3) run the full test suite.
- If conflicts occur, dispatch a single merge-fix subagent with the specific error messages — don't try to fix manually in the controller session (context pollution).
- Include "re-read files before applying patches after parallel subagent work" as an explicit instruction in subagent context when parallel work is happening.

### Sibling subagents can revert the parent controller's uncommitted changes

**Different from the parallel-conflict pitfall above.** This is about a sibling
subagent overwriting changes the *parent controller* already made to a file
(not two subagents conflicting with each other). The parent edits a file, then
dispatches a subagent for unrelated work — the subagent writes a fresh version
of the same file, reverting the parent's changes.

**Real example (Jun 2026):** The parent removed `DEFAULT_MAX_TURNS` from
`model_utils.py`. A sibling subagent (`20260628_021420_e7fe93`) later wrote
the file with the old constant restored. The parent's `grep` verification
caught it.

**Detection:** After any subagent dispatch, `grep` for your key change before
declaring done.

**Lock-in fix:** If a sibling reverts your changes more than once, commit and
push immediately. Sibling subagents can only overwrite uncommitted working-tree
files — they can't revert committed changes without a conflicting commit.

See also: `ask` skill pitfall "Sibling Subagents Can Revert File Changes" for
the full incident report.

### Subagent tool budget exhaustion leaves partial work

When a subagent is assigned multiple tasks and hits its tool budget before completing all of them, it returns a summary of what was done and what remains. The controller MUST:

1. **Verify completed work** — run tests, check file contents, confirm the subagent's claims
2. **Identify incomplete tasks** — compare the subagent's summary against the original task list
3. **Finish remaining work directly** — do NOT re-dispatch the same partial state (context pollution, the new subagent has no memory of what was already done)
4. **Run full test suite** — catch regressions from the subagent's partial changes

Example: subagent assigned Tasks 2-6 completed Tasks 2-4 (lock column, lock methods, lock validation) and partially completed Task 5 (atomic `apply_change` done, `apply_swap` not done). Controller read the subagent's partial work, applied the remaining `apply_swap` patch directly, then ran the full test suite to verify.

### Subagent file truncation: silent massive deletions

Subagents (especially qwen-coder) can silently truncate files — removing 60%+
of the content while leaving the file syntactically valid. The file compiles
but is missing most of its logic.

**Real example (Jun 2026):** A qwen-coder subagent fixing sdlc.py bugs
truncated the file from 2123 lines (90KB) to 840 lines (36KB). The file
still compiled (no SyntaxError) but was missing ~60% of its functions and
classes. The truncation was only discovered when pytest failed with
`SyntaxError: '{' was never closed` at the truncated boundary.

**Detection:**
```bash
# After any subagent code change, check for unexpected massive deletions
git diff --stat  # look for -1000+ line changes
wc -l <file>     # compare against known line count
```

**Recovery:**
```bash
# Restore from last known-good commit
git checkout HEAD -- <file>
```

**Prevention:** Include in subagent context: "Do not truncate or remove
existing code. Only modify the specific lines needed for the fix. Preserve
all existing functions, classes, and imports."

### Subagent escaping artifacts: double-escaped strings in generated code

Subagents (especially qwen-coder) can produce **double-escaped strings** —
literal `\\\\n` instead of `\n`, and `f\\"` instead of `f"`. These compile
(because they're valid Python string literals containing literal backslash
characters) but produce garbled output at runtime.

**Detection:** After any subagent code change, scan for double-escaped patterns:
```bash
grep -n '\\\\\\\\n' <changed_file>
grep -n 'f\\\\"' <changed_file>
```

**Fix:** Replace `\\\\n` → `\n` and `f\\"` → `f"`. These are always artifacts.

**Prevention:** Include in subagent context: "Do not double-escape backslashes
in string literals. Write `\n` not `\\n`, and `f\"` not `f\\\"`."

See `ask` skill pitfall "Subagent Escaping Artifacts" for the full incident
report (Jun 2026, sdlc.py bug fixes).

### Subagent code extraction must verify syntax with `ast.parse()`

When a subagent returns generated code (e.g., from an `implement` phase), the controller or pipeline must extract the code from the subagent's response. A lenient extraction fallback (matching `return`/`if __` keywords) can return prose, error text, or partial code as "valid code." Always verify extracted code with `ast.parse()` before accepting it:

```python
import ast

def extract_python_code(text: str) -> str | None:
    # ... extraction logic (triple-backtick blocks, keyword matching) ...
    if extracted:
        try:
            ast.parse(extracted)
            return extracted
        except SyntaxError:
            return None  # extraction is invalid — don't return prose as code
    return None
```

If `ast.parse()` fails, the extraction is invalid. Return None and set a failure status (e.g., `pipeline_status='implement_failed'`). Never pass unverified extracted text to `exec()`, `compile()`, or a test runner.

**Real example:** A subagent returned a response where the "code" block contained API error text (`"I apologize, but I cannot..."`). The lenient fallback matched `return` in the error text and returned it as code. `ast.parse()` would have caught this — the error text is not valid Python.

## Handling Issues

### If Subagent Asks Questions

- Answer clearly and completely
- Provide additional context if needed
- Don't rush them into implementation

### If Reviewer Finds Issues

- Implementer subagent (or a new one) fixes them
- Reviewer reviews again
- Repeat until approved
- Don't skip the re-review

### If Subagent Fails a Task

- Dispatch a new fix subagent with specific instructions about what went wrong
- Don't try to fix manually in the controller session (context pollution)

## Per-Task Model Overrides

> ⚠️ **Per-task `model` overrides do NOT work (verified 2026-06-27).**
> Despite the code at `tools/delegate_tool.py` reading the per-task model,
> all subagents inherit `delegation.model` from config.yaml. A `delegate_task`
> with `model="deepseek-v4-pro:cloud"` actually runs on whatever
> `delegation.model` is set to. **Do not use per-task model overrides.**
>
> **For per-call model diversity, use `prompt_model.py` from the `advisors`
> skill.** It runs `hermes chat -q` as a subprocess with actual per-call model
> selection. See `skill_view(name='advisors')` for the full process.
>
> **For role-based development with model diversity, use the `dev` skill.**
> It wraps `prompt_model.py` with role aliases (planner → GLM, coder → Qwen,
> code-debugger → Kimi). See `skill_view(name='dev')`.
>
> **For interactive model queries, use the `ask` skill.** It provides alias
> resolution, session memory, and comparison mode. See `skill_view(name='ask')`.
>
> The code examples below are preserved for reference but do NOT produce
> model-diverse subagents in practice.

`delegate_task` supports an optional `model` parameter at both the top level (single-task mode) and per-task (batch mode). This lets you route different task types to different models:

```python
# Single task: route heavy reasoning to a stronger model
delegate_task(
    goal="Analyze concurrency edge cases in the lock manager",
    model="deepseek-v4-pro:cloud",
    context="...",
    toolsets=['terminal', 'file']
)

# Batch: mix models per task
delegate_task(tasks=[
    {"goal": "code review", "model": "kimi-k2.7-code:cloud", "context": "..."},
    {"goal": "reason about algorithm", "model": "deepseek-v4-pro:cloud", "context": "..."},
    {"goal": "default task"},  # uses delegation.model from config
])
```

**Resolution order:** per-task `model` → `delegation.model` in config → parent agent's model.

**When to use:**
- **Coding tasks** → code-specialized model (kimi-k2.7-code, claude-sonnet)
- **Heavy reasoning / analysis** → reasoning-specialized model (deepseek-v4-pro, o3)
- **Default / unspecified** → let config handle it

**Pitfall:** A model override only changes the model name — it does NOT change the provider or credentials. The subagent still uses the delegation provider (or parent's provider if delegation.provider is unset). If the model you specify isn't available on that provider, the subagent will fail at startup. Verify provider-model compatibility before overriding.

**Pitfall (config cache staleness):** `hermes config set delegation.model <model>` writes to disk but the running agent process caches the config value at startup. Subagents dispatched in the same session will still use the OLD model — the change is silently ignored. **Always check the subagent's result message header** (`Model: <actual>`) to confirm which model actually ran. **Workaround:** use `prompt_model.py` from the `advisors` skill for per-call model selection — it runs `hermes chat -q` as a subprocess with actual per-call model diversity. Per-task `model` overrides on `delegate_task` do NOT work reliably in practice (verified 2026-06-27).

**Pitfall (background mode):** When `background=true` is set on a single-task delegation, the async dispatch path (`dispatch_async_delegation`) must receive the per-task model override, not the config default. This was a live bug (fixed in the v0.15.1 patch) — if you modify the dispatch path, verify the model flows through correctly.

**Pitfall (non-string model values):** The LLM may pass non-string values for `model` (e.g., `True`, `123`, `["model"]`). The child-building loop uses `str(t.get("model") or "").strip()` — the `str()` coercion prevents `AttributeError` on `.strip()`. Without it, a truthy non-string like `True` crashes. If you modify the model resolution logic, preserve the `str()` coercion. Falsy non-strings (`0`, `False`) fall through to the config default, which is safe.

## Efficiency Notes

**Why fresh subagent per task:**
- Prevents context pollution from accumulated state
- Each subagent gets clean, focused context
- No confusion from prior tasks' code or reasoning

**Why two-stage review:**
- Spec review catches under/over-building early
- Quality review ensures the implementation is well-built
- Catches issues before they compound across tasks

**Cost trade-off:**
- More subagent invocations (implementer + 2 reviewers per task)
- But catches issues early (cheaper than debugging compounded problems later)

## Integration with Other Skills

### With writing-plans

This skill EXECUTES plans created by the writing-plans skill:
1. User requirements → writing-plans → implementation plan
2. Implementation plan → subagent-driven-development → working code

### With test-driven-development

Implementer subagents should follow TDD:
1. Write failing test first
2. Implement minimal code
3. Verify test passes
4. Commit

Include TDD instructions in every implementer context.

### With requesting-code-review

The two-stage review process IS the code review. For final integration review, use the requesting-code-review skill's review dimensions.

### With systematic-debugging

If a subagent encounters bugs during implementation:
1. Follow systematic-debugging process
2. Find root cause before fixing
3. Write regression test
4. Resume implementation

## Example Workflow

```
[Read plan: docs/plans/auth-feature.md]
[Create todo list with 5 tasks]

--- Task 1: Create User model ---
[Dispatch implementer subagent]
  Implementer: "Should email be unique?"
  You: "Yes, email must be unique"
  Implementer: Implemented, 3/3 tests passing, committed.

[Dispatch spec reviewer]
  Spec reviewer: ✅ PASS — all requirements met

[Dispatch quality reviewer]
  Quality reviewer: ✅ APPROVED — clean code, good tests

[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Dispatch implementer subagent]
  Implementer: No questions, implemented, 5/5 tests passing.

[Dispatch spec reviewer]
  Spec reviewer: ❌ Missing: password strength validation (spec says "min 8 chars")

[Implementer fixes]
  Implementer: Added validation, 7/7 tests passing.

[Dispatch spec reviewer again]
  Spec reviewer: ✅ PASS

[Dispatch quality reviewer]
  Quality reviewer: Important: Magic number 8, extract to constant
  Implementer: Extracted MIN_PASSWORD_LENGTH constant
  Quality reviewer: ✅ APPROVED

[Mark Task 2 complete]

... (continue for all tasks)

[After all tasks: dispatch final integration reviewer]
[Run full test suite: all passing]
[Done!]
```

## Remember

```
Fresh subagent per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
```

**Quality is not an accident. It's the result of systematic process.**

## Further reading (load when relevant)

When the orchestration involves significant context usage, long review loops, or complex validation checkpoints, load these references for the specific discipline:

- **`references/context-budget-discipline.md`** — Four-tier context degradation model (PEAK / GOOD / DEGRADING / POOR), read-depth rules that scale with context window size, and early warning signs of silent degradation. Load when a run will clearly consume significant context (multi-phase plans, many subagents, large artifacts).
- **`references/gates-taxonomy.md`** — The four canonical gate types (Pre-flight, Revision, Escalation, Abort) with behavior, recovery, and examples. Load when designing or reviewing any workflow that has validation checkpoints — use the vocabulary explicitly so each gate has defined entry, failure behavior, and resumption rules.
- **`references/ad-hoc-verification-pattern.md`** — Write a temp script to `/tmp/hermes-verify-*.py`, run structural checks (file existence, YAML parse, Python syntax, model mapping consistency), report pass/fail, clean up. Load after creating/modifying skills or multi-file artifacts — catches mechanical errors subagents and controllers both miss. Includes the section-parser-in-code-blocks pitfall.

Both references adapted from gsd-build/get-shit-done (MIT © 2025 Lex Christopherson).

- **`references/three-model-review-pipeline.md`** — User's preferred 3-model review pipeline: DeepSeek V4 Pro for plan/test review, Kimi (kimi-k2.7-code) for code review + auto-fix, Qwen coder for code production. Load when dispatching review subagents for development work.
- **`references/yagni-design-review-pattern.md`** — YAGNI simplification analysis workflow: controller writes analysis → DeepSeek reviews against actual codebase → incorporate corrections → present corrected plan. Load when the user asks "is this overbuilt?" or "what should we cut?"
