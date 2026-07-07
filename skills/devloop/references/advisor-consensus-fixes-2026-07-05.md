# Advisor Consensus: 6 Proposed Devloop Fixes (2026-07-05)

3-seat advisor panel (DeepSeek reasoner, Kimi coder, Minimax challenger) reviewed
6 proposed fixes for devloop based on learnings from the calendar-quick-add
validation run. Each advisor read the actual source files in
`/opt/data/skills/software-development/devloop/` before rendering verdicts.

## The 6 Fixes Under Review

| # | Fix | Root Cause |
|---|-----|------------|
| 1 | Auto-generate integration-tier criteria for CLI skills | Unit tests mocked gws_runner → wrong CLI syntax not caught |
| 2 | Charter decomposes artifact deliverables as criteria | "Include SKILL.md, known_places.json" → no criteria for those files |
| 3 | Post-implementation e2e dry-run gate | Evidence only runs pytest, never exercises real external tools |
| 4 | Quality lint flags weak substring assertions | `assert 'lunch' in cmd_str` passes even if command format is wrong |
| 5 | Progress stream includes timing/estimates | 11 min of progress markers but no timing |
| 6 | Parallelize commit scope with overfit audit | Two independent audits run sequentially |

## Consensus Verdicts

| Fix | DeepSeek | Minimax | Consensus |
|-----|----------|---------|-----------|
| 1 | MODIFIED — broaden tier rule, one-line prompt change | MODIFIED — don't hardcode `--dry-run`, let planner pick the flag | **MODIFIED** |
| 2 | MODIFIED — carve out exception in refine prompt for non-code files | MODIFIED — require CONTENT criteria not file-existence | **MODIFIED** |
| 3 | **AGAINST** — fragile heuristic, false positives, redundant with Fix 1 | **AGAINST** — implementation wasn't wrong, test expectation was wrong | **AGAINST** |
| 4 | MODIFIED — scope to command-runner mocks specifically | **FOR (P0!)** — highest leverage, catches exact failure mode | **FOR/MODIFIED** |
| 5 | FOR — trivial, 3-line change, high UX impact | MODIFIED — function already exists, just add elapsed time + roadmap | **FOR** |
| 6 | FOR (with caveat) — gate scope on overfit being clean | MODIFIED — just reorder scope before overfit, simpler than ThreadPool | **MODIFIED** |

## Key Insights

### Minimax's Reframing (the most important insight)

> "The implementation was never wrong; the test's expectation of the implementation
> was wrong. The real bug was in `assert 'lunch' in call_str` (Fix 4 territory),
> not in the implementation."

This means the e2e dry-run gate (Fix 3) would have failed on a **correct**
implementation because the TEST was the problem, not the code. The right fix is
at the test-design layer (Fix 4), not at the post-implementation verification
layer (Fix 3).

### DeepSeek's Architecture Insight

> "Fixes 1+4 together close the loop — Fix 1 ensures the real CLI gets exercised
> (integration criterion), and Fix 4 catches weak substring assertions at lint
> time so the test designer knows to write exact-match assertions."

### Why Devloop Can't Do E2E (Structural)

Devloop's entire verification pipeline is test-internal:

```
Implementation → lint → frozen-tests → evidence (pytest) → stop_check → regression (pytest)
```

`verify_cmd_for` in `testgen.py:104` always produces `pytest -q <node>`. There
is no mechanism to run a different command. The evidence phase literally runs
`pytest test_c3` — which imports the module, calls functions with mocked deps,
and checks substring assertions. The real external binary is never invoked.

The stop condition (`gate.stop_condition`) checks coverage + judge trust +
evidence pass. It has no concept of "does the code actually work in the real
world?"

## Recommended Implementation Order

| Order | Fix | Priority | Effort | Impact |
|-------|-----|----------|--------|--------|
| 1 | **Fix 4** — Quality lint weak substring assertions | **P0** | ~80 lines | Catches exact failure mode at lint time |
| 2 | **Fix 1 + Fix 2** — Integration criteria + artifact criteria | P1 | ~20 lines prompt | Prevention: charter produces right criteria |
| 3 | **Fix 5** — Progress timing | P1 | ~40 lines | UX: elapsed time + roadmap |
| 4 | **Fix 6** — Reorder scope before overfit | P2 | 1 line | Speed: saves ~18s |
| — | **Fix 3** — E2E dry-run gate | P3 | Defer | Redundant with Fix 1+4; fragile heuristic |

## Fix 3: Why Both Advisors Said AGAINST

1. **False negatives**: The implementation may call a runner function (like
   `gws_runner`) that wraps subprocess — a regex scan won't find it.
2. **False positives**: Any subprocess call (git, pytest, pip) would be flagged
   and dry-run'd, potentially with harmful side effects.
3. **`--dry-run` isn't universal**: Many CLIs don't support it, or use different
   flags (`-n`, `--check`, `--validate`).
4. **Redundant with Fix 1**: If the charter generates an integration-tier
   criterion that exercises the real binary, the evidence phase already runs it
   as a real subprocess. The integration criterion IS the e2e gate.
5. **Wrong layer**: The bug was in the test's expectation, not the implementation.
   Running the implementation through a dry-run subprocess doesn't help — the
   implementation was never wrong.

## Fix 4: The P0 Fix — Detailed Design

The existing `test_quality_lint.py` has 3 AST patterns. Pattern 4 should detect:

- A mock variable assigned to a name matching `*run*`/`*exec*`/`*call*`/`*cmd*`
- Assertions using `in` on that mock's `call_args[0][0]` (positional arg 0, element 0)
- Absence of any exact-match assertion (`==`) on the same call_args

A substring `in` check on a command string is a signal that the test author
doesn't know the exact command format — which is exactly when integration-tier
criteria are needed.

Minimax also recommended a 5th pattern: `Mock(return_value=..., side_effect=...)`
with no call_args inspection — a superset of the existing pattern 2 that catches
the calendar-quick-add failure mode where the test had a return_value but never
verified the call shape.
