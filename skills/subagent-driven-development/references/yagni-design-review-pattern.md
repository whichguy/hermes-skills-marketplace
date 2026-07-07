# YAGNI Design Review Pattern

## When to Use

When the user asks for a YAGNI (You Aren't Gonna Need It) simplification analysis of an
existing codebase — "is this overbuilt?", "what should we cut?", "deeply consider over
design and plan out if there is a better method of simplification."

## The Pattern

### Phase 1: Write the Analysis (Controller)

The controller writes a thorough YAGNI analysis document covering:
- What the codebase actually does vs what it was designed to do
- Per-component assessment: lines, purpose, whether it's on the critical path
- What's genuinely needed vs what's gold-plating
- A radical simplification option (what if we rewrote from scratch?)
- A middle-path recommendation

Save to `.hermes/plans/YYYY-MM-DD-yagni-simplification-analysis.md`.

### Phase 2: DeepSeek Review (Critical — Do Not Skip)

**The controller's analysis WILL contain errors.** The controller works from memory and
file-size estimates, not from actual codebase verification. DeepSeek catches:
- Conflated components (e.g., treating a warning-only helper as the same as a real lock mechanism)
- Overestimated line counts (counting "lines in file" as "lines safely removable")
- Hidden dependencies (imports, test suites, SKILL.md references that make deletion harder)
- False claims about what "doesn't exist" (e.g., claiming NL intake doesn't exist when tests prove it does)
- Protective code misidentified as dead code

```python
# Set delegation model to DeepSeek
terminal("hermes config set delegation.model deepseek-v4-pro:cloud")

# Dispatch DeepSeek with the analysis + all key source files
delegate_task(
    goal="Review the YAGNI simplification analysis against the actual codebase",
    context="""Read the full YAGNI analysis at [path], then read the actual source files.
For each pruning recommendation, assess: agree/disagree, hidden risks, line count accuracy,
hidden dependencies, and middle grounds. Also assess the radical rewrite option and the
reduction target realism.""",
    toolsets=['terminal', 'file']
)

# Switch back to Kimi after
terminal("hermes config set delegation.model kimi-k2.7-code:cloud")
```

### Phase 3: Incorporate Corrections

DeepSeek's review will typically find 2-3 significant errors. Incorporate them into a
revised plan. The most common errors:

1. **Conflating protective code with dead code** — a warning-only helper ≠ the real lock mechanism
2. **Claiming a feature "doesn't exist"** — check test files, not just production code
3. **Overestimating removable lines** — "lines in file" ≠ "lines safely removable" due to hidden coupling
4. **Missing hidden dependencies** — setup scripts, webhook handlers, compound test files

### Phase 4: Present the Corrected Plan

Present the DeepSeek-corrected plan to the user with:
- Where DeepSeek agreed (safe deletions)
- Where DeepSeek disagreed (my analysis was wrong, and why)
- Hidden dependencies I missed
- Realistic reduction numbers (typically 30-35%, not 50%)

## Pitfalls

- **Don't skip the DeepSeek review.** The controller's analysis is always optimistic about
  what can be cut. DeepSeek's codebase-level verification catches concrete errors.
- **Don't conflate components.** A `_add_lock_validation` warning-only helper is NOT the same
  as the `lock_row`/`unlock_row` pessimistic locking mechanism. Read the code, not just the names.
- **Check test files for feature existence.** If `test_nl_intent.py` exists and passes, the
  NL intake path exists — even if the controller claims it doesn't.
- **The config cache staleness pitfall applies.** `hermes config set delegation.model` doesn't
  take effect mid-session. Always verify the subagent's result message header to confirm
  which model actually ran.
