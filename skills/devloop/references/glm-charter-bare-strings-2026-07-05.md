# GLM-5.2 Charter Bare-String Bug — 2026-07-05

## Symptom

```
devloop NEEDS YOUR INPUT — invalid Charter: ['open_questions[0] is not an object']
```

Devloop exits with HUMAN_REVIEW at the ambiguity gate, even when the request is
well-specified and the planner produced a valid-looking charter.

## Root Cause

The planner model (GLM-5.2:cloud) sometimes returns `open_questions` and `assumptions`
as lists of **strings** instead of the expected dict shape.

**Expected (per the charter prompt):**
```json
{
  "open_questions": [
    {"text": "Should the script support multiple calendars?", "blocking": false}
  ],
  "assumptions": [
    {"text": "Uses Open-Meteo free API", "confidence": 0.9}
  ]
}
```

**What GLM-5.2 sometimes returns:**
```json
{
  "open_questions": [
    "Should the script support multiple calendars?"
  ],
  "assumptions": [
    "Uses Open-Meteo free API"
  ]
}
```

## Error Chain

1. GLM-5.2 generates charter JSON with bare-string elements
2. `_extract_json()` in `dispatch.py:300` parses it successfully (valid JSON)
3. `_wrap_charter()` in `dispatch.py:315` passes `open_questions` and `assumptions` through unchanged
4. `validate_charter()` in `state.py:128` iterates elements and checks `isinstance(x, dict)`:
   ```python
   errs += [f"{k}[{i}] is not an object" for i, x in enumerate(charter[k])
            if not isinstance(x, dict)]
   ```
5. Bare strings fail the `isinstance(x, dict)` check → `"open_questions[0] is not an object"`
6. `ambiguity_gate()` in `gate.py` sees non-empty errors → HUMAN_REVIEW

## Why No Trace

The trace at `devloop-traces/<name>/` only has a `finalize` event — the charter
failed at the very first gate before any trace events were written. The planner's
raw output wasn't captured because `DEVLOOP_DEBUG=1` wasn't set (it captures full
prompts/replies only in debug mode).

## Fix Location

`dispatch.py:_wrap_charter()` — add coercion before returning:

```python
def _coerce_qa(items, default_keys):
    """Coerce bare strings to dict objects for open_questions/assumptions."""
    result = []
    for item in (items or []):
        if isinstance(item, str):
            entry = dict(default_keys)
            entry["text"] = item
            result.append(entry)
        elif isinstance(item, dict):
            result.append(item)
    return result

# In _wrap_charter:
"assumptions": _coerce_qa(data.get("assumptions", []), {"confidence": 0.7}),
"open_questions": _coerce_qa(data.get("open_questions", []), {"blocking": False}),
```

This normalizes:
- `"open_questions": ["some question"]` → `[{"text": "some question", "blocking": false}]`
- `"assumptions": ["some assumption"]` → `[{"text": "some assumption", "confidence": 0.7}]`

## Reproduction

```bash
DEVLOOP_DEBUG=1 devloop "build a travel-weather skill..." --repo /path/to/repo
# Then check devloop-traces/<name>/dispatch/ for the planner's raw JSON
```

## Related

- Same pattern as the ANSWERS→designer fix (2026-07-05): the wrapper should coerce
  common LLM slips rather than rejecting them.
- The refiner (kimi-k2.7-code:cloud) may also produce bare strings — the coercion
  in `_wrap_charter` catches both paths since both go through it.
