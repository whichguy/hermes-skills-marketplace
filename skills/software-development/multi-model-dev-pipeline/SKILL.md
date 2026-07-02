---
name: multi-model-dev-pipeline
description: >
  6-stage dev pipeline routing planning, review, coding, code review, test
  planning, and test execution to different LLM models via delegate_task
  per-task model overrides. Uses DeepSeek for reasoning stages, Kimi for
  code review/debug, Qwen for code production. Includes git branch
  isolation, per-run pipeline directories, and pre-flight model checks.
version: 1.0.0
author: agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [software-development, multi-model, delegation, pipeline]
  requires_toolsets: [terminal, file, web]
  config:
    coding_model: qwen3-coder-next:q4_K_M
    coding_model_fallback: kimi-k2.7-code:cloud
    review_model: kimi-k2.7-code:cloud
    planning_model: deepseek-v4-pro:cloud
    test_model: kimi-k2.7-code:cloud
    max_plan_iterations: 2
    max_stage_retries: 1
---

# Multi-Model Dev Pipeline

Routes development work through 6 sequential/parallel stages, each dispatched
to a different LLM model via `delegate_task` per-task model overrides. The main
conversation model acts as orchestrator — it never does coding work itself.

Design document: `wiki/concepts/multi-model-dev-pipeline-design.md`
Design review: `/opt/data/pipeline-review/design-review.md`

## When to Load This Skill

Load this skill when the user asks to:
- "Build", "implement", or "develop" a feature, module, or service
- "Run the pipeline" or "use the dev pipeline"
- Describes a task spanning 3+ of the 6 stages (planning + coding + testing)

**Do NOT load for:**
- Quick bug fixes (single file, obvious cause)
- Research / analysis tasks (no code to write)
- Simple config changes or one-liner edits

## Model Assignments

| Stage | Model | Provider | Why |
|---|---|---|---|
| 1 Code Planning | `deepseek-v4-pro:cloud` | `ollama-glm` | Heavy reasoning, architecture |
| 2 Plan Review | `deepseek-v4-pro:cloud` | `ollama-glm` | Adversarial critique, gap finding |
| 3 Coding | `qwen3-coder-next:q4_K_M` | `ollama-glm` | Local, free, code-specialized |
| 4 Code Review | `kimi-k2.7-code:cloud` | `ollama-glm` | Code-specialized, read-only |
| 5 Test Planning | `deepseek-v4-pro:cloud` | `ollama-glm` | Test strategy = reasoning |
| 6 Test Execution | `kimi-k2.7-code:cloud` | `ollama-glm` | Run tests, fix failures |

**Fallback:** If `qwen3-coder-next:q4_K_M` is unavailable, Stage 3 falls back to
`kimi-k2.7-code:cloud`.

See `references/model-assignment.md` for rationale and swap instructions.

## Pipeline Stages

### Pre-flight (Orchestrator, before Stage 1)

```
1. Check git status — refuse if working tree is dirty
2. Run: python3 scripts/verify_models.py (check model availability)
3. Create per-run pipeline dir: <project_dir>/.hermes/pipeline/<run-id>/
4. Add .hermes/pipeline/ to .gitignore if not present
5. Create feature branch: hermes-pipeline/<run-id>-<slug>
6. Record the pipeline dir path and branch name for all stages
```

### Stage 1: Code Planning (DeepSeek)

```python
delegate_task(
    goal="<see references/stage-prompts.md Stage 1>",
    context="Project dir: <project_dir>. Pipeline dir: <pipeline_dir>. "
            "Task: <user's request>. Read relevant source files first.",
    model="deepseek-v4-pro:cloud",
    toolsets=["file", "web"]
)
# Output: <pipeline_dir>/plan.md
```

### Stage 2: Plan Review (DeepSeek, adversarial)

```python
delegate_task(
    goal="<see references/stage-prompts.md Stage 2 — adversarial review>",
    context="Read <pipeline_dir>/plan.md. Project dir: <project_dir>. "
            "Verify plan against actual codebase.",
    model="deepseek-v4-pro:cloud",
    toolsets=["file"]
)
# Output: <pipeline_dir>/review.md
# Check for BLOCKING_ISSUES marker → re-dispatch Stage 1 (max 2 iterations)
```

### Stage 3: Coding (Qwen, fallback: Kimi)

```python
delegate_task(
    goal="<see references/stage-prompts.md Stage 3>",
    context="Read <pipeline_dir>/plan.md and <pipeline_dir>/review.md. "
            "Project dir: <project_dir>. You are on branch: <branch_name>. "
            "DO NOT use execute_code — use terminal() for any commands.",
    model="qwen3-coder-next:q4_K_M",  # or kimi-k2.7-code:cloud if unavailable
    toolsets=["terminal", "file"]
)
# Output: code changes in <project_dir> on feature branch
#         <pipeline_dir>/code-changes.md (summary of files changed)
```

