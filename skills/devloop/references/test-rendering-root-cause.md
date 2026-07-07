# Test-Rendering Root Cause Analysis

**Date:** 2026-07-05
**Session:** calendar-quick-add build (5 devloop rounds, all HUMAN_REVIEW)
**Outcome:** Skill built directly after devloop couldn't reach implementation phase

## The Failure Pattern

5 consecutive devloop runs on the same request. ALL 5 exited HUMAN_REVIEW with "test fault" —
judges rejected the generated tests, NOT the implementation. devloop never reached the
IMPLEMENT phase in any run.

## Root Causes (Code-Level)

### 1. ANSWERS Never Reach the Test Designer

**File:** `scripts/devloop_cli.py` line 71, `dispatch.py` line 603

The CLI appends `— ANSWERS: ...` to the request string. This flows to the charter/ambiguity
gate. But `designer_spec_via_ask()` (dispatch.py ~line 603) only receives the DoD criteria —
it NEVER sees the ANSWERS. The designer generates tests independently from the criteria alone.

**Consequence:** When we answered "use real datetime objects not string literals," the designer
kept generating string-literal tests because it never saw our answer. This persisted across
3+ rounds with the same answer.

**Fix needed:** Pass prior-run feedback (ANSWERS or judge verdicts) to the designer as
additional context. The designer prompt should include: "Previous attempts used these test
patterns and judges rejected them: [patterns]. Do NOT repeat these patterns."

### 2. Structured Mode Can't Express Dependency Injection

**File:** `render.py` — `_render_case()` and `_mock_with()`

The structured test spec mode supports:
- `{module, call, cases: [{args, kwargs, expected/raises}], mocks: [{target, return_value}]}`
- Renders as `assert func(args) == expected` with optional `mock.patch()` wrappers

Judges consistently reject `mock.patch()` because:
- It patches at module level — can't verify what was actually passed to the mock
- Can't express `mock.call_args[0][0]` inspection (verify the command string)
- Can't express dependency injection (passing callables as parameters)

**Fix needed:** Extend the structured spec to support:
- `inject: {param_name: mock_value}` — renders as `func(arg, gws_runner=mock_fn)`
- `verify_call: {mock_name, expected_args}` — renders as `assert mock_fn.call_args[0][0] == expected`

### 3. Raw Escape Hatch Exists But Designer Rarely Uses It

**File:** `render.py` — `_render_entry()` oracle="raw" path

The raw escape hatch (`{criterion_id, oracle: "raw", raw_test: "def test_cX(): ..."}`) exists
and works correctly. But the designer LLM defaults to structured mode and rarely uses raw mode
even when the criterion clearly needs it (CLI integration, dependency injection, call_args
inspection).

**Fix needed:** Add guidance to `_DESIGN_SPEC_PROMPT` (dispatch.py ~line 580):
- When the function under test accepts callable parameters → use raw mode with dependency injection
- When the test needs to verify what was passed to a mock → use raw mode with call_args inspection
- When the criterion is integration-tier (CLI, real modules) → use raw mode

### 4. Test Redesign Path Doesn't Incorporate Feedback

**File:** `loop.py` lines 370-415

The test redesign path (triggered when judges reject tests) regenerates the oracle but doesn't
pass the judge verdicts or prior ANSWERS to the designer. The designer starts fresh each time,
producing the same patterns judges already rejected.

**Fix needed:** Pass judge verdicts (which tests were rejected and why) as context to the
redesign call. The designer should see: "These tests were rejected: c1 (string literals instead
of datetime objects), c4 (mock.patch instead of dependency injection). Do NOT repeat these patterns."

## Round-by-Round Progression

| Round | Blocked Criteria | Pattern | Root Cause |
|-------|-----------------|---------|------------|
| 1 | c5 (CLI orchestration) | `patch('sys.stdout', ...)` | Structured mode limitation (#2) |
| 2 | c4 (calendar create) | Object attribute mock | Structured mode limitation (#2) |
| 3 | c1, c4, c10 | String literals, personal emails | ANSWERS not reaching designer (#1) |
| 4 | c1 | STILL string literals | ANSWERS not reaching designer (#1) |
| 5 | c6 (CLI main) | Likely patch() again | All 4 root causes |

Round 5 was the closest — c1-c5 and c7 all passed both judges. Only c6 (CLI integration) failed.

## The 3 Patterns Judges Consistently Reject

| Pattern | Why Rejected | Correct Approach |
|---------|-------------|-----------------|
| `patch('module.func')` at module level | Can't verify what happened inside | Dependency injection: pass callables as parameters |
| `Mock(return_value=obj_with_attrs)` | Doesn't verify the function *called* the mock | Return plain strings; inspect `call_args[0][0]` |
| `assert result == 'datetime(2026,7,6)'` | String literal, not a real Python object | Use real `datetime` objects |

## Recovery Pattern

When devloop produces the same test fault across 3+ rounds despite explicit ANSWERS:

1. **Stop re-running devloop.** The ANSWERS aren't reaching the designer.
2. **Extract the DoD criteria** from the last run's charter (they're usually correct).
3. **Write the tests yourself** using the patterns judges accept (DI, call_args, real objects).
4. **Implement against those tests.**
5. **Verify with `pytest`.**
6. **Commit with THESIS/LEARNINGS** documenting the devloop rounds and why direct build was the right fallback.

## Proposed Code Fixes (for future devloop improvement)

See the advisor dispatch results (when they land) for specific patches. The four fixes are:

1. **dispatch.py** — Feed ANSWERS/prior feedback to `designer_spec_via_ask()`
2. **render.py** — Add `inject` and `verify_call` to structured spec
3. **dispatch.py `_DESIGN_SPEC_PROMPT`** — Add guidance: when to use raw mode
4. **loop.py redesign path** — Pass judge verdicts to redesign call
