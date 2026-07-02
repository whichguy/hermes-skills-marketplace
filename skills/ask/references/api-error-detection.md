# API Error Detection in Pipeline Output

## Problem

When the SDLC pipeline dispatches a model via `hermes chat -q`, the model
sometimes returns an API error message instead of code — HTTP 429 rate limits,
HTTP 500 server errors, or "monthly max reached" messages. The pipeline's
`extract_python_code()` would treat these as code and try to execute them,
producing confusing failures.

## Solution

### `is_api_error()` in `model_utils.py` (production code)

As of P1 (Jun 2026), `is_api_error()` lives in `scripts/model_utils.py` —
production code, not just the test file. `dispatch_single()` calls it after
`clean_output()` to detect API errors in model output and convert them to
proper error returns:

```python
def is_api_error(text: str) -> bool:
    """Check if model output is an API error, not code."""
    if not text:
        return False
    text_lower = text.lower()
    api_error_patterns = [
        "http 429",
        "http 500",
        "error code: 429",
        "error code: 500",
        "rate limit",
        "monthly max reached",
        "extra usage auto reload",
    ]
    return any(pattern in text_lower for pattern in api_error_patterns)
```

### Pipeline retry on transient errors

`run_pipeline()` in `pipeline.py` retries on transient API errors (429,
timeout, connection refused) with exponential backoff. The `max_retries`
parameter controls this (default: 1 retry).

### `extract_python_code()` guard (test file)

`extract_python_code()` in `test_pipeline_e2e.py` also calls `is_api_error()`
and returns `""` (empty string) when true, so the E2E test harness knows to
retry rather than execute the error message.

## Test Coverage

`TestApiErrorDetection` in `test_pipeline.py` (11 CI tests):

| Test | What it verifies |
|------|-----------------|
| `test_is_api_error_429` | HTTP 429 detected |
| `test_is_api_error_500` | HTTP 500 detected |
| `test_is_api_error_monthly_max` | "monthly max reached" detected |
| `test_is_api_error_normal_code` | Normal Python NOT flagged |
| `test_is_api_error_bare_number` | `x = 429` NOT flagged |
| `test_is_api_error_empty` | Empty string NOT flagged |
| `test_extract_python_code_api_error` | Returns `""` for API error |
| `test_extract_python_code_markdown` | Extracts from ```python block |
| `test_extract_python_code_generic` | Extracts from generic ``` block |
| `test_extract_python_code_bare` | Extracts bare Python |
| `test_extract_python_code_largest` | Returns largest of multiple blocks |

Additional P1 tests in `test_ask.py` verify `is_api_error()` in the
production module and pipeline retry behavior.

## Pitfalls

- **False positives are worse than false negatives.** The patterns are
  conservative — they only match clear API error strings. A code snippet
  containing the number 429 (e.g., `x = 429`) is NOT flagged because the
  patterns require surrounding error context ("HTTP 429", "error code: 429").
- **Don't add patterns for every possible error.** The goal is to catch the
  common cases (429, 500, monthly max). Adding too many patterns risks false
  positives on legitimate code.
- **`is_api_error()` is in `model_utils.py` (production), not just the test
  file.** `dispatch_single()` calls it after `clean_output()`. If you add
  patterns, both the production guard and the E2E test guard benefit.
