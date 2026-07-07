# SDLC Inline Status Emission — Implementation Plan

> **Status:** Draft v2 — reviewed by Kimi (kimi-k2.7-code:cloud), pending DeepSeek review  
> **Date:** 2026-06-28  
> **Author:** Controller (GLM-5.2), reviewed by Kimi  
> **Files:** `model_utils.py`, `sdlc.py`, `pipeline.py` (all under `skills/productivity/ask/scripts/`)

## Problem

The SDLC pipeline has 3 layers, all blocking and silent during execution:

1. **`model_utils.py`** — `dispatch_single()` runs `hermes chat -q` as a blocking subprocess, captures all stdout+stderr, returns a dict. No callback hook. When called as a library (by sdlc.py), per-dispatch status (model name, elapsed, success) is lost.

2. **`sdlc.py`** — `run_test_first_pipeline()` runs 9 sequential phases (plan → design_tests → implement → run_tests → debug_cascade → tech_docs → simplify → tech_docs → council_review). Each phase calls `dispatch_single()`. No phase-level status is emitted between phases. The entire pipeline takes 3-10+ minutes with zero output.

3. **`sdlc.py` CLI** `main()` — prints a `┌─├─└─` summary tree AFTER the entire pipeline completes. No streaming.

**Result:** The controller (Hermes agent) dispatches the pipeline via `execute_code`, which blocks until completion and returns all output as a blob. The user sees nothing for 3-10 minutes.

## Design: 3 Layers, ~100 Lines Total

### Layer 1: `model_utils.py` — `progress_callback` on `dispatch_single()` (~20 lines)

Add optional `progress_callback: Callable = None` parameter to `dispatch_single()`.

**Typed event schema** (Kimi recommendation — TypedDict, not raw dict):

```python
from typing import Callable, TypedDict, Optional

class DispatchEvent(TypedDict, total=False):
    event: str          # 'dispatch_start' | 'dispatch_end'
    model: str
    role: Optional[str]
    thinking: Optional[str]
    elapsed: float
    success: bool
    chars: int
    error: Optional[str]
    phase: str          # set by sdlc.py when forwarding
    message: str        # human-readable summary
    timestamp: float
```

