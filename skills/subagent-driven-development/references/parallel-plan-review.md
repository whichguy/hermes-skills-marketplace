# Parallel Plan Review Pattern

## When to Use

When you have a complete implementation plan and want thorough review before execution. Dispatch two reviewers in parallel — each examines the plan from a different angle:

| Reviewer | Focus | What It Catches |
|---|---|---|
| **Kimi** (`kimi-k2.7-code:cloud`) | Code/debug review | Wrong line numbers, missing imports, API signature mismatches, edge cases, concrete bugs in code snippets |
| **DeepSeek Pro** (`deepseek-v4-pro:cloud`) | Architecture/design review | Middleware ordering, race conditions, Block Kit validity, dispatch routing, design soundness |

## Why Parallel

- Kimi and DeepSeek review **different things** — no overlap, no dependency
- Running sequentially doubles wall-clock time for no benefit
- Both reviews land at roughly the same time, giving a complete picture in one pass

## Dispatch Pattern

```python
delegate_task(tasks=[
    {
        "goal": "Review the implementation plan from a code/debug perspective",
        "model": "kimi-k2.7-code:cloud",
        "context": """## Your Role
You are Kimi K2.7 Code — the debug + code review model. Find CONCRETE issues by cross-referencing the plan against actual source code.

## What to Review
The plan is at {plan_path}.

## Source Files to Cross-Reference
- {list of files the plan references}

## Specific Things to Verify
1. Line numbers in the plan match actual source files
2. Import paths are correct
3. API signatures match (connect(), middleware, etc.)
4. Functions/methods called actually exist
5. Edge cases not covered by the plan
6. Missing imports in proposed code snippets

## Output
Add a section to the plan file with: issue table (severity, location, fix), missing imports, wrong line numbers, API mismatches, edge cases, verdict.""",
        "toolsets": ["terminal", "file"],
    },
    {
        "goal": "Review the implementation plan from an architecture/design perspective",
        "model": "deepseek-v4-pro:cloud",
        "context": """## Your Role
You are DeepSeek V4 Pro — the design review and plan verification model. Validate the architecture, catch design flaws, and verify the approach will actually work.

## What to Review
The plan is at {plan_path}.

## Design Questions to Validate
1. Will the core approach actually work in production?
2. Are there race conditions or ordering issues?
3. Is the middleware/event routing correct?
4. Are there double-patching or idempotency risks?
5. Does the dispatch routing create loops or wrong contexts?
6. Are the Block Kit / API types valid?

## Output
Add a section to the plan file with: architecture validation, design risks ranked by severity, specific corrections, verdict.""",
        "toolsets": ["terminal", "file"],
    },
])
```

## Context Requirements

Each reviewer needs:
- **The plan file path** — they read it themselves (don't inline 800 lines of plan text)
- **Source file paths** — the actual code the plan references, so they can cross-reference
- **Specific verification checklist** — don't just say "review the plan"; give concrete things to check
- **Output format** — tell them to append their findings as a new section to the plan file

## After Reviews Land

1. Read both review sections from the plan file
2. Present a consolidated summary to the user
3. Fix critical/high issues before execution
4. Re-dispatch if major architectural changes are needed

## Pitfalls

- **Don't inline the plan text** — subagents have file tools; let them read the plan themselves. Inlining 800+ lines of plan text bloats the dispatch context.
- **Don't give both reviewers the same instructions** — they'll produce overlapping reviews. Give each a distinct focus area.
- **Don't skip the verification checklist** — generic "review the plan" instructions produce generic reviews. Be specific about what to check.
- **Kimi reviews CODE, DeepSeek reviews DESIGN** — don't swap their roles. Kimi is better at concrete code issues; DeepSeek is better at architectural reasoning.
- **Both reviewers should write to the plan file** — this keeps findings in one place and avoids context pollution in the controller session.
