# Three-Layer Test Quality Defense (2026-07-05)

Built from a 3-seat advisor panel (DeepSeek, Kimi, Minimax) reviewing the full
devloop codebase after a 5-round calendar-quick-add failure. Commit `1eb0de2`.

## Architecture

```
design → coverage → [QUALITY_LINT] → judges → implement
                         ↓                ↓
                   static patterns    reason text
                   (<100ms)           (~6min, but now
                                     feeds WHY back)
```

## Layer 1: Pre-Judge Static Gate (Kimi)

`test_quality_lint.py` — scans rendered test files with AST for 3 known-bad patterns:

| Pattern | Detection | Fix Hint |
|---------|-----------|----------|
| Module-level `mock.patch` | `ast.Call` with `func.attr == 'patch'` at module scope | Use dependency injection (callable parameter) |
| `Mock` without call inspection | `Mock(...)` with no `assert_called_with`/`call_args` in body | Add `assert mock.call_args[0][0] == expected` |
| Datetime string literal | String literal matching ISO date pattern in `assert` | Use `datetime(2026, 7, 6, 12, 0)` real object |

Wired into `loop.py` after coverage and before judges. 8 regression tests in
`tests/test_quality_lint.py`. Feedback includes `category` and `fix_hint` for
the redesigner.

## Layer 2: Render Output Regression Tests (DeepSeek)

9 new tests in `tests/test_render_more.py` pin the `_lit()` datetime fix and
mock assertion rendering:

- `test_render_datetime_expected_produces_real_object`
- `test_render_datetime_in_args_produces_real_object`
- `test_render_date_object_not_string`
- `test_render_datetime_in_list_renders_recursively`
- `test_render_timedelta_renders_as_real_object`
- `test_render_mock_assert_called_with_renders_correctly`
- `test_render_mock_assert_call_arg_renders_correctly`
- `test_render_mock_assert_called_once_renders`
- `test_render_datetime_header_auto_imported`

## Layer 3: Judge Reason Text (Minimax)

Judges now return `(bool, str)` instead of bare `bool`. The str is a one-sentence
reason extracted from the judge's second reply line.

Files changed:
- `dispatch.py`: judge prompt asks for reason text on NO; `_DESIGN_SPEC_PROMPT` has negative examples
- `dod_oracle.py`: `judge_assertions` returns `judge_a_reason`/`judge_b_reason` fields
- `runner.py`: `_redesign` threads judge reason text into designer feedback
- `loop.py`: trace includes judge reasons; `_design_spec` includes reasons
- `tests/test_dispatch.py`: updated for `(bool, str)` return type

Backward compatibility: `_unwrap()` normalizes bare `bool` → `(bool, "")`.

## Test Suite

118/118 tests pass (9 render + 9 render_more + 8 quality_lint + 4 dod_oracle
+ 56 dispatch/smoke/state/testgen/runner + 32 other).

## Advisor Contributions

| Seat | Model | Contribution |
|------|-------|-------------|
| Kimi | kimi-k2.7-code:cloud | Static gate + designer prompt negative examples + loop wiring |
| DeepSeek | deepseek-v4-pro:cloud | Render output regression tests (9 new) |
| Minimax | minimax-m3:cloud | Judge reason text extension + redesign threading |