**Callback invocation** (wrapped in try/except — Kimi #4):

```python
def _safe_callback(cb, event_dict):
    """Invoke callback, swallow exceptions so pipeline never crashes."""
    if cb:
        try:
            cb(event_dict)
        except Exception as e:
            print(f"Warning: progress_callback raised: {e}", file=sys.stderr)
```

In `dispatch_single()`:
- Before subprocess.run: `_safe_callback(progress_callback, {'event': 'dispatch_start', 'model': model, 'role': role, 'thinking': thinking or 'default', 'timestamp': time.time()})`
- After subprocess.run (success or failure): `_safe_callback(progress_callback, {'event': 'dispatch_end', 'model': model, 'elapsed': elapsed, 'success': content is not None, 'chars': len(content) if content else 0, 'error': error})`

**Also plumb through `dispatch_comparison()`** (Kimi #2 concern):
- Both calls inside `dispatch_comparison()` (sequential path at ~line 797, parallel path at ~line 810) need `progress_callback=None` added as keyword arg to `dispatch_single()` calls.

**Zero overhead when None (default).** All existing callers unaffected.

### Layer 2: `sdlc.py` — phase-level `_emit()` calls (~50 lines)

#### Phase metadata dict:

```python
PHASE_INFO = {
    'plan':            {'num': 1, 'label': 'Plan',           'model': 'GLM',        'icon': '📋'},
    'design_tests':    {'num': 2, 'label': 'Design Tests',    'model': 'DeepSeek',    'icon': '🧪'},
    'implement':       {'num': 3, 'label': 'Implement',       'model': 'Qwen-coder',  'icon': '🔨'},
    'run_tests':       {'num': 4, 'label': 'Run Test Suites', 'model': 'pytest',     'icon': '⚡'},
    'debug':           {'num': 5, 'label': 'Debug Cascade',   'model': 'Qwen→Kimi',   'icon': '🔧'},
    'tech_docs_1':     {'num': 6, 'label': 'Tech-Docs',       'model': 'Qwen',       'icon': '📝'},
    'simplify':        {'num': 7, 'label': 'Simplify',       'model': 'Kimi',       'icon': '✨'},
    'tech_docs_2':     {'num': 8, 'label': 'Tech-Docs',       'model': 'Qwen',       'icon': '📝'},
    'council':         {'num': 9, 'label': 'Council Review',  'model': '3 models',   'icon': '🏛️'},
}
```

#### Emit helper:

```python
def _emit(callback, event, phase, **extra):
    """Emit a structured progress event if callback is set."""
    if callback:
        try:
            callback({'event': event, 'phase': phase, **PHASE_INFO.get(phase, {}), **extra})
        except Exception:
            pass  # Never let callback crash the pipeline
```

#### Each phase function accepts `progress_callback=None`:

Pattern for every phase function (`plan`, `design_test_suites`, `implement`, `tech_docs`, `simplify_code`):

```python
def plan(message, timeout=120, toolsets='file,web', progress_callback=None):
    _emit(progress_callback, 'phase_start', 'plan')
    result = dispatch_single(
        model=resolve_alias('planner'),
        progress_callback=progress_callback,  # forwards per-dispatch events
        # ...existing args...
    )
    _emit(progress_callback, 'phase_end', 'plan',
          elapsed=result.get('elapsed', 0),
          success=bool(result.get('content')))
    return result
```

#### Special phases (Kimi #1 — single event, not per-dispatch):

**`run_test_suites()`** — emits per-suite events (Kimi #9.3):

```python
def run_test_suites(code, test_suites, progress_callback=None):
    _emit(progress_callback, 'phase_start', 'run_tests')
    results = []
    for suite_config in TEST_SUITES:
        suite_name = suite_config['name']
        _emit(progress_callback, 'suite_start', 'run_tests', suite=suite_name)
        # ...existing run_tests call...
        _emit(progress_callback, 'suite_end', 'run_tests', 
              suite=suite_name, passed=result['passed'])
        results.append(result)
        if not result['passed']:
            break
    _emit(progress_callback, 'phase_end', 'run_tests',
          elapsed=sum(r.get('elapsed', 0) for r in results if isinstance(r, dict)),
          success=all(r.get('passed', True) for r in results))
    return results
```

**`debug_cascade()`** — one start/end event, winning_model in end (Kimi #1):

```python
def debug_cascade(message, code=None, error_feedback=None, ..., progress_callback=None):
    _emit(progress_callback, 'phase_start', 'debug')
    # ...existing cascade logic...
    _emit(progress_callback, 'phase_end', 'debug',
          elapsed=elapsed, success=cascade_succeeded,
          winning_model=winning_model)
    return result
```

**`council_review()`** — one start/end, NO per-seat callbacks (Kimi #1, #6):

```python
def council_review(message, code, plan_output, test_results, ..., progress_callback=None):
    _emit(progress_callback, 'phase_start', 'council', seat_count=len(COUNCIL_PANEL))
    # ...existing parallel dispatch (NO callback forwarded to _dispatch_seat)...
    _emit(progress_callback, 'phase_end', 'council',
          elapsed=elapsed, seat_count=seat_count, success=seat_count > 0)
```

#### `run_test_first_pipeline()` — pipeline-level events + early-return coverage (Kimi #9.8):

```python
def run_test_first_pipeline(message, timeout=120, ..., progress_callback=None):
    _emit(progress_callback, 'pipeline_start', 'plan', message_preview=message[:80])
    
    # Phase 1: Plan
    _emit(progress_callback, 'phase_start', 'plan')
    plan_result = plan(message, timeout=timeout, progress_callback=progress_callback)
    _emit(progress_callback, 'phase_end', 'plan', ...)
    
    if not plan_result.get('content'):
        _emit(progress_callback, 'pipeline_failed', 'plan', reason='Plan phase failed')
        return {...}  # existing early return
    
    # Phase 2: Design tests
    _emit(progress_callback, 'phase_start', 'design_tests')
    test_result = design_test_suites(..., progress_callback=progress_callback)
    _emit(progress_callback, 'phase_end', 'design_tests', ...)
    
    if not test_result.get('content'):
        _emit(progress_callback, 'pipeline_failed', 'design_tests', reason='Test design failed')
        return {...}  # existing early return
    
    # ... same pattern for implement, run_tests, debug, tech_docs, simplify, tech_docs, council ...
    
    _emit(progress_callback, 'pipeline_complete', 'council',
          total_elapsed=elapsed, status=pipeline_status)
    return {...}
```

**Critical (Kimi #9.8):** Every early-return path MUST emit `pipeline_failed` before returning. There are 4 early returns: `plan_failed`, `test_design_failed`, `implement_failed`, `debug_failed`.

### Layer 3: `sdlc.py` CLI — locked `_stderr_callback` + `--quiet` flag (~30 lines)

```python
import threading

_stderr_lock = threading.Lock()

def _stderr_callback(event):
    """Default callback: print [SDLC] lines to stderr. Thread-safe."""
    evt = event.get('event', '')
    phase = event.get('phase', '')
    info = PHASE_INFO.get(phase, {})
    num = info.get('num', '')
    label = info.get('label', '')
    model = info.get('model', '')
    icon = info.get('icon', '')
    
    if evt == 'pipeline_start':
        line = f"[SDLC] pipeline_start: {event.get('message_preview', '')}"
    elif evt == 'phase_start':
        line = f"[SDLC] phase_start: {num}. {label} ({model})"
    elif evt == 'phase_end':
        elapsed = event.get('elapsed', 0)
        ok = '✅' if event.get('success') else '❌'
        extra = f" → {event['winning_model']}" if event.get('winning_model') else ''
        line = f"[SDLC] phase_end: {num}. {label} {ok} ({elapsed:.1f}s){extra}"
    elif evt == 'suite_start':
        line = f"[SDLC] suite_start: {event.get('suite', '')}"
    elif evt == 'suite_end':
        ok = '✅' if event.get('passed') else '❌'
        line = f"[SDLC] suite_end: {event.get('suite', '')} {ok}"
    elif evt == 'pipeline_complete':
        line = f"[SDLC] pipeline_complete: {event.get('status', '')} ({event.get('total_elapsed', 0):.1f}s total)"
    elif evt == 'pipeline_failed':
        line = f"[SDLC] pipeline_failed: {event.get('reason', '')}"
    else:
        return
    
    with _stderr_lock:
        print(line, file=sys.stderr, flush=True)
```

**CLI `main()` changes:**

```python
parser.add_argument('--quiet', action='store_true',
                    help='Suppress [SDLC] status lines on stderr')
# ...existing args...

result = run_test_first_pipeline(
    args.message, timeout=args.timeout,
    progress_callback=None if args.quiet else _stderr_callback,
)
```

**Controller usage:**

```python
# Controller dispatches sdlc.py as background terminal with watch patterns
terminal(
    command='python3 /opt/data/skills/productivity/ask/scripts/sdlc.py '
            '"Build a palindrome checker" --json 2>&1',
    background=True,
    notify_on_complete=True,
    watch_patterns=[
        r'\[SDLC\] phase_start:',
        r'\[SDLC\] phase_end:',
        r'\[SDLC\] pipeline_complete:',
        r'\[SDLC\] pipeline_failed:',
    ]
)
```

Each `[SDLC]` line triggers a watch pattern notification → controller reports inline.

## Test Mock Safety Analysis (Kimi #3)

**Finding:** Tests use `@patch("...dispatch_single")` with `mock_dispatch.return_value = {...}` and extract kwargs via `mock_dispatch.call_args`. No positional lambdas found. Adding `progress_callback=None` as a keyword-only parameter is safe — existing mocks don't reference it, and `**kwargs` patterns won't break.

**Specific patterns found:**
- `test_pipeline.py:75` — `_fake_dispatch()` returns a canned dict, used via `@patch("pipeline.dispatch_single", return_value=_fake_dispatch())`
- `test_sdlc.py:29` — `_fake_dispatch()` returns canned dict, used via `@patch("sdlc.dispatch_single")`
- `test_ask.py:264+` — `@patch("ask.dispatch_single")` with `mock_dispatch.return_value = {...}`, asserts on `mock_dispatch.call_args`
- All tests check kwargs via `.call_args.kwargs` or `.call_args[1]` — adding a new kwarg doesn't break these

**Risk: LOW.** No positional lambda mocks exist.

## Implementation Order (Kimi's 9 Steps)

1. Add `progress_callback` to `model_utils.dispatch_single` with TypedDict + `_safe_callback` wrapper
2. Plumb through `model_utils.dispatch_comparison` (both sequential + parallel paths)
3. Add `PHASE_INFO` dict and `_emit()` helper to `sdlc.py`
4. Wire each phase function to accept `progress_callback` and emit start/end events
5. Wire `run_test_suites` to emit suite-level events (suite_start/suite_end)
6. Wire `debug_cascade` to emit single phase_start/phase_end with winning_model
7. Wire `council_review` to emit single phase_start/phase_end (no per-seat)
8. Add `pipeline_start`/`pipeline_failed`/`pipeline_complete` to `run_test_first_pipeline` with all early-return coverage
9. Add locked `_stderr_callback` default in `sdlc.py` `main()` + `--quiet` flag
10. Write tests for callback events (mock callback, assert expected events fire)
11. Run the 306-test suite (`uv run --with pytest python3 -m pytest tests/ -v -k "not live"`)

## Event Contract

| Event | When | Fields |
|---|---|---|
| `pipeline_start` | Pipeline begins | phase, message_preview, timestamp |
| `phase_start` | Phase function begins | phase, num, label, model, icon |
| `dispatch_start` | dispatch_single begins (from L1) | model, role, thinking, timestamp |
| `dispatch_end` | dispatch_single ends (from L1) | model, elapsed, success, chars, error |
| `suite_start` | Test suite begins | phase, suite |
| `suite_end` | Test suite ends | phase, suite, passed |
| `phase_end` | Phase function ends | phase, num, label, model, elapsed, success |
| `pipeline_complete` | All phases done | phase, status, total_elapsed |
| `pipeline_failed` | Early return on failure | phase, reason |

## What Does NOT Change

- `hermes chat -q` is still a blocking subprocess — we can't stream model token output
- `ask.py` does NOT get the callback (Kimi #7 — YAGNI, it has its own badge printing)
- `pipeline.py` passes through `progress_callback` if set, but doesn't add its own (the controller calls sdlc.py CLI, not pipeline.py directly, for SDLC work)
- Phase logic, prompts, model selection, test execution — all unchanged
- All existing function signatures remain backward-compatible (new params default to None)

## Deferred (Nice-to-Have, Not Blockers)

- `--events-file` flag: writes JSON-lines event log to a file (robust alternative to watch_patterns rate limits)
- Event contract documentation (markdown doc listing event types + fields)
- ask.py callback plumbing (when a programmatic caller needs it)
- Per-seat council events (if someone wants per-model visibility in the council phase)

## Review History

| Reviewer | Model | Date | Verdict | Key Issues |
|---|---|---|---|---|
| Kimi | kimi-k2.7-code:cloud | 2026-06-28 | Architecture sound, ship with fixes | Thread lock, dispatch_comparison plumbing, test mocks, early-return coverage, --quiet flag, callback exception handling |
| DeepSeek | deepseek-v4-pro:cloud | 2026-06-28 | Pending | — |