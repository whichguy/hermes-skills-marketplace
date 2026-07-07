# HUMAN_REVIEW Recovery Patterns

When devloop exits 2 (HUMAN_REVIEW), it means a gate blocked progress. The trace tells you exactly which gate and why. Here's how to diagnose and re-run.

## Quick Diagnosis

**Meta-pattern:** In practice, test design is the bottleneck — not implementation. Across multiple runs, every HUMAN_REVIEW exit was a test fault (judge-untrusted test), never an implementation failure. The implementation never even ran. Invest in precise ANSWERS about test structure before re-running; vague "fix the test" answers won't help.

```bash
# Read the trace to find the blocking reason
python3 -c "
import json
with open('devloop-traces/<name>/trace.jsonl') as f:
    for line in f:
        d = json.loads(line)
        if d.get('step') == 'terminal' and d.get('terminal') == 'HUMAN_REVIEW':
            print('REASON:', d.get('reason'))
        if d.get('step') == 'attribution':
            print('FAULT:', d.get('fault'), '→', d.get('criteria'))
        if d.get('step') == 'grounding':
            for c in d.get('criteria', []):
                judges = c.get('judges', {})
                if not judges.get('a') or not judges.get('b'):
                    print(f'  UNTRUSTED: {c[\"criterion_id\"]} — judge_a={judges.get(\"a\")} judge_b={judges.get(\"b\")}')
"
```

## Common Patterns

### 1. Test Fault — Judge-Untrusted Test (most common)

**Symptom:** `test fault: criteria ['cX'] have no judge-trusted test`

**Root cause:** One or both judges voted `false` on a criterion's test. The test exists but doesn't convincingly encode the criterion. The implementation never even ran — devloop exits before coding because the test design is the bottleneck.

**Core principle:** Judges reject tests that don't **prove the behavior happened**. A test that mocks at module level with `patch()` or returns fabricated object attributes without verifying what was *called* will fail. Judges want to see: (1) the function was invoked, (2) with the right arguments, (3) and the return value is correctly processed.

**Fix by pattern:**

| Pattern judges reject | Why | Fix |
|---|---|---|
| `patch('module.func')` at module level | Can't verify what actually happened inside | Dependency injection: pass callables as parameters |
| `Mock(return_value=obj_with_attrs)` | Doesn't verify the function *called* the mock correctly | Return plain strings; inspect `call_args[0][0]` |
| `assert result == 'datetime(2026,7,6)'` | String literal, not a real Python object | Use real `datetime` objects: `assert result == datetime(2026,7,6,12,0)` |
| `assert result.event_id == 'evt123'` | Object attribute on mock return — never verified the mock was called | `assert mock.call_count == 1` then inspect `mock.call_args[0][0]` |

**General ANSWERS template for test faults:**
- For CLI tests: split into c5a (argparse isolation) + c5b (orchestration with explicit dependency injection)
- Functions should accept injectable mock parameters (`geocode_fn=None`, `gws_runner=None`) instead of relying on `unittest.mock.patch` at module level
- The main function should default injectable params to real implementations
- For callable dependencies: the mock takes a single string argument and returns a plain string. Use `Mock(return_value='output\n')` and verify with `mock.call_args[0][0]`
- For datetime assertions: use real `datetime`/`date` objects, never string literals like `'datetime(2026,7,6)'`
- For return-value verification: extract from plain strings, not fabricated object attributes

**Example re-run commands:**

CLI + dependency injection:
```bash
devloop "<original request> — ANSWERS: For c5 CLI test: split into c5a tests CLI argument parsing in isolation, c5b tests orchestration with explicit dependency injection (pass mock geocode_fn and mock gws_runner as parameters to main, do NOT use patch at module level). The main function should accept optional geocode_fn and gws_runner parameters defaulting to the real implementations."
```

Callable dependency with string return:
```bash
devloop "<original request> — ANSWERS: For c4 create_calendar_event test: the gws_runner is a callable that takes a single string argument (the full gws CLI command) and returns a string (the raw gws stdout). The test must assert: (1) gws_runner was called exactly once, (2) the command string passed to gws_runner contains the title, start time, end time, location, and attendee emails, (3) when reminder_minutes=30 the command string contains '--reminder 30', (4) when reminder_minutes=0 the command string does NOT contain '--reminder'. Use mock_gws = Mock(return_value='evt123\n') and check mock_gws.call_args[0][0] to inspect the command string. Do NOT use object attributes on the return — gws_runner returns a plain string."
```

Datetime objects (not string literals):
```bash
devloop "<original request> — ANSWERS: For c1 parse_time_expression test: use REAL Python datetime objects, NOT string literals. Import from datetime import datetime, date. Pass reference_date as a real date object: reference_date=date(2026,7,5). Assert return values are real datetime objects: assert result[0] == datetime(2026,7,6,12,0,0). ALL assertions must compare against real datetime objects, never strings like 'datetime(2026,7,6)'."
```

### 2. Vague Goal — Unmeasurable Quality Target

**Symptom:** `vague goal: criterion references 'faster'/'cleaner'/'better' with no measurable target`

**Fix:** Add a concrete metric to the request: "must complete in under 2 seconds" or "must pass pylint with score ≥ 8.0".

### 3. Blocking Open Questions

**Symptom:** `ambiguity: blocking open questions remain`

**Fix:** Read the questions from the trace's charter, answer them in ANSWERS.

## Re-run Mechanics

- Every invoke is FRESH — append `— ANSWERS: <your answers>` to the original devloop command
- The trace from the failed run is preserved; the new run gets its own trace
- You can re-run as many times as needed; each is independent

## After Re-run

- Check `devloop-traces/<name>/trace.jsonl` for the new run's outcome
- If it COMPLETEs, the code is merged (or kept on branch with `--keep-branch`)
- If it HUMAN_REVIEWs again, read the new trace — it's a different issue
