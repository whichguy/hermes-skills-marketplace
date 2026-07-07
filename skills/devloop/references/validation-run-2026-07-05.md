# Devloop Validation Run — 2026-07-05

## Context

After applying the 3-layer test quality defense (commit `1eb0de2`), we ran the
exact same `calendar-quick-add` request that had failed 5 consecutive times
before the fixes. The existing `nl-calendar-add` skill was renamed so devloop
would build fresh.

## Request

```
Build a Python skill called 'calendar-quick-add' for Hermes Agent that parses
natural language event descriptions into Google Calendar events via the gws CLI,
with 3-layer location fallback and dependency-injected functions. Uses only
stdlib + urllib. CLI: python3 calendar_quick_add.py 'lunch tomorrow 12pm at
Pizzaiolo' [--calendar primary] [--attendees a@b.com] [--duration 60]
[--no-reminder]. Include SKILL.md with Hermes frontmatter, known_places.json,
and tests. All functions should accept injectable dependencies (geocode_fn,
gws_runner as callable parameters) for testability. Use real datetime objects
in tests, not string literals.
```

## Results

| Metric | Before Fixes (5 rounds) | After Fixes (this run) |
|--------|------------------------|----------------------|
| Judge verdicts | 0/4 criteria trusted | **4/4 criteria trusted** |
| Quality lint gate | didn't exist | **ok=True** — no bad patterns |
| Implementation phase | never reached | **attempt 0, 1 file changed** |
| Evidence | never ran | **c1-c4 all pass** |
| Stop condition | HUMAN_REVIEW (test fault) | **DoD-SATISFIED** |
| Regression | never ran | **whole-suite green** |
| Rounds needed | 5 (all failed) | **1 round, 0 rebuilds** |

## Pipeline Trace

```
charter → ambiguity_gate (passed)
coverage → ok=True
quality_lint → ok=True          ← NEW: caught any bad patterns before judges
judge → all 4 criteria trusted  ← NEW: judge reason text fed back to designer
frozen_tests → ok
lint_discovery → ok
backoff → within caps
implement → attempt 0           ← first attempt succeeded
lint → ok=True
evidence → c1-c4 all pass
stop_check → DoD-SATISFIED
regression → whole-suite green
```

## Judge Verdicts

| Criterion | Judge A | Judge B | Encodes | Reason |
|-----------|---------|---------|---------|--------|
| c1 | True | True | True | both judges agree |
| c2 | True | True | True | both judges agree |
| c3 | True | True | True | both judges agree |
| c4 | True | True | True | both judges agree |

c4 was the criterion that failed every time before the fixes — the designer kept
generating string-literal datetime tests despite explicit ANSWERS to use real
datetime objects.

## Post-Completion Gates

- **Overfit audit**: Ran after stop_check (normal — post-completion verification)
- **Commit-scope gate**: Classified changed files as deliverable vs scratch

## Key Takeaways

1. **The 3-layer defense works end-to-end.** The quality lint gate catches bad
   patterns before the expensive judge round-trip. Judge reason text gives the
   redesigner actionable feedback. Designer prompt negative examples prevent
   bad patterns from being generated in the first place.

2. **The ANSWERS→designer gap was the root cause** of the 5-round failure.
   Without it, the designer never saw the user's explicit instruction to use
   real datetime objects.

3. **The `_lit()` datetime fix** was critical — without it, even correct test
   designs would render as string literals.

4. **Zero rebuilds, zero replans.** The first attempt succeeded. This is the
   target state for devloop — one round, verified, merged.

5. **The overfit auditor ran** as a post-completion check, confirming the
   implementation honestly encodes the criteria rather than special-casing
   to pass tests.
