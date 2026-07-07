# Pre-Judge Static Gate — 2026-07-05

## What

`test_quality_lint.py` — a static analysis gate that runs BEFORE the expensive
judge round-trip in devloop. Catches 3 known-bad test patterns in under 1 second
instead of burning a 6-minute judge round-trip.

## Patterns Caught

| Pattern | Detection | Feedback |
|---------|-----------|----------|
| Module-level `mock.patch` | AST: `with mock.patch(...)` at module scope | "Use dependency injection (callable params) instead of module-level mock.patch" |
| `Mock` without call inspection | AST: `Mock(return_value=...)` with no `assert_called`/`call_args` | "Add assert_called_once() or call_args inspection to verify what was passed" |
| Datetime string literal | AST: string literal matching datetime pattern in assert | "Use real datetime objects: `datetime(2026, 7, 6, 12, 0)` not `'2026-07-06T12:00'`" |

## Wiring

- **File:** `test_quality_lint.py` (156 lines, in devloop root)
- **Tests:** `tests/test_quality_lint.py` (8 tests, all pass with `--import-mode=importlib`)
- **Loop insertion:** `loop.py` — after coverage gate, before judges
- **Prompt hardening:** `dispatch.py` `_DESIGN_SPEC_PROMPT` — negative examples for all 3 patterns

## Architecture Decision (3-Advisor Consensus)

All 3 advisors (DeepSeek, Kimi, MiniMax) agreed: a static gate is the right approach,
not schema extension. The gate catches known patterns deterministically; judges handle
novel patterns. This is the "investigator layer" — pre-judge, not post-judge.

## Remaining Gap

Judges return only boolean votes. When they reject a test for a NOVEL pattern
(one the static gate doesn't catch), the redesigner gets "both judges rejected"
with no explanation. Adding `judge_reason` text to the verdict dict is the next
bottleneck — see the `devloop` skill's "Redesign path doesn't incorporate judge
feedback" pitfall.

## Test Results

```
17 passed in 0.02s
- 9 render tests (test_render_more.py)
- 8 quality lint tests (test_quality_lint.py)
```

Run: `pytest tests/test_quality_lint.py tests/test_render_more.py -v --import-mode=importlib`