### Stages 4+5: Code Review + Test Planning (PARALLEL)

```python
delegate_task(tasks=[
    {
        # Stage 4: Code Review (Kimi, READ-ONLY)
        "goal": "<see references/stage-prompts.md Stage 4 — READ-ONLY>",
        "context": "Read <pipeline_dir>/plan.md. Review code in <project_dir>. "
                  "DO NOT modify project files. DO NOT use execute_code.",
        "model": "kimi-k2.7-code:cloud",
        "toolsets": ["terminal", "file"]
        # Output: <pipeline_dir>/code-review.md + <pipeline_dir>/review-fixes.patch
    },
    {
        # Stage 5: Test Planning (DeepSeek)
        "goal": "<see references/stage-prompts.md Stage 5>",
        "context": "Read <pipeline_dir>/plan.md and <pipeline_dir>/review.md. "
                  "Project dir: <project_dir>.",
        "model": "deepseek-v4-pro:cloud",
        "toolsets": ["file"]
        # Output: <pipeline_dir>/test-plan.md
    }
])
# Wait for both to complete, then proceed to Stage 5.5
```

### Stage 5.5: Apply Review Fixes (Orchestrator or Kimi subagent)

```python
# Orchestrator applies the patch from Stage 4:
# terminal("cd <project_dir> && git apply <pipeline_dir>/review-fixes.patch")
# If patch fails (conflicts), dispatch a Kimi subagent to resolve:
delegate_task(
    goal="Apply the review patch from <pipeline_dir>/review-fixes.patch "
         "manually. Resolve any conflicts. Commit the changes.",
    context="Project dir: <project_dir>. Patch file: <pipeline_dir>/review-fixes.patch. "
            "Review notes: <pipeline_dir>/code-review.md. DO NOT use execute_code.",
    model="kimi-k2.7-code:cloud",
    toolsets=["terminal", "file"]
)
```

### Stage 6: Test Execution (Kimi)

```python
delegate_task(
    goal="<see references/stage-prompts.md Stage 6>",
    context="Read <pipeline_dir>/test-plan.md. Project dir: <project_dir>. "
            "Run the test suite, fix any failing tests. "
            "DO NOT use execute_code — use terminal() for all commands.",
    model="kimi-k2.7-code:cloud",
    toolsets=["terminal", "file"]
)
# Output: <pipeline_dir>/test-results.md
```

### Post-pipeline (Orchestrator)

```
1. Read <pipeline_dir>/test-results.md
2. Check git diff on feature branch
3. Report summary to user:
   - Files changed
   - Tests passed/failed
   - Review findings applied
   - Pipeline artifact paths
4. Offer: merge feature branch to original branch, or reset (clean rollback)
```

## Per-Stage Failure Handling

Check `delegate_task` result for `status` and `exit_reason`:

| Failure | Action |
|---|---|
| `status: failed`, `exit_reason: max_iterations` | Re-dispatch with narrower goal (1 retry max) |
| `status: timeout` | Re-dispatch once; abort if second timeout |
| `status: error` | Report to user; retry once |
| `status: failed` (empty output) | Re-dispatch with tighter prompt (1 retry) |
| `status: interrupted` | Halt pipeline; offer branch reset |

## Critical Constraints

1. **DO NOT use `execute_code` in subagents.** It's blocked by
   `DELEGATE_BLOCKED_TOOLS`. Use `terminal()` for all shell commands and
   Python scripts (`python3 -c "..."`).

2. **Stage 4 is READ-ONLY.** It must not modify project files. It writes
   findings + a patch file only. Fixes are applied in Stage 5.5.

3. **All subagents share `delegation.provider`.** Per-task `model` only swaps
   the model name on the same provider's endpoint. All pipeline models must
   be available on `ollama-glm` (the Ollama proxy).

4. **No shared subagent context.** Each `delegate_task` child starts fresh.
   Context flows through files in `<pipeline_dir>/` only.

5. **`subagent_auto_approve: true`.** Subagents auto-approve dangerous
   commands (logged). Pipeline can run `rm`, `git reset`, etc. without user
   prompts. All such commands are logged with `logger.warning`.

## See Also

- `references/stage-prompts.md` — Full prompt contracts for each stage
- `references/model-assignment.md` — Model selection rationale and swap guide
- `scripts/verify_models.py` — Pre-flight model availability checker
- Design doc: `wiki/concepts/multi-model-dev-pipeline-design.md`