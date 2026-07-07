# SDLC Inline Status Emission — Implementation Plan

> **Status:** Draft v4 — reviewed by DeepSeek (deepseek-v4-pro:cloud), Kimi fixes integrated, Controller re-review complete
> **Date:** 2026-06-28
> **Author:** Controller (GLM-5.2), reviewed by Kimi, re-reviewed by DeepSeek, final review by Controller
> **Files:** `model_utils.py`, `sdlc.py`, `pipeline.py` (all under `skills/productivity/ask/scripts/`)

## Problem

The SDLC pipeline has 3 layers, all blocking and silent during execution:

1. **`model_utils.py`** — `dispatch_single()` runs `hermes chat -q` as a blocking subprocess, captures all stdout+stderr, returns a dict. No callback hook. When called as a library (by sdlc.py), per-dispatch status (model name, elapsed, success) is lost.

2. **`sdlc.py`** — `run_test_first_pipeline()` runs 9 sequential phases (plan → design_tests → implement → run_tests → debug_cascade → tech_docs → simplify → tech_docs → council_review). Each phase calls `dispatch_single()`. No phase-level status is emitted between phases. The entire pipeline takes 3-10+ minutes with zero output.

3. **`sdlc.py` CLI** `main()` — prints a `┌─├─└─` summary tree AFTER the entire pipeline completes. No streaming.

**Result:** The controller (Hermes agent) dispatches the pipeline via `execute_code`, which blocks until completion and returns all output as a blob. The user sees nothing for 3-10 minutes.

## Design: 3 Layers, ~110 Lines Total

### Layer 1: `model_utils.py` — `progress_callback` on `dispatch_single()` (~25 lines)

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

**`_safe_callback` helper** — defined in `model_utils.py` (module-level, used by `dispatch_single`):

```python
def _safe_callback(cb, event_dict):
    """Invoke callback, swallow exceptions so pipeline never crashes."""
    if cb:
        try:
            cb(event_dict)
        except Exception as e:
            print(f"Warning: progress_callback raised: {e}", file=sys.stderr)
```

**`dispatch_single()` signature change** — add `progress_callback` as the LAST parameter (after `role`):

```python
def dispatch_single(model: str, prompt: str, context: str, toolsets: str,
                    max_turns: int, timeout: int, provider: str,
                    output_file: Optional[str] = None, resume_session: Optional[str] = None,
                    alias: Optional[str] = None, thinking: Optional[str] = None,
                    english_only: bool = False, role: Optional[str] = None,
                    progress_callback: Optional[Callable] = None) -> dict:
```

In `dispatch_single()`:
- Before subprocess.run (line ~646): `_safe_callback(progress_callback, {'event': 'dispatch_start', 'model': model, 'role': role, 'thinking': thinking or 'default', 'timestamp': time.time()})`
- After subprocess.run success (line ~719, before return): `_safe_callback(progress_callback, {'event': 'dispatch_end', 'model': model, 'elapsed': elapsed, 'success': True, 'chars': len(content), 'error': None})`
- In each error/exception return path (TimeoutExpired at ~726, Exception at ~733, empty output at ~694, API error at ~686): `_safe_callback(progress_callback, {'event': 'dispatch_end', 'model': model, 'elapsed': elapsed, 'success': False, 'chars': 0, 'error': error_msg})`

**Also plumb through `dispatch_comparison()`** (Kimi #2 concern):
- Sequential path at line 797: add `progress_callback=None` as keyword arg to `dispatch_single()` call
- Parallel path at line 808: add `progress_callback=None` as keyword arg in `pool.submit()` call
  - `pool.submit(dispatch_single, model, prompt, context, toolsets, max_turns, timeout, provider, None, None, None, None, progress_callback=None)`
  - NOTE: `ThreadPoolExecutor.submit(fn, *args, **kwargs)` supports keyword args, so this works

**Zero overhead when None (default).** All existing callers unaffected.

### Layer 2: `sdlc.py` — phase-level `_emit()` calls (~55 lines)

**Add `import threading`** to sdlc.py imports (line ~63). Currently sdlc.py does NOT import threading, but `_stderr_lock = threading.Lock()` requires it.

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

**`run_test_suites()`** — emits per-suite events (Kimi #9.3). NOTE: `run_test_suites()` (line 446) currently does NOT accept `progress_callback`. Add it:

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

#### `run_test_first_pipeline()` — pipeline-level events ONLY + early-return coverage (Kimi #9.8, DEEPSEEK FIX):

**CRITICAL FIX (DeepSeek):** The pipeline function must NOT emit `phase_start`/`phase_end` — those are emitted by the individual phase functions. The pipeline only emits `pipeline_start`, `pipeline_failed`, and `pipeline_complete`. Emitting both would double-emit every phase event.

```python
def run_test_first_pipeline(message, timeout=120, ..., progress_callback=None):
    _emit(progress_callback, 'pipeline_start', 'plan', message_preview=message[:80])
    
    # Phase 1: Plan
    plan_result = plan(message, timeout=timeout, progress_callback=progress_callback)
    
    if not plan_result.get('content'):
        _emit(progress_callback, 'pipeline_failed', 'plan', reason='Plan phase failed')
        return {...}  # existing early return
    
    # Phase 2: Design tests
    test_result = design_test_suites(message, plan_result['content'],
                                     timeout=timeout, progress_callback=progress_callback)
    
    if not test_result.get('content') or test_result.get('error'):
        _emit(progress_callback, 'pipeline_failed', 'design_tests', reason='Test design failed')
        return {...}  # existing early return
    
    # Phase 3: Implement
    code_result = implement(message, plan_result['content'], test_result['content'],
                            timeout=timeout, progress_callback=progress_callback)
    
    if not code_result.get('content') or code_result.get('error'):
        _emit(progress_callback, 'pipeline_failed', 'implement', reason='Implement phase failed')
        return {...}  # existing early return (line 1084-1092)
    
    # ... code extraction logic (unchanged) ...
    
    if not extracted_code:
        _emit(progress_callback, 'pipeline_failed', 'implement',
              reason='No extractable code from implement phase')
        return {...}  # existing early return (line 1110-1118)
    
    # Phase 4-5: Run tests + debug cascade (if verification enabled)
    # ... existing logic, pass progress_callback to run_test_suites and debug_cascade ...
    
    # NOTE: debug_failed and tests_failed are NOT early returns — they set
    # pipeline_status but continue to docs/council phases. No pipeline_failed
    # emission needed here (the phase functions already emitted their failures).
    
    # Phases 6-8: Tech-docs → Simplify → Tech-docs
    # ... pass progress_callback to tech_docs(), simplify_code() ...
    
    # Phase 9: Council review
    # ... pass progress_callback to council_review() ...
    
    _emit(progress_callback, 'pipeline_complete', 'council',
          total_elapsed=elapsed, status=pipeline_status)
    return {...}
```

**Early return inventory (verified against source at lines 1057-1232):**

| Return point | `return` line | Status | Emit required |
|---|---|---|---|
| plan_failed | 1055 | Early return | `pipeline_failed` |
| test_design_failed | 1064 | Early return | `pipeline_failed` |
| implement_failed (no content) | 1080 | Early return | `pipeline_failed` |
| implement_failed (no extractable code) | 1106 | Early return | `pipeline_failed` |
| debug_failed | 1139 | NOT early return — sets status, continues | None (phase already emitted) |
| tests_failed | 1142 | NOT early return — sets status, continues | None (phase already emitted) |

**Total: 4 early returns requiring `pipeline_failed` emission.** (Not 4 including debug_failed as the original plan claimed.)

### Layer 3: `sdlc.py` CLI — locked `_stderr_callback` + `--quiet` flag (~35 lines)

```python
import threading  # ADD to sdlc.py imports (line ~63)

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
    elif evt == 'dispatch_start':
        # DEEPSEEK ADDITION: Handle dispatch events forwarded from model_utils.
        # These are intentionally terse — phase_start/phase_end already provide
        # the high-level summary. Dispatch events add per-model detail.
        line = f"[SDLC] dispatch_start: {event.get('model', '?')} (thinking={event.get('thinking', 'default')})"
    elif evt == 'dispatch_end':
        ok = '✅' if event.get('success') else '❌'
        line = f"[SDLC] dispatch_end: {event.get('model', '?')} {ok} ({event.get('elapsed', 0):.1f}s, {event.get('chars', 0)} chars)"
    else:
        return  # Unknown event type — silently ignore
    
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

**Regex note:** `\[SDLC\]` correctly escapes the literal brackets. Without escaping, `[SDLC]` would be interpreted as a character class matching any single character from the set {S, D, L, C}.

## Test Mock Safety Analysis (Kimi #3, DeepSeek verified)

**Finding:** Tests use `@patch("...dispatch_single")` with `mock_dispatch.return_value = {...}` and extract kwargs via `mock_dispatch.call_args`. No positional lambdas found. Adding `progress_callback=None` as a keyword-only parameter is safe — existing mocks don't reference it, and `**kwargs` patterns won't break.

**Specific patterns found (verified against source):**
- `test_sdlc.py:71` — `@patch("sdlc.dispatch_single")` with `mock_dispatch.return_value = _fake_dispatch(...)`. Asserts on `mock_dispatch.call_args.kwargs` (line 150, 163, 173, 329, 341). Adding `progress_callback` as a new kwarg doesn't break these — they check specific keys like `role`, `prompt`, not the full kwargs dict.
- `test_sdlc.py:192-198` — Mocks phase functions directly (`@patch("sdlc.plan")`, etc.), not `dispatch_single`. Unaffected.
- `test_pipeline.py:163-164` — `@patch("pipeline.dispatch_single")` with `mock_dispatch.return_value = _fake_dispatch()`. Asserts on `mock_dispatch.call_args.kwargs` (line 260-266, 276-277, etc.). Safe.
- `test_ask.py:230` — `@patch("model_utils.subprocess.run")` — mocks subprocess, not dispatch_single. Unaffected.
- `test_ask.py:264` — `@patch("ask.dispatch_single")` — mocks ask.py's wrapper, not model_utils directly. Unaffected.

**Risk: LOW.** No positional lambda mocks exist. All tests use `call_args.kwargs` for specific key checks.

## Implementation Order (Updated — 11 Steps)

1. Add `progress_callback` to `model_utils.dispatch_single` with TypedDict + `_safe_callback` wrapper
2. Plumb through `model_utils.dispatch_comparison` (both sequential at line 797 + parallel at line 808)
3. Add `import threading` to `sdlc.py` (required for `_stderr_lock`)
4. Add `PHASE_INFO` dict and `_emit()` helper to `sdlc.py`
5. Wire each phase function to accept `progress_callback` and emit start/end events:
   - `plan()`, `design_test_suites()`, `implement()`, `tech_docs()`, `simplify_code()`
6. Wire `run_test_suites()` to accept `progress_callback` and emit suite-level events (suite_start/suite_end)
7. Wire `debug_cascade()` to accept `progress_callback` and emit single phase_start/phase_end with winning_model
8. Wire `council_review()` to accept `progress_callback` and emit single phase_start/phase_end (no per-seat)
9. Add `pipeline_start`/`pipeline_failed`/`pipeline_complete` to `run_test_first_pipeline` with all 4 early-return coverage (NOT phase_start/phase_end — those come from phase functions)
10. Add locked `_stderr_callback` default in `sdlc.py` `main()` + `--quiet` flag (include dispatch_start/dispatch_end handling)
11. Write tests for callback events (mock callback, assert expected events fire) + run the full test suite

## Event Contract

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `pipeline_start` | Pipeline begins | `run_test_first_pipeline` | phase, message_preview, timestamp |
| `phase_start` | Phase function begins | Each phase function | phase, num, label, model, icon |
| `dispatch_start` | dispatch_single begins | `model_utils.dispatch_single` | model, role, thinking, timestamp |
| `dispatch_end` | dispatch_single ends | `model_utils.dispatch_single` | model, elapsed, success, chars, error |
| `suite_start` | Test suite begins | `run_test_suites` | phase, suite |
| `suite_end` | Test suite ends | `run_test_suites` | phase, suite, passed |
| `phase_end` | Phase function ends | Each phase function | phase, num, label, model, elapsed, success |
| `pipeline_complete` | All phases done | `run_test_first_pipeline` | phase, status, total_elapsed |
| `pipeline_failed` | Early return on failure | `run_test_first_pipeline` | phase, reason |

**Event flow for a successful pipeline:**
```
pipeline_start
  phase_start: plan
    dispatch_start (GLM)
    dispatch_end (GLM)
  phase_end: plan
  phase_start: design_tests
    dispatch_start (DeepSeek)
    dispatch_end (DeepSeek)
  phase_end: design_tests
  ... (implement, run_tests with suite_start/suite_end, debug if needed, docs×2, simplify, council)
pipeline_complete
```

## What Does NOT Change

- `hermes chat -q` is still a blocking subprocess — we can't stream model token output
- `ask.py` does NOT get the callback (Kimi #7 — YAGNI, it has its own badge printing)
- `pipeline.py` does NOT add its own callback plumbing (the controller calls sdlc.py CLI, not pipeline.py directly, for SDLC work). If a future programmatic caller needs `progress_callback` through `pipeline.run_pipeline()` → `run_sdlc_build()`, that's a separate change.
- Phase logic, prompts, model selection, test execution — all unchanged
- All existing function signatures remain backward-compatible (new params default to None)

## Deferred (Nice-to-Have, Not Blockers)

- `--events-file` flag: writes JSON-lines event log to a file (robust alternative to watch_patterns rate limits)
- Event contract documentation (markdown doc listing event types + fields)
- `ask.py` callback plumbing (when a programmatic caller needs it)
- Per-seat council events (if someone wants per-model visibility in the council phase)
- `pipeline.py` `progress_callback` pass-through (for programmatic callers of `run_pipeline()`)

## Review History

| Reviewer | Model | Date | Verdict | Key Issues |
|---|---|---|---|---|
| Kimi | kimi-k2.7-code:cloud | 2026-06-28 | Architecture sound, ship with fixes | Thread lock, dispatch_comparison plumbing, test mocks, early-return coverage, --quiet flag, callback exception handling |
| DeepSeek | deepseek-v4-pro:cloud | 2026-06-28 | Ship with fixes below | Double-emission bug (pipeline emitted phase_start/phase_end redundantly), early-return count wrong (debug_failed is NOT an early return), missing `import threading` in sdlc.py, `_stderr_callback` missing dispatch_start/dispatch_end handlers, `_safe_callback` location unspecified, `dispatch_comparison` line numbers off by 2, test plan underspecified |
| Controller | deepseek-v4-pro:cloud | 2026-06-28 | Ship with fixes below (v4) | See Controller Review Findings section below |

---

# SDLC Intelligent Orchestrator Extension

> **Status:** Design v2 — reviewed by Controller (deepseek-v4-pro:cloud)
> **Date:** 2026-06-28
> **Author:** Controller (GLM-5.2), Kimi synthesis, Controller re-review
> **Files:** `model_utils.py`, `sdlc.py` (all under `skills/productivity/ask/scripts/`)

## Problem

The current SDLC pipeline is a **linear, fire-and-forget chain**:
- Each phase calls `dispatch_single()` once via `hermes chat -q`
- The subagent response is consumed only for its `content` field
- The orchestrator cannot read a response and say *"this plan is too thin — add error handling"*
- `model_utils.py` already captures and saves `session_id`, but `sdlc.py` never passes `resume_session` or `alias`, so every phase starts a fresh session

The user wants the SDLC orchestrator to act as an intelligent agent: read subagent responses, decide whether they are good enough, and **continue the same session** with targeted feedback when they are not.

## Goals

1. **Session continuity per phase** — each phase keeps its own session alive for follow-up rounds
2. **Response evaluation** — the orchestrator inspects each phase result and decides *proceed* vs. *retry with feedback*
3. **Conditional re-interaction** — only loop back when the response is actually insufficient
4. **Context preservation** — follow-up prompts resume the same `hermes chat` session, so the model retains the full prior conversation
5. **Status transparency** — new events report each evaluation round and the retry decision
6. **Backward compatibility** — existing callers and tests are unaffected when results are already good

## Session Lifecycle Model

**Decision: per-phase sessions, not one global pipeline session.**

Rationale:
- Different phases use different models (GLM planner → DeepSeek test-planner → Qwen coder → Kimi reviewer)
- A planner session should not leak implementation details into the test-designer session
- Within a single phase, follow-ups should resume the same session so the model has full context of what it already produced

**Aliases:**

```python
PHASE_ALIASES = {
    'plan':          '__sdlc_plan',
    'design_tests':  '__sdlc_design_tests',
    'implement':     '__sdlc_implement',
    'tech_docs_1':   '__sdlc_tech_docs_1',
    'simplify':      '__sdlc_simplify',
    'tech_docs_2':   '__sdlc_tech_docs_2',
    'debug':         '__sdlc_debug',
    'council':       '__sdlc_council',
}
```

**CONTROLLER FIX: `__sdlc_` prefix** — The original plan used `sdlc-` prefix which shares the flat `~/.hermes/ask-sessions.json` namespace with user aliases from `ask.py`. A user could create an alias called `sdlc-plan` and collide. The `__sdlc_` prefix (double-underscore convention) signals "internal/system-managed" and is extremely unlikely to collide with user-chosen aliases. If stronger isolation is needed in the future, a separate `~/.hermes/sdlc-sessions.json` file can be introduced.

**Lifecycle rules:**
- Round 1 of a phase starts a **fresh** session (ignore any stale alias from a previous pipeline run)
- If the response is insufficient, round 2+ resumes the saved session for that alias
- After each successful dispatch, the returned `session_id` is saved under the phase alias
- Sessions auto-expire via the existing `SESSION_TTL = 3600` in `model_utils.py`
- A new pipeline run always starts fresh — it never resumes another pipeline's sessions

**CONTROLLER FIX: Session cleanup on pipeline start** — Before starting the pipeline, call `_cleanup_sdlc_sessions()` which removes all `__sdlc_*` entries from the session registry. This prevents stale entries from a crashed previous pipeline from interfering with the new run. Implementation:

```python
def _cleanup_sdlc_sessions():
    """Remove all __sdlc_* session entries before starting a new pipeline."""
    if not os.path.exists(SESSIONS_FILE):
        return
    try:
        with open(SESSIONS_FILE) as f:
            registry = json.load(f)
    except (json.JSONDecodeError, IOError):
        return
    removed = [k for k in registry if k.startswith('__sdlc_')]
    for k in removed:
        del registry[k]
    if removed:
        tmp_path = SESSIONS_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(registry, f, indent=2)
        os.replace(tmp_path, SESSIONS_FILE)
```

Call this at the top of `run_test_first_pipeline()` before Phase 1.

**CONTROLLER NOTE: Concurrent pipeline safety** — Two simultaneous SDLC pipelines would share the same `__sdlc_*` session entries, causing cross-pipeline session contamination. This is a known limitation. The session registry has no locking. Mitigations for future consideration: (a) include a pipeline UUID in the alias key, (b) use a separate session file per pipeline run, (c) document that only one SDLC pipeline should run at a time. For now, this is acceptable — the controller dispatches pipelines sequentially.

**CONTROLLER NOTE: TTL expiry mid-pipeline** — If a pipeline runs longer than `SESSION_TTL` (3600s = 1 hour), session entries could theoretically expire. In practice, `clean_expired_sessions()` is only called from `ask.py` CLI, not from `sdlc.py`, so TTL is not enforced during pipeline execution. Even if a session expires on the Hermes server side, `dispatch_single()` already has a fallback (line 662): if `--resume` fails with "Session not found", it retries fresh and cleans up the stale alias entry. This is sufficient.

## Evaluation Loop Pattern

**Decision: heuristic/rule-based evaluator first, with a swappable evaluator interface for future model-based evaluation.**

The orchestrator needs concrete *directives* for when to loop back. A rule-based evaluator is predictable, fast, and sufficient for the obvious failure modes:
- Empty / API-error / refusal content
- Too short / missing required structure
- Missing artifacts (code block, SUITE markers, P0/P1 markers)
- Failure to parse into expected downstream format

A model-based evaluator can be plugged in later by passing a different callable.

**Evaluator interface:**

```python
EvaluatorFn = Callable[[dict, int], Optional[str]]
# Input: dispatch result dict, round number
# Output: None → proceed; str → retry with this feedback text
```

**CONTROLLER FIX: Evaluator exception safety** — The evaluator call in `dispatch_with_evaluation` MUST be wrapped in try/except. If an evaluator raises (e.g., regex error on malformed content), the phase should treat it as "proceed" (best-effort) rather than crashing the entire pipeline:

```python
try:
    feedback = evaluator(result, round_num)
except Exception as e:
    _emit(progress_callback, 'feedback_end', phase, round=round_num,
          decision='proceed', reason=f'Evaluator error (proceeding): {str(e)[:120]}')
    return result  # Best-effort: proceed with the result
```

**Wrapper function:**

```python
def dispatch_with_evaluation(
    phase: str,
    prompt: str,
    context: str,
    model: str,
    toolsets: str,
    max_turns: int,
    timeout: int,
    provider: str,
    thinking: Optional[str] = None,
    role: Optional[str] = None,
    english_only: bool = False,
    evaluator: Optional[EvaluatorFn] = None,
    max_rounds: int = MAX_PHASE_ROUNDS,
    alias: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """Dispatch a model call with evaluation-driven follow-up loop."""
```

**Loop logic (pseudo-code):**

```python
evaluator = evaluator or evaluate_generic
alias = alias or PHASE_ALIASES.get(phase)
last_result = None

for round_num in range(1, max_rounds + 1):
    _emit(progress_callback, 'phase_round_start', phase, round=round_num, total_rounds=max_rounds)

    # Only resume after round 1
    session_id = None
    if round_num > 1 and alias:
        session_info = get_session(alias)
        session_id = session_info.get('session_id') if session_info else None

    # Wrap callback to inject round/phase into dispatch events
    def _dispatch_callback(event):
        event['phase'] = phase
        event['round'] = round_num
        _safe_callback(progress_callback, event)

    result = dispatch_single(
        model=model, prompt=prompt, context=context, toolsets=toolsets,
        max_turns=max_turns, timeout=timeout, provider=provider,
        thinking=thinking, role=role, english_only=english_only,
        resume_session=session_id, alias=alias,
        progress_callback=_dispatch_callback,
    )
    last_result = result

    _emit(progress_callback, 'phase_round_end', phase, round=round_num,
         success=bool(result.get('content')), elapsed=result.get('elapsed', 0))

    # Evaluate (with exception safety)
    _emit(progress_callback, 'feedback_start', phase, round=round_num)
    try:
        feedback = evaluator(result, round_num)
    except Exception as e:
        _emit(progress_callback, 'feedback_end', phase, round=round_num,
              decision='proceed', reason=f'Evaluator error: {str(e)[:120]}')
        return result

    _emit(progress_callback, 'feedback_end', phase, round=round_num,
         decision='proceed' if feedback is None else 'retry',
         reason=(feedback or '')[:120])

    if feedback is None:
        return result

    # CONTROLLER FIX: max_rounds=1 edge case
    # If max_rounds=1 and evaluator returned feedback, we can't retry.
    # Mark the result as evaluation_failed so the pipeline can handle it.
    if round_num >= max_rounds:
        last_result['evaluation_failed'] = True
        last_result['evaluation_feedback'] = (
            f"Max evaluation rounds ({max_rounds}) exceeded with feedback: {feedback[:200]}"
        )
        return last_result

    # Prepare concise follow-up prompt for next round
    prompt = (
        f"The previous response needs revision: {feedback}\n\n"
        f"Please revise your previous response accordingly. "
        f"Preserve what is correct and fix only the issues noted."
    )

# Max rounds exceeded (should not reach here due to the check above, but defensive)
last_result['evaluation_failed'] = True
last_result['evaluation_feedback'] = "Max evaluation rounds exceeded; returning best attempt."
return last_result
```

## Max Iteration Policy

**Decision: `MAX_PHASE_ROUNDS = 3`** (initial attempt + up to 2 follow-ups). This mirrors the existing `debug_cascade` `max_attempts=2` pattern and keeps local-model context windows bounded.

- Configurable per call via the `max_rounds` parameter
- If max rounds are exceeded, the phase returns the last result with `evaluation_failed=True`
- For phases 1-3 (plan, design_tests, implement), `evaluation_failed` is treated as a pipeline failure
- For phases 6-8 (tech_docs, simplify, tech_docs) and council, the pipeline may continue with the best-effort output

**CONTROLLER FIX: max_rounds=1 edge case** — When `max_rounds=1` and the evaluator returns feedback, the loop now correctly sets `evaluation_failed=True` before returning. Previously, the loop would exit without setting this flag, causing the pipeline to treat a known-bad result as success.

**Context window math (CONTROLLER ADDITION):**

| Round | Prompt tokens | Response tokens | Cumulative session tokens |
|---|---|---|---|
| 1 | ~2,000 | ~2,000 | ~4,000 |
| 2 | ~200 (feedback) | ~2,000 | ~6,200 |
| 3 | ~200 (feedback) | ~2,000 | ~8,400 |

Worst case with 3 rounds: ~8,400 tokens per phase. Well within any model's context window (32K minimum for local models, 128K+ for cloud models). No summarization needed at `MAX_PHASE_ROUNDS=3`.

**Interaction with debug_cascade budget (CONTROLLER ADDITION):**

The evaluation loop and debug cascade are complementary, not nested:
- Evaluation loop: pre-test quality gate (catches bad output before pytest)
- Debug cascade: post-test repair loop (runs after pytest reports failures)

Worst-case model calls for the implement phase: `max_phase_rounds` (3) + `debug_attempts` (2) = 5 total model calls. This is acceptable — they run sequentially, not nested.

## Orchestrator Directives (Quality Gate Criteria)

**Generic gate** (`evaluate_generic`):

```python
def evaluate_generic(result: dict, round_num: int) -> Optional[str]:
    """Generic quality gate: check for basic response validity."""
    content = result.get('content', '')
    error = result.get('error')

    if error:
        return f"Dispatch error: {error[:200]}"
    if not content or len(content.strip()) < 10:
        return "Response is empty or too short. Please provide a complete response."
    if is_api_error(content):
        return "Response appears to be an API error. Please try again."

    # Refusal patterns
    refusal_patterns = [
        r"\bI can't\b", r"\bI don't know\b", r"\bI'm not able\b",
        r"\bas an AI\b", r"\bI cannot\b", r"\bI won't\b",
    ]
    for pattern in refusal_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Response contains refusal language ('{pattern}'). Please provide the requested output."

    if len(content.strip()) < 50:
        return f"Response is too short ({len(content.strip())} chars). Please provide a more detailed response."

    return None  # Proceed
```

**CONTROLLER FIX: `evaluate_generic` signature** — The original plan had `evaluate_generic(result, phase, round_num)` with 3 parameters, but `EvaluatorFn` is `Callable[[dict, int], Optional[str]]` (2 parameters). Fixed to `evaluate_generic(result, round_num)`. Phase-specific context is handled by the phase-specific evaluators.

**Phase-specific gates:**

| Phase | Evaluator function | Required artifact | Quality signal |
|---|---|---|---|
| `plan` | `evaluate_plan` | Structured plan | Contains numbered/sectioned items; length ≥ 200 chars; names concrete files/functions |
| `design_tests` | `evaluate_design_tests` | Multiple suites | `parse_test_suites()` returns ≥ 1 suite; all required suite scopes present |
| `implement` | `evaluate_implement` | Python code | `extract_python_code()` returns valid block ≥ 50 chars |
| `tech_docs` | `evaluate_tech_docs` | Documented code | `extract_python_code()` returns valid block |
| `simplify` | `evaluate_simplify` | Simplified code | `extract_python_code()` returns valid block |
| `council` | `evaluate_council` | Review text | At least 2 seats responded; merged content is non-empty |

**CONTROLLER FIX: Added `evaluate_council`** — The original plan listed council quality criteria in the table but never defined the evaluator. Added:

```python
def evaluate_council(result: dict, round_num: int) -> Optional[str]:
    """Council-specific gate: check quorum and content quality."""
    # First run generic checks
    generic_feedback = evaluate_generic(result, round_num)
    if generic_feedback:
        return generic_feedback

    seat_count = result.get('seat_count', 0)
    total_seats = result.get('total_seats', len(COUNCIL_PANEL))

    if seat_count < 2:
        return f"Only {seat_count}/{total_seats} council seats responded. Need at least 2 for quorum."

    content = result.get('content', '')
    if 'NO IMPROVEMENTS NEEDED' not in content.upper():
        # Check that the review actually contains P0/P1 items or substantive feedback
        if len(content.strip()) < 100:
            return "Council review is too brief. Please provide detailed P0/P1 analysis."

    return None
```

**PHASE_EVALUATORS mapping (CONTROLLER ADDITION — missing from original plan):**

```python
PHASE_EVALUATORS = {
    'plan': evaluate_plan,
    'design_tests': evaluate_design_tests,
    'implement': evaluate_implement,
    'tech_docs_1': evaluate_tech_docs,
    'simplify': evaluate_simplify,
    'tech_docs_2': evaluate_tech_docs,
    'council': evaluate_council,
}
```

**Feedback text examples:**
- Plan: *"Plan is too brief. Expand with specific files/functions to reuse and concrete corner cases."*
- Design tests: *"Missing integration and E2E suites. Output all three suites as separate ```python blocks preceded by # SUITE: <name>."*
- Implement: *"No valid Python code block found. Output the complete implementation in a single ```python block."*
- Tech docs: *"Output must be the full documented code in a ```python block, not a summary."*

## Integration with Existing Pipeline

**Phases that benefit from the evaluation loop:**
- `plan()`
- `design_test_suites()`
- `implement()`
- `tech_docs()` (both pass 1 and pass 2)
- `simplify_code()`
- `council_review()` (CONTROLLER ADDITION: now has `evaluate_council`)

**Phases left unchanged or lightly changed:**
- `run_test_suites()` — no model calls; already emits suite events in v3
- `debug_cascade()` — already has its own retry/cascade loop; will be updated only to save session under `__sdlc_debug` alias so cascade attempts share context (already partially supports `prev_session_id`)

**Relationship to debug cascade:**
- The evaluation loop is a **pre-test quality gate** — it catches bad output before any pytest run
- The debug cascade is a **post-test repair loop** — it runs after pytest reports failures
- They are complementary, not replacements for each other

## New / Extended Event Types

Extend the v3 event contract with these events:

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `phase_round_start` | Each evaluation round begins | `dispatch_with_evaluation` | phase, round, total_rounds |
| `phase_round_end` | Each evaluation round ends | `dispatch_with_evaluation` | phase, round, total_rounds, success, elapsed |
| `feedback_start` | Evaluator begins | `dispatch_with_evaluation` | phase, round |
| `feedback_end` | Evaluator decides | `dispatch_with_evaluation` | phase, round, decision (`proceed`/`retry`/`failed`), reason |

The existing `dispatch_start` / `dispatch_end` events from `model_utils.py` are enriched with `phase` and `round` by the wrapper before forwarding to the caller's callback.

**Example event flow for a phase with one retry:**
```
phase_start: plan
  phase_round_start: plan (round 1/3)
    dispatch_start: GLM
    dispatch_end: GLM
  feedback_start: plan
  feedback_end: plan → retry ("plan too brief")
  phase_round_end: plan (round 1)
  phase_round_start: plan (round 2/3)
    dispatch_start: GLM [resume]
    dispatch_end: GLM
  feedback_start: plan
  feedback_end: plan → proceed
  phase_round_end: plan (round 2)
phase_end: plan ✅
```

## model_utils.py vs sdlc.py Changes

**`model_utils.py` — minimal change:**

One bugfix required for follow-up sessions to work:
```python
# BEFORE (line ~703)
if session_id and not resume_session and alias:
    save_session(alias, model, session_id, prompt)

# AFTER
if session_id and alias:
    save_session(alias, model, session_id, prompt)
```

Rationale: when resuming a session, `hermes chat --resume` may return the same or a new session ID. We must save that ID so the next follow-up resumes the correct session. Saving only on non-resume calls breaks the follow-up chain.

The v3 `progress_callback` work in `model_utils.py` is reused as-is.

**`sdlc.py` — primary changes:**

1. Import `get_session` from `model_utils`
2. Add constants:
   - `PHASE_ALIASES` (with `__sdlc_` prefix — CONTROLLER FIX)
   - `MAX_PHASE_ROUNDS = 3`
   - `REFUSAL_PATTERNS`
3. Add `_cleanup_sdlc_sessions()` helper (CONTROLLER ADDITION)
4. Add evaluator functions:
   - `evaluate_generic(result, round_num) → Optional[str]` (CONTROLLER FIX: 2 params, not 3)
   - `evaluate_plan(result, round_num) → Optional[str]`
   - `evaluate_design_tests(result, round_num) → Optional[str]`
   - `evaluate_implement(result, round_num) → Optional[str]`
   - `evaluate_tech_docs(result, round_num) → Optional[str]`
   - `evaluate_simplify(result, round_num) → Optional[str]`
   - `evaluate_council(result, round_num) → Optional[str]` (CONTROLLER ADDITION)
5. Add `PHASE_EVALUATORS` mapping (CONTROLLER ADDITION)
6. Add `dispatch_with_evaluation(...)` wrapper with evaluator exception safety + max_rounds=1 edge case fix (CONTROLLER FIX)
7. Refactor model-calling phase functions to call `dispatch_with_evaluation` instead of `dispatch_single`
8. Update phase functions to pass `progress_callback` (already in v3 plan) and accept an optional `max_phase_rounds` parameter
9. Update `run_test_first_pipeline` to:
   - Call `_cleanup_sdlc_sessions()` at start (CONTROLLER ADDITION)
   - Accept and forward `max_phase_rounds`
   - Check `evaluation_failed` on phase results for early-return decisions
10. Update `_stderr_callback` to render `phase_round_*` and `feedback_*` events
11. Update CLI to expose `--max-phase-rounds`

## Code Structure

**New/Modified function signatures in `sdlc.py`:**

```python
# Existing v3 signature plus new parameter
def plan(message: str, timeout: int = 120, toolsets: str = 'file,web',
         progress_callback: Optional[Callable] = None,
         max_phase_rounds: int = MAX_PHASE_ROUNDS) -> dict: ...

def design_test_suites(message: str, plan_output: str,
                       timeout: int = 120, toolsets: str = 'file,web',
                       progress_callback: Optional[Callable] = None,
                       max_phase_rounds: int = MAX_PHASE_ROUNDS) -> dict: ...

def implement(message: str, plan_output: str, test_output: str,
              timeout: int = 180,
              progress_callback: Optional[Callable] = None,
              max_phase_rounds: int = MAX_PHASE_ROUNDS) -> dict: ...

def tech_docs(message: str, code: str, plan_output: str,
              pass_num: int = 1, timeout: int = 120,
              progress_callback: Optional[Callable] = None,
              max_phase_rounds: int = MAX_PHASE_ROUNDS) -> dict: ...

def simplify_code(message: str, code: str, plan_output: str,
                  test_results: list, timeout: int = 120,
                  progress_callback: Optional[Callable] = None,
                  max_phase_rounds: int = MAX_PHASE_ROUNDS) -> dict: ...

# Pipeline signature updated
def run_test_first_pipeline(
    message: str, timeout: int = 120,
    run_verification: bool = True,
    run_council: bool = True,
    run_docs: bool = True,
    progress_callback: Optional[Callable] = None,
    max_phase_rounds: int = MAX_PHASE_ROUNDS,
) -> dict: ...
```

**Refactored phase example (`plan`):**
```python
def plan(message, timeout=120, toolsets='file,web',
         progress_callback=None, max_phase_rounds=MAX_PHASE_ROUNDS):
    _emit(progress_callback, 'phase_start', 'plan')

    prompt = (
        f"{REUSE_DIRECTIVE}\n\n"
        f"## Task\n{message}\n\n"
        f"## Output\n"
        f"Produce a concise implementation plan:\n"
        f"1. Existing facilities to reuse\n"
        f"2. New code needed\n"
        f"3. Corner cases and usage scenarios\n"
        f"4. Suggested test cases"
    )

    result = dispatch_with_evaluation(
        phase='plan',
        prompt=prompt,
        context='',
        model=resolve_alias('planner'),
        toolsets=toolsets,
        max_turns=5,
        timeout=timeout,
        provider='ollama-glm',
        thinking='medium',
        evaluator=evaluate_plan,
        max_rounds=max_phase_rounds,
        alias=PHASE_ALIASES['plan'],
        progress_callback=progress_callback,
    )

    success = bool(result.get('content')) and not result.get('evaluation_failed')
    _emit(progress_callback, 'phase_end', 'plan',
          elapsed=result.get('elapsed', 0), success=success,
          rounds=result.get('rounds', 1))
    return result
```

**`run_test_first_pipeline` forwarding example:**
```python
# At start of pipeline:
_cleanup_sdlc_sessions()

plan_result = plan(
    message, timeout=timeout,
    progress_callback=progress_callback,
    max_phase_rounds=max_phase_rounds,
)
if not plan_result.get('content') or plan_result.get('evaluation_failed'):
    _emit(progress_callback, 'pipeline_failed', 'plan',
          reason='Plan phase failed or max evaluation rounds exceeded')
    return {..., 'pipeline_status': 'plan_failed'}
```

## CLI / Controller Changes

Add to `sdlc.py` CLI:
```python
parser.add_argument('--max-phase-rounds', type=int, default=MAX_PHASE_ROUNDS,
                    help=f'Max evaluation rounds per model phase (default: {MAX_PHASE_ROUNDS})')
```

Forward to `run_test_first_pipeline`:
```python
result = run_test_first_pipeline(
    args.message, timeout=args.timeout,
    run_verification=not args.no_verify,
    progress_callback=None if args.quiet else _stderr_callback,
    max_phase_rounds=args.max_phase_rounds,
)
```

Update `_stderr_callback` to render new events concisely:
```python
elif evt == 'phase_round_start':
    line = f"[SDLC] round_start: {num}. {label} (round {event.get('round', '?')}/{event.get('total_rounds', '?')})"
elif evt == 'phase_round_end':
    ok = '✅' if event.get('success') else '❌'
    line = f"[SDLC] round_end: {num}. {label} {ok} (round {event.get('round', '?')})"
elif evt == 'feedback_end':
    decision = event.get('decision', '?')
    line = f"[SDLC] feedback: {num}. {label} → {decision}"
```

## Test Considerations

**Low risk for good-result tests:**
- Tests that mock `dispatch_single` to return valid content will trigger only one call because evaluators return `None`
- v3's mock-safety finding still holds for the new kwargs (`resume_session`, `alias`) when tests inspect `call_args.kwargs`

**Tests that need updating (CONTROLLER: quantified from source):**

| File | Test count | Tests needing update | Reason |
|---|---|---|---|
| `test_sdlc.py` | 100 | ~15 | Tests mocking `sdlc.dispatch_single` that check `call_count` — phase functions now call `dispatch_with_evaluation` which internally calls `dispatch_single`. Mock target changes from `sdlc.dispatch_single` to `sdlc.dispatch_single` (still works since `dispatch_with_evaluation` calls it), but `call_count` assertions may change (1 call → up to 3 calls for bad results). |
| `test_pipeline.py` | 98 | ~5 | Tests mocking `pipeline.dispatch_single` — similar call_count changes. |
| `test_ask.py` | 149 | ~2 | Tests checking session save behavior after the `model_utils.py` bugfix. |
| `test_pipeline_e2e.py` | 10 | 0 | Live E2E tests — unaffected (real dispatch, no mocks). |

**New tests to add (~15):**
- `test_evaluate_generic`: good result → None, empty → feedback, API error → feedback, refusal → feedback, short → feedback
- `test_evaluate_plan`: good plan → None, too short → feedback, no structure → feedback
- `test_evaluate_design_tests`: all suites → None, missing suites → feedback, unparseable → feedback
- `test_evaluate_implement`: valid code → None, no code block → feedback, too short → feedback
- `test_evaluate_council`: quorum → None, <2 seats → feedback, empty → feedback
- `test_dispatch_with_evaluation_good`: good result on round 1 → 1 dispatch call, returns result
- `test_dispatch_with_evaluation_retry`: bad then good → 2 dispatch calls, second uses resume_session
- `test_dispatch_with_evaluation_exhausted`: bad for all rounds → returns evaluation_failed=True
- `test_dispatch_with_evaluation_max_rounds_one`: max_rounds=1 with bad result → evaluation_failed=True (CONTROLLER: new edge case test)
- `test_dispatch_with_evaluation_evaluator_crash`: evaluator raises → proceeds with result (CONTROLLER: new exception safety test)
- `test_session_save_on_resume`: verify session is saved even when resume_session is set (CONTROLLER: bugfix verification)
- `test_cleanup_sdlc_sessions`: verify stale __sdlc_* entries are removed on pipeline start (CONTROLLER: new)

**Total test impact: ~20-30 existing tests need updating, ~15 new tests to add.**

## Implementation Order

1. **model_utils.py:** change session-save condition to save on resume too
2. **sdlc.py:** add `_cleanup_sdlc_sessions()` and call at pipeline start
3. **sdlc.py:** add `PHASE_ALIASES` (with `__sdlc_` prefix), `MAX_PHASE_ROUNDS`, refusal patterns, and evaluator functions (including `evaluate_council`)
4. **sdlc.py:** add `PHASE_EVALUATORS` mapping
5. **sdlc.py:** add `dispatch_with_evaluation` wrapper with:
   - Evaluator exception safety (try/except around evaluator call)
   - max_rounds=1 edge case fix (set evaluation_failed before returning)
   - Round/feedback event emission
6. **sdlc.py:** refactor `plan()`, `design_test_suites()`, `implement()`, `tech_docs()`, `simplify_code()`, `council_review()` to use the wrapper
7. **sdlc.py:** wire `max_phase_rounds` through `run_test_first_pipeline`; check `evaluation_failed` on phase results
8. **sdlc.py CLI:** add `--max-phase-rounds` and update `_stderr_callback` for new events
9. **Tests:** add evaluator tests and `dispatch_with_evaluation` tests; update any tests broken by multi-round behavior

## Deferred Enhancements

- **Model-based evaluator:** pass a small fast model (qwen) as `evaluator` to score plan quality or flag subtle issues
- **Session summarization:** if a phase accumulates many follow-ups, summarize the session before the context window overflows
- **Per-seat council follow-up:** allow the orchestrator to ask individual council advisors for clarification
- **Cross-pipeline session reuse:** intentionally resume a previous pipeline's plan session for *"build on top of X"* tasks
- **Adaptive max_rounds:** increase rounds for complex tasks based on message length or phase
- **Concurrent pipeline safety:** include pipeline UUID in alias keys or use separate session file per run
- **Separate SDLC session file:** `~/.hermes/sdlc-sessions.json` to completely isolate from user aliases

## Design Question Answers

| # | Question | Decision |
|---|---|---|
| 1 | Session lifecycle | Per-phase sessions; round 1 is fresh, rounds 2+ resume the phase alias |
| 2 | Evaluation loop | Rule-based/heuristic evaluators with swappable interface for future model-based eval |
| 3 | Max iterations | `MAX_PHASE_ROUNDS = 3` (initial + 2 follow-ups), configurable |
| 4 | "Respond back" technically | `dispatch_single(..., resume_session=<session_id>, prompt=<feedback>)` |
| 5 | Orchestrator directives | Phase-specific quality gates: artifacts, length, parseability, refusal patterns |
| 6 | Interaction with debug cascade | Complementary — evaluation loop gates phase output, debug cascade repairs test failures |
| 7 | Context window concerns | Bounded by `MAX_PHASE_ROUNDS = 3`; ~8,400 tokens worst case per phase; well within all model windows |
| 8 | Status event changes | Add `phase_round_start/end` and `feedback_start/end`; enrich dispatch events with `round` |
| 9 | Architecture | New `dispatch_with_evaluation()` wrapper — middleware pattern over `dispatch_single()` |
| 10 | model_utils vs sdlc | One bugfix in `model_utils.py` (save on resume); all orchestration logic in `sdlc.py` |

## Controller Review Findings (v4)

Systematic 10-point review of the v3 plan against actual source code at `/opt/data/skills/productivity/ask/scripts/`:

| # | Area | Finding | Severity | Fix Integrated |
|---|---|---|---|---|
| 1 | Session save bugfix | Line 703 `if session_id and not resume_session and alias:` → `if session_id and alias:` is correct. Verified against source. | ✅ Correct | N/A |
| 2a | dispatch_with_evaluation | Evaluator call not wrapped in try/except — if `evaluator(result, round_num)` raises, the whole phase crashes. | 🔴 Bug | Wrapped in try/except; proceeds on evaluator error |
| 2b | dispatch_with_evaluation | `max_rounds=1` with evaluator returning feedback silently returns bad result without `evaluation_failed=True`. | 🔴 Bug | Added check: if `round_num >= max_rounds` and feedback is not None, set `evaluation_failed=True` before returning |
| 3a | Evaluator signatures | `evaluate_generic` had 3 params `(result, phase, round_num)` but `EvaluatorFn` is `Callable[[dict, int], Optional[str]]` (2 params). | 🔴 Bug | Fixed to `evaluate_generic(result, round_num)` |
| 3b | Missing evaluator | `evaluate_council` listed in quality gate table but never defined. | 🟡 Gap | Added `evaluate_council` with quorum check |
| 3c | Missing mapping | `PHASE_EVALUATORS` mapping mentioned in implementation list but never specified. | 🟡 Gap | Added `PHASE_EVALUATORS` dict |
| 4 | Alias collision | `sdlc-*` aliases share flat namespace with user aliases in `ask-sessions.json`. | 🟡 Risk | Changed to `__sdlc_*` prefix (double-underscore convention) |
| 5 | Max rounds policy | `MAX_PHASE_ROUNDS=3` is reasonable. Edge case fixed (see #2b). | ✅ Fixed | N/A |
| 6 | Context window math | Missing from plan. | 🟡 Gap | Added context window math table (~8,400 tokens worst case) |
| 7 | debug_cascade budget | No conflict, but worst-case model calls not documented. | 🟡 Gap | Added note: 5 max model calls per phase (3 eval + 2 debug) |
| 8 | Double-emission | New events (`phase_round_*`, `feedback_*`) emitted only by `dispatch_with_evaluation`. No double-emission risk. | ✅ Clean | N/A |
| 9 | Test impact | ~20-30 existing tests need updating; ~15 new tests needed. Quantified from source. | 🟡 Info | Added test impact table with per-file breakdown |
| 10a | Concurrent pipelines | Two simultaneous pipelines share `__sdlc_*` session entries. No locking. | 🟡 Known limitation | Documented; deferred to future |
| 10b | Session cleanup | Stale entries from crashed pipelines persist. | 🟡 Gap | Added `_cleanup_sdlc_sessions()` called at pipeline start |
| 10c | TTL expiry mid-pipeline | Mitigated by existing `dispatch_single` fallback (line 662). | ✅ Mitigated | Documented |

## Review History

| Reviewer | Model | Date | Verdict | Key Issues |
|---|---|---|---|---|
| Kimi | kimi-k2.7-code:cloud | 2026-06-28 | Architecture sound, ship with fixes | Thread lock, dispatch_comparison plumbing, test mocks, early-return coverage, --quiet flag, callback exception handling |
| DeepSeek | deepseek-v4-pro:cloud | 2026-06-28 | Ship with fixes below | Double-emission bug, early-return count wrong, missing `import threading`, `_stderr_callback` missing dispatch handlers, `_safe_callback` location unspecified, `dispatch_comparison` line numbers off by 2, test plan underspecified |
| Controller | deepseek-v4-pro:cloud | 2026-06-28 | Ship with v4 fixes below | 2 bugs (evaluator crash, max_rounds=1 edge case), 5 gaps (evaluator signature, missing evaluate_council, missing PHASE_EVALUATORS, alias collision, context math), 2 missing pieces (session cleanup, concurrent safety documented) |
| Controller | kimi-k2.7-code:cloud | 2026-06-28 | Architecture extension v5 — logical control channel, context lifecycle, iterative state machine, worktrees, file-reference protocol | 6 new architectural concepts incorporated into v5 extension below |

---

# SDLC Orchestrator v5 — Control Channel, Context Lifecycle, Iterative State Machine, Worktrees, File-Reference Protocol

> **Status:** Design v5 — architectural extension to v4, authored by Controller (Kimi review pass)
> **Date:** 2026-06-28
> **Author:** Controller, integrating user requirements
> **Files:** `model_utils.py`, `sdlc.py`, `pipeline.py` (all under `skills/productivity/ask/scripts/`)
> **Scope:** Design only — implementation is a follow-up task

## Problem

The v4 SDLC orchestrator still passes large text artifacts (5K+ char plans, full test suites, generated code) directly inside prompt strings. The orchestrator also keeps per-phase sessions alive across retries, and the pipeline is a mostly-linear chain with only one council-refinement loop. The user wants six new architectural concepts:

1. **Logical control channel** — orchestrator ↔ subagent coordination should pass file paths, not bulk content.
2. **Context lifecycle management** — close a subagent context when its work is done; start fresh if another layer needs it.
3. **Iterative state machine** — orchestrator decides when to stop iterating based on diminishing returns, plateau, or max iterations.
4. **Final summary + teaching** — required end-of-run deliverable explaining what happened and how the new system works.
5. **Independent project directories with git worktrees** — each pipeline run gets its own isolated worktree branch.
6. **File-reference protocol** — pass paths like `/worktree/RESEARCH.md` instead of embedding content in prompts.

This section designs all six concepts concretely, answers the technical questions, and maps changes to `sdlc.py`, `model_utils.py`, and new files.

## 1. Logical Control Channel

### What it is

The "control channel" is the orchestrator's prompt text and structured directives. It carries:
- The phase goal
- Required input/output file paths
- Evaluation criteria
- State transitions

It does **not** carry:
- The full plan text
- Full test suites
- Full code blocks
- Council reviews

Those live in files inside the worktree; subagents read/write them with their own file toolset.

### Technical form

It is a normal `prompt` argument to `dispatch_single()`, but it is constructed with file references instead of embedded content. Example:

```
You are the implementation agent for the SDLC pipeline.
Read the plan at /worktree/.sdlc/RESEARCH.md and the test suites at /worktree/.sdlc/tests/.
Implement the solution as /worktree/solution.py.
After writing, run pytest /worktree/tests/ and report any failures.
Do not put implementation details in this message — read the files.
```

No separate metadata dict, no side file. The control channel is simply the prompt text plus the existing structured event stream (`progress_callback`) for status reporting. Hermes subagents already have file tools, so reading/writing worktree files is their responsibility.

### Why this works

- `dispatch_single()` spawns `hermes chat -q`, which gives the subagent the full tool loop (file, web, terminal).
- The subagent sees a small prompt and pulls multi-KB artifacts itself.
- The orchestrator stays in charge of which files exist and what phase to run; the subagent decides how to satisfy the directive.

### Changes needed

**`model_utils.py`:**
- Already supports `output_file` parameter; extend it to also write a structured control envelope when an `artifact_dir` is passed.
- Add optional `artifacts: dict[str, str] = None` parameter to `dispatch_single()` — maps logical artifact names (e.g., `"plan"`, `"tests"`) to absolute paths. The envelope header written to `output_file` includes these references so external consumers can correlate.
- Keep `progress_callback` from v3/v4; it is the status/control sideband, not data transfer.

**`sdlc.py`:**
- Replace embedded-content prompts with file-reference prompts.
- Phase functions no longer build giant `prompt` strings containing plan/test/code. They build a short directive and point the subagent at files in the worktree.
- The subagent is expected to write its output to a known path (e.g., `/worktree/.sdlc/plan.md`) and return a brief confirmation.

### New file

**`sdlc_control.py`** (new helper module):
- `build_control_message(phase: str, worktree: str, refs: dict, directive: str) -> str`
- `parse_agent_report(content: str) -> dict` — extracts file paths the subagent claims to have written, plus a success/failure flag.
- `emit_control_event(callback, phase, action, refs)` — thin wrapper around `_emit()` with event type `control`.

### New event type

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `control` | Control channel message sent/received | `sdlc_control.emit_control_event` | phase, action (`send`|`receive`), refs, size_hint (chars in prompt) |

## 2. Context Lifecycle Management

### What "close context" means

Closing a context means **stopping the Hermes chat session** so the next interaction with the same or a different model starts fresh. It is not a marker file; it is the absence of `resume_session` on the next `dispatch_single()` call.

Current `dispatch_single()` already supports `--resume <session_id>`. If `resume_session` is `None`, `hermes chat` starts a new session. Therefore:
- **Open context:** pass `resume_session=<saved_id>` and an `alias`.
- **Keep context:** same alias + saved session_id across multiple rounds within one phase (v4 evaluation loop).
- **Close context:** stop passing `resume_session` for that alias; do not save further session_ids.

### Lifecycle ownership

The orchestrator owns the lifecycle. A phase wrapper (`dispatch_with_evaluation`) decides when an agent is done:
1. If evaluation returns `None` → close context after this phase.
2. If evaluation returns feedback and `round_num < max_rounds` → keep context open, resume same alias for the follow-up.
3. When `round_num` is the last allowed round → close context regardless of outcome.

This replaces the v4 default of leaving every saved `__sdlc_*` session in the registry until pipeline end.

### Implementation

Add to `sdlc.py`:

```python
class ContextState:
    """Tracks whether a phase's session is open, closed, or transitioning."""

    def __init__(self, alias: str):
        self.alias = alias
        self.session_id: Optional[str] = None
        self.is_open: bool = False

    def attach(self, result: dict):
        """Attach a freshly returned session_id to this context."""
        sid = result.get('session_id')
        if sid:
            self.session_id = sid
            self.is_open = True

    def close(self):
        """Close the context. Subsequent dispatches will start fresh."""
        self.session_id = None
        self.is_open = False

    def resume(self) -> Optional[str]:
        """Return the session_id to resume, or None if closed."""
        return self.session_id if self.is_open else None
```

Refactor `dispatch_with_evaluation` to take a `ContextState` object:

```python
def dispatch_with_evaluation(
    phase: str,
    ctx: ContextState,
    prompt: str,
    ...,
    progress_callback: Optional[Callable] = None,
) -> dict:
    for round_num in range(1, max_rounds + 1):
        session_id = ctx.resume() if round_num > 1 else None
        result = dispatch_single(
            ...,
            resume_session=session_id,
            alias=ctx.alias,
            progress_callback=progress_callback,
        )
        ctx.attach(result)
        feedback = evaluator(result, round_num)
        if feedback is None:
            ctx.close()
            return result
        if round_num >= max_rounds:
            ctx.close()
            result['evaluation_failed'] = True
            result['evaluation_feedback'] = feedback
            return result
        # context stays open; next round will resume ctx.session_id
    ctx.close()
    return result
```

### New event types

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `context_open` | New session started for a phase | `ContextState.attach` | phase, alias, session_id (hashed) |
| `context_close` | Session closed for a phase | `ContextState.close` | phase, alias, rounds |

The `session_id` is SHA-256-hashed in events to avoid leaking session identifiers in logs.

### Changes to `model_utils.py`

- Add a small `_close_session(alias)` helper that removes a session entry from the registry. Called by `ContextState.close()` if we want deterministic cleanup.
- Keep the existing save-on-resume fix from v4 (save session even when resuming).

## 3. Iterative State Machine

### State machine design

States are explicit in code as a Python `Enum`:

```python
from enum import Enum, auto

class SDLCState(Enum):
    INIT = auto()
    PLAN = auto()
    EVALUATE_PLAN = auto()
    REVISE_PLAN = auto()
    DESIGN_TESTS = auto()
    EVALUATE_TESTS = auto()
    IMPLEMENT = auto()
    RUN_TESTS = auto()
    DEBUG = auto()
    REVIEW = auto()
    REFINE = auto()
    COMPLETE = auto()
```

Transitions are driven by an evaluation/effect function, not a static dict:

```python
StateTransition = Callable[[SDLCState, SDLCRun], SDLCState]

def default_transition(state: SDLCState, run: 'SDLCRun') -> SDLCState:
    if state == SDLCState.PLAN:
        return SDLCState.EVALUATE_PLAN
    if state == SDLCState.EVALUATE_PLAN:
        if run.plan_result.get('evaluation_failed'):
            return SDLCState.REVISE_PLAN if run.iteration < MAX_ITERATIONS else SDLCState.COMPLETE
        return SDLCState.DESIGN_TESTS
    if state == SDLCState.REVISE_PLAN:
        return SDLCState.EVALUATE_PLAN
    if state == SDLCState.DESIGN_TESTS:
        return SDLCState.EVALUATE_TESTS
    if state == SDLCState.EVALUATE_TESTS:
        if run.test_result.get('evaluation_failed'):
            return SDLCState.DESIGN_TESTS if run.iteration < MAX_ITERATIONS else SDLCState.COMPLETE
        return SDLCState.IMPLEMENT
    if state == SDLCState.IMPLEMENT:
        return SDLCState.RUN_TESTS
    if state == SDLCState.RUN_TESTS:
        return SDLCState.DEBUG if run.needs_debug else SDLCState.REVIEW
    if state == SDLCState.DEBUG:
        return SDLCState.RUN_TESTS if run.debug_succeeded else SDLCState.COMPLETE
    if state == SDLCState.REVIEW:
        return SDLCState.REFINE if run.has_improvement_items else SDLCState.COMPLETE
    if state == SDLCState.REFINE:
        return SDLCState.IMPLEMENT if run.iteration < MAX_ITERATIONS else SDLCState.COMPLETE
    return SDLCState.COMPLETE
```

The main loop is a `while` loop with `if/elif` dispatch (cleaner than a transition table because each transition has side effects):

```python
def run_state_machine(message: str, worktree: str,
                      max_iterations: int = 3,
                      progress_callback: Optional[Callable] = None) -> SDLCRun:
    run = SDLCRun(message=message, worktree=worktree)
    state = SDLCState.INIT
    while state != SDLCState.COMPLETE:
        _emit(progress_callback, 'state', state.name, iteration=run.iteration)
        if state == SDLCState.INIT:
            state = SDLCState.PLAN
        elif state == SDLCState.PLAN:
            run.plan_result = plan(...)
            state = SDLCState.EVALUATE_PLAN
        elif state == SDLCState.EVALUATE_PLAN:
            state = evaluate_and_transition(run, SDLCState.REVISE_PLAN, SDLCState.DESIGN_TESTS)
        elif state == SDLCState.REVISE_PLAN:
            run.plan_result = revise_plan(run)
            run.iteration += 1
            state = SDLCState.EVALUATE_PLAN
        elif state == SDLCState.DESIGN_TESTS:
            run.test_result = design_test_suites(...)
            state = SDLCState.EVALUATE_TESTS
        elif state == SDLCState.EVALUATE_TESTS:
            state = evaluate_and_transition(run, SDLCState.DESIGN_TESTS, SDLCState.IMPLEMENT)
        elif state == SDLCState.IMPLEMENT:
            run.code_result = implement(...)
            state = SDLCState.RUN_TESTS
        elif state == SDLCState.RUN_TESTS:
            run.test_runs = run_test_suites(...)
            run.needs_debug = any(not tr.get('passed') for tr in run.test_runs)
            state = SDLCState.DEBUG if run.needs_debug else SDLCState.REVIEW
        elif state == SDLCState.DEBUG:
            run.debug_result = debug_cascade(...)
            run.debug_succeeded = run.debug_result.get('cascade_succeeded', False)
            state = SDLCState.RUN_TESTS if run.debug_succeeded else SDLCState.COMPLETE
        elif state == SDLCState.REVIEW:
            run.council_result = council_review(...)
            run.has_improvement_items = has_improvement_items(run.council_result.get('content', ''))
            state = SDLCState.REFINE if run.has_improvement_items else SDLCState.COMPLETE
        elif state == SDLCState.REFINE:
            run.refine_result = refine(run)
            run.iteration += 1
            state = SDLCState.IMPLEMENT
        else:
            state = SDLCState.COMPLETE
    return run
```

### Diminishing returns detection

Three complementary signals:

1. **Evaluation feedback similarity** — track a history of feedback strings. If the same feedback text (normalized) appears twice, we are in a loop; stop.
2. **Improvement delta** — compute a simple quality score and require a minimum delta between rounds. Score components:
   - Plan: length (capped), number of headings, concrete file references
   - Tests: number of suites parsed, number of `test_` functions via regex
   - Code: whether `extract_python_code()` succeeds, number of public functions, lint pass
   - Council: number of P0/P1 items resolved vs newly introduced
3. **Max iterations** — hard ceiling (`MAX_ITERATIONS = 3`) to guarantee termination.

Implementation helper in `sdlc_state.py`:

```python
class DiminishingReturnsTracker:
    def __init__(self, min_delta: float = 0.05, max_repeats: int = 2):
        self.scores: list[float] = []
        self.feedbacks: list[str] = []
        self.min_delta = min_delta
        self.max_repeats = max_repeats

    def update(self, score: float, feedback: Optional[str]):
        self.scores.append(score)
        if feedback:
            normalized = ' '.join(feedback.lower().split())
            self.feedbacks.append(normalized)

    def should_stop(self) -> tuple[bool, str]:
        if len(self.scores) >= 2:
            delta = self.scores[-1] - self.scores[-2]
            if delta < self.min_delta:
                return True, f"Improvement delta {delta:.3f} below threshold {self.min_delta}"
        feedback_counts = Counter(self.feedbacks)
        if any(c >= self.max_repeats for c in feedback_counts.values()):
            return True, "Repeated evaluation feedback detected"
        return False, ""
```

The `evaluate_and_transition()` helper consults the tracker:

```python
def evaluate_and_transition(run, retry_state, next_state):
    score = run.compute_quality_score()
    run.diminishing_tracker.update(score, run.last_feedback)
    stop, reason = run.diminishing_tracker.should_stop()
    if stop:
        _emit(..., 'diminishing_returns', reason)
        return SDLCState.COMPLETE
    if run.last_feedback:
        return retry_state
    return next_state
```

### New event types

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `state` | State changes | `run_state_machine` | state, iteration |
| `diminishing_returns` | Iteration stopped due to low improvement | `DiminishingReturnsTracker` | reason, delta, iteration |

## 4. Final Summary + Teaching

### Required deliverable

At the end of every pipeline run, the orchestrator writes a file `/.sdlc/SUMMARY.md` in the worktree and emits a `summary` event. The summary contains:

- What was built (one sentence).
- Which phases ran and how many iterations each took.
- Where the final artifacts live.
- Key decisions made (e.g., "debug cascade used Kimi after Qwen failed").
- How the new architecture works (the "teaching" section):
  - Control channel: file paths passed, subagents read/write files
  - Context lifecycle: sessions opened/closed per phase
  - State machine: states and transition logic
  - Worktrees: isolation and merge-back
  - File-reference protocol: why prompts stay small

### Implementation

New function in `sdlc.py`:

```python
def write_summary(run: SDLCRun) -> str:
    summary = f"""# SDLC Run Summary

## What was completed
- Task: {run.message}
- Final status: {run.status}
- Total elapsed: {run.elapsed:.1f}s
- Iterations: {run.iteration}

## Phases executed
- Plan: {run.plan_result and 'ok' or 'failed'}
- Test design: {run.test_result and 'ok' or 'failed'}
- Implementation: {run.code_result and 'ok' or 'failed'}
- Test runs: {len(run.test_runs or [])} suite(s)
- Debug cascade: {run.debug_result and run.debug_result.get('cascade_succeeded') and 'used' or 'not needed'}
- Council review: {run.council_result and run.council_result.get('status') or 'skipped'}

## Artifacts
- Plan: {os.path.join(run.worktree, '.sdlc/RESEARCH.md')}
- Tests: {os.path.join(run.worktree, '.sdlc/tests/')}
- Solution: {os.path.join(run.worktree, 'solution.py')}
- Summary: {os.path.join(run.worktree, '.sdlc/SUMMARY.md')}

## How the new SDLC architecture works
1. **Logical control channel:** The orchestrator sends short prompts with file paths. Subagents read/write artifacts using their own file tools. This keeps prompts small and the orchestrator in control.
2. **Context lifecycle:** Each phase uses a `ContextState` object. A session is opened on round 1 and closed when evaluation says the phase is done or when max rounds are exhausted.
3. **Iterative state machine:** `SDLCState` enumerates states like PLAN, EVALUATE_PLAN, REVISE_PLAN, etc. Transitions are driven by evaluation results and a `DiminishingReturnsTracker`.
4. **Git worktrees:** Each run creates a worktree on a feature branch, commits progress, merges back to main when successful, and removes the worktree.
5. **File-reference protocol:** Instead of embedding `plan_output` (5K chars) in an implement prompt, the orchestrator passes `Plan is at /worktree/.sdlc/RESEARCH.md — read it and implement accordingly`.
"""
    path = os.path.join(run.worktree, '.sdlc/SUMMARY.md')
    with open(path, 'w') as f:
        f.write(summary)
    return path
```

### New event type

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `summary` | End of pipeline | `write_summary` | path, chars, status, elapsed |

## 5. Independent Project Directories with Git Worktrees

### Lifecycle

1. **Create before Phase 1:** `create_worktree()` is called with a sanitized branch name derived from the user message and a UUID short hash.
2. **Commit per iteration with structured learning:** after each EVALUATE state, call `learning_commit(run, state, feedback, progress_callback)` before transitioning to a REVISE/DESIGN_TESTS retry. The commit message is not a generic label — it is a structured learning record containing:
   - **Attempt:** what the phase produced in this iteration (file paths, key decisions).
   - **Evaluation:** what the evaluator found (pass/fail, concrete feedback).
   - **Revision:** what should change in the next iteration.
   - **Learnings:** concise takeaways for future runs (e.g., "Planner omitted error handling until explicitly prompted; always list corner cases").
   - **Next time:** actionable prompt adjustments for the next iteration or next pipeline.
   The commit references the evaluation feedback that drove the revision, so git history becomes a learning journal.
3. **Capture git history before PLAN:** before the first `SDLCState.PLAN`, call `prepare_git_history(worktree)` to write `/.sdlc/HISTORY.md` from `git log --oneline` and `git log --format=%B`. The plan phase prompt references this file so iteration N+1 learns from iteration N's commits.
4. **Merge after COMPLETE:** if the pipeline status is `success` or `council_reviewed`, `merge_worktree_to_main()` fast-forwards or merges the branch.
5. **Remove after merge:** `remove_worktree()` deletes the worktree directory and prunes the git worktree list.

### Branch naming

```python
def make_branch_name(message: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', message.lower())[:40].strip('-')
    uid = uuid.uuid4().hex[:8]
    return f"sdlc/{slug}-{uid}"
```

### New file: `sdlc_worktree.py`

```python
#!/usr/bin/env python3
"""sdlc_worktree — git worktree management and learning commits for SDLC runs."""

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Callable

WORKTREE_ROOT = os.environ.get('SDLC_WORKTREE_ROOT', '/opt/data/sdlc-worktrees')
REPO_ROOT = os.environ.get('SDLC_REPO_ROOT', '/opt/data')

def ensure_worktree_root() -> Path:
    Path(WORKTREE_ROOT).mkdir(parents=True, exist_ok=True)
    return Path(WORKTREE_ROOT)

def make_branch_name(message: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', message.lower())[:40].strip('-')
    return f"sdlc/{slug}-{uuid.uuid4().hex[:8]}"

def create_worktree(message: str, base_ref: str = 'main') -> str:
    ensure_worktree_root()
    branch = make_branch_name(message)
    path = os.path.join(WORKTREE_ROOT, branch.replace('/', '_'))
    subprocess.run(
        ['git', 'worktree', 'add', '-b', branch, path, base_ref],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    return path

def init_sdlc_dir(worktree: str) -> str:
    sdlc_dir = os.path.join(worktree, '.sdlc')
    os.makedirs(os.path.join(sdlc_dir, 'tests'), exist_ok=True)
    with open(os.path.join(sdlc_dir, '.gitignore'), 'w') as f:
        f.write("*.pyc\n__pycache__/\n.pytest_cache/\n")
    return sdlc_dir

def git_commit(worktree: str, message: str, files: list[str]) -> None:
    if not files:
        return
    subprocess.run(['git', 'add'] + files, cwd=worktree, check=True)
    try:
        subprocess.run(['git', 'commit', '-m', message], cwd=worktree, check=True)
    except subprocess.CalledProcessError:
        # Nothing to commit — ignore
        pass

def learning_commit(
    worktree: str,
    state: str,
    iteration: int,
    feedback: str,
    files: list[str],
    progress_callback: Optional[Callable] = None,
) -> None:
    """Commit a structured learning record after an EVALUATE state drives a revision.

    The commit message is the learning artifact: it captures what was attempted,
    what the evaluation found, what should be revised, what was learned, and what
    to try next time. It references the evaluator feedback that triggered it.
    """
    escaped_feedback = feedback.replace('"', '\\"')[:2000]
    message = f"""learn: {state} iteration {iteration}

Attempt:
- Produced artifacts in {worktree}/.sdlc/
- State: {state}
- Iteration: {iteration}

Evaluation:
{escaped_feedback}

Revision:
- Address the evaluation feedback in the next iteration.
- Preserve working decisions; change only the issues noted.

Learnings:
- Captured from this iteration's evaluation to inform the next round.

Next time:
- Reference prior learning commits when planning or revising.
- Use structured feedback to avoid repeating the same gaps.

See HISTORY.md in the worktree for prior iterations.
"""
    git_commit(worktree, message, files)
    if progress_callback:
        try:
            progress_callback({
                'event': 'learning_commit',
                'state': state,
                'iteration': iteration,
                'worktree': worktree,
                'files': files,
                'feedback_preview': feedback[:120],
            })
        except Exception:
            pass

def prepare_git_history(worktree: str) -> str:
    """Write /.sdlc/HISTORY.md from the worktree's git log.

    The plan phase reads this file to factor learnings from prior iterations into
    its planning.
    """
    sdlc_dir = os.path.join(worktree, '.sdlc')
    history_path = os.path.join(sdlc_dir, 'HISTORY.md')
    os.makedirs(sdlc_dir, exist_ok=True)
    oneline = subprocess.run(
        ['git', 'log', '--oneline'],
        cwd=worktree, check=True, capture_output=True, text=True,
    ).stdout
    full = subprocess.run(
        ['git', 'log', '--format=%B'],
        cwd=worktree, check=True, capture_output=True, text=True,
    ).stdout
    with open(history_path, 'w') as f:
        f.write("# SDLC Learning History\n\n")
        f.write("## Oneline\n\n```\n")
        f.write(oneline)
        f.write("```\n\n## Full Commit Messages\n\n```\n")
        f.write(full)
        f.write("```\n")
    return history_path

def merge_worktree_to_main(worktree: str, branch: str, base_ref: str = 'main') -> None:
    subprocess.run(['git', 'checkout', base_ref], cwd=REPO_ROOT, check=True)
    subprocess.run(['git', 'merge', '--no-ff', branch, '-m', f"Merge {branch}"], cwd=REPO_ROOT, check=True)

def remove_worktree(worktree: str) -> None:
    subprocess.run(['git', 'worktree', 'remove', '--force', worktree], cwd=REPO_ROOT, check=True)
    subprocess.run(['git', 'worktree', 'prune'], cwd=REPO_ROOT, check=True)

def worktree_branch(worktree: str) -> str:
    result = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        cwd=worktree, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()
```

### Where commits happen in the state machine

The state machine calls `learning_commit()` immediately after each EVALUATE state that produces feedback and before entering the corresponding REVISE state:

```python
elif state == SDLCState.EVALUATE_PLAN:
    feedback = run.plan_result.get('evaluation_feedback')
    if feedback and run.iteration < MAX_ITERATIONS:
        learning_commit(
            worktree=run.worktree,
            state=SDLCState.PLAN.name,
            iteration=run.iteration,
            feedback=feedback,
            files=[os.path.join(run.worktree, '.sdlc', 'RESEARCH.md')],
            progress_callback=progress_callback,
        )
    state = evaluate_and_transition(run, SDLCState.REVISE_PLAN, SDLCState.DESIGN_TESTS)

elif state == SDLCState.EVALUATE_TESTS:
    feedback = run.test_result.get('evaluation_feedback')
    if feedback and run.iteration < MAX_ITERATIONS:
        learning_commit(
            worktree=run.worktree,
            state=SDLCState.DESIGN_TESTS.name,
            iteration=run.iteration,
            feedback=feedback,
            files=run.test_artifacts,
            progress_callback=progress_callback,
        )
    state = evaluate_and_transition(run, SDLCState.DESIGN_TESTS, SDLCState.IMPLEMENT)

elif state == SDLCState.REVIEW:
    # Council also emits a learning commit if improvement items require a REFINE iteration.
    if run.has_improvement_items and run.iteration < MAX_ITERATIONS:
        learning_commit(
            worktree=run.worktree,
            state=SDLCState.REVIEW.name,
            iteration=run.iteration,
            feedback=run.council_result.get('content', '')[:1000],
            files=[os.path.join(run.worktree, 'solution.py')],
            progress_callback=progress_callback,
        )
    state = SDLCState.REFINE if run.has_improvement_items else SDLCState.COMPLETE
```

Each PLAN→EVALUATE_PLAN→REVISE_PLAN cycle is therefore a single iteration with one learning commit that captures the full learning from that iteration.

### Integration with existing pipeline

- `run_state_machine()` receives `worktree: str` at the top.
- Phase functions write to `worktree/.sdlc/` and `worktree/solution.py`.
- The pipeline no longer writes temp files under `/opt/data/sdlc-test-run-{suite}` (current code). Tests run inside the worktree directory.

### New event types

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `worktree_create` | Worktree created | `create_worktree` | worktree, branch, base_ref |
| `worktree_commit` | Commit made | `git_commit` | worktree, message, files |
| `worktree_merge` | Branch merged | `merge_worktree_to_main` | worktree, branch, base_ref |
| `worktree_remove` | Worktree removed | `remove_worktree` | worktree |

## 6. File-Reference Protocol

### What changes

Phase prompts no longer embed the previous artifact. They reference files:

- `plan()` writes `/worktree/.sdlc/RESEARCH.md`.
- `design_test_suites()` reads that file and writes suites to `/worktree/.sdlc/tests/<suite>.py`.
- `implement()` reads the plan and tests, writes `/worktree/solution.py`.
- `tech_docs()` reads `/worktree/solution.py`, writes documented version back to the same path.
- `simplify_code()` reads `/worktree/solution.py`, writes simplified version back.
- `council_review()` reads `/worktree/solution.py` and `/worktree/.sdlc/RESEARCH.md`.

### Example phase prompts

**Before (v4):**
```python
prompt = (
    f"## Task\n{message}\n\n"
    f"## Implementation Plan\n{plan_output}\n\n"
    f"## Test Cases to Satisfy\n{test_output}\n\n"
    ...
)
```

**After (v5):**
```python
def plan(message: str, worktree: str, ...) -> dict:
    sdlc_dir = os.path.join(worktree, '.sdlc')
    plan_path = os.path.join(sdlc_dir, 'RESEARCH.md')
    history_path = os.path.join(sdlc_dir, 'HISTORY.md')
    prompt = build_control_message(
        phase='plan',
        worktree=worktree,
        refs={'output': plan_path, 'history': history_path},
        directive=(
            "Review the git history at /worktree for lessons from prior iterations. "
            "Factor these learnings into your plan. "
            "Inspect the existing codebase for reusable facilities, then write "
            "a concise implementation plan to /worktree/.sdlc/RESEARCH.md. "
            "Cover: 1) files/functions to reuse, 2) new code needed (KISS/YAGNI), "
            "3) corner cases, 4) suggested test cases. Do not output the plan in chat. "
            "If this is iteration 2+, explicitly reference what was learned in iteration 1."
        ),
    )
    result = dispatch_with_evaluation(...)
    # The subagent is expected to have written plan_path.
    if os.path.exists(plan_path):
        result['content'] = read_file_limited(plan_path)
    return result
```

The same pattern for implement:

```python
def implement(message: str, worktree: str, ...) -> dict:
    plan_path = os.path.join(worktree, '.sdlc', 'RESEARCH.md')
    tests_dir = os.path.join(worktree, '.sdlc', 'tests')
    solution_path = os.path.join(worktree, 'solution.py')
    prompt = build_control_message(
        phase='implement',
        worktree=worktree,
        refs={'plan': plan_path, 'tests': tests_dir, 'output': solution_path},
        directive=(
            f"Read the plan at {plan_path} and the test suites in {tests_dir}. "
            f"Implement /worktree/solution.py so all tests pass. "
            f"Run pytest inside the worktree and fix any failures before returning. "
            f"Return only a brief confirmation, not the code."
        ),
    )
    result = dispatch_with_evaluation(...)
    if os.path.exists(solution_path):
        result['content'] = read_file_limited(solution_path)
    return result
```

### Function signature changes

| Function | Old signature | New signature |
|---|---|---|
| `plan` | `plan(message, timeout=120, toolsets='file,web', progress_callback=None, max_phase_rounds=3)` | `plan(message, worktree: str, timeout=120, toolsets='file,web', progress_callback=None, max_phase_rounds=3)` |
| `design_test_suites` | `design_test_suites(message, plan_output, ...)` | `design_test_suites(message, worktree: str, ...)` |
| `implement` | `implement(message, plan_output, test_output, ...)` | `implement(message, worktree: str, ...)` |
| `tech_docs` | `tech_docs(message, code, plan_output, ...)` | `tech_docs(message, worktree: str, ...)` |
| `simplify_code` | `simplify_code(message, code, plan_output, test_results, ...)` | `simplify_code(message, worktree: str, ...)` |
| `council_review` | `council_review(message, code, plan_output, test_results, ...)` | `council_review(message, worktree: str, ...)` |
| `run_test_first_pipeline` | `run_test_first_pipeline(message, timeout=120, ...)` | `run_test_first_pipeline(message, worktree: Optional[str]=None, timeout=120, ...)` |

If `worktree` is `None`, the pipeline auto-creates one using `create_worktree()`.

### New helper

```python
def read_file_limited(path: str, limit: int = 50_000) -> str:
    try:
        with open(path) as f:
            return f.read(limit)
    except (OSError, IOError):
        return ''
```

## Design Question Answers

### How does the control channel work technically?

It is the `prompt` argument to `dispatch_single()`. The prompt is short and contains file paths. The subagent uses its file tools to read/write artifacts. No separate metadata file is needed. The existing `progress_callback` event stream is the sideband for status, not data.

### How does "close context" work?

Context close means no longer passing `resume_session` and no longer saving the session alias. We add a `ContextState` object per phase. The orchestrator calls `ctx.close()` when evaluation says the phase is done or when max rounds are exhausted. A `_close_session(alias)` helper can also remove the registry entry.

### What does the state machine look like as code?

A Python `Enum` for states, a `while` loop in `run_state_machine()`, and `if/elif` dispatch. A `DiminishingReturnsTracker` determines when to transition to `COMPLETE` from `REVISE_PLAN`, `DESIGN_TESTS`, or `REFINE` states.

### How does diminishing returns detection work?

Track a quality score per iteration and the normalized evaluation feedback. Stop when the score delta falls below a threshold (`min_delta = 0.05`) or the same feedback repeats twice. Also honor a hard `MAX_ITERATIONS` ceiling.

### How does the worktree lifecycle integrate?

Create worktree before `SDLCState.PLAN`. Capture git history into `/.sdlc/HISTORY.md` immediately after worktree creation. Commit per iteration with `learning_commit()` after each EVALUATE state that produces feedback, before entering REVISE. Merge to `main` when `SDLCState.COMPLETE` is reached with a success status. Remove the worktree immediately after merge. If the pipeline fails before merge, the worktree is left in place for debugging unless a `--cleanup-on-failure` flag is set.

### How does git history review during planning work?

Before the first `SDLCState.PLAN`, the orchestrator runs `git log --oneline` and `git log --format=%B` inside the worktree and writes the combined output to `/.sdlc/HISTORY.md`. The plan phase prompt references that file and instructs the planner to review prior learning commits, factor their lessons into the new plan, and explicitly reference iteration 1 learnings when this is iteration 2+. The git history becomes a learning journal that informs future planning, creating a feedback loop between iterations.

### How does the file-reference protocol change phase signatures?

Remove `plan_output`, `test_output`, `code`, etc. from phase function signatures. Add `worktree: str`. Each phase reads the needed artifacts from the worktree and writes its output to a known path. The returned dict still has a `content` field, populated by reading the artifact file the subagent was directed to write.

## Implementation Plan

1. **Create `sdlc_worktree.py`** — worktree create/commit/merge/remove helpers, plus `learning_commit()` and `prepare_git_history()`.
2. **Create `sdlc_control.py`** — `build_control_message()`, `parse_agent_report()`, `emit_control_event()`.
3. **Create `sdlc_state.py`** — `SDLCState` enum, `DiminishingReturnsTracker`, `SDLCRun` dataclass.
4. **Update `model_utils.py`**:
   - Add `artifacts` parameter to `dispatch_single()`.
   - Write artifact envelope to `output_file` when artifacts are passed.
   - Add `_close_session(alias)` helper.
5. **Update `sdlc.py`**:
   - Add `ContextState` class.
   - Refactor phase functions to use file-reference protocol; `plan()` reads `HISTORY.md`.
   - Add `run_state_machine()` and `run_test_first_pipeline_v5()` entry point.
   - Call `prepare_git_history()` before the first PLAN.
   - Integrate worktree lifecycle and `learning_commit()` after each EVALUATE state that drives revision.
   - Add `write_summary()`.
6. **Update `pipeline.py`**:
   - Forward `worktree` parameter from CLI/env if provided.
   - Call `run_test_first_pipeline(message, worktree=...)`.
7. **Tests**:
   - Mock `git` subprocesses for worktree tests.
   - Test `learning_commit()` message structure and `prepare_git_history()` output.
   - Test file-reference prompts contain correct paths and history directive.
   - Test `DiminishingReturnsTracker` stop conditions.
   - Test `ContextState` open/close behavior.

## New / Extended Event Contract

| Event | When | Emitted By | Fields |
|---|---|---|---|
| `control` | Control channel message sent/received | `sdlc_control` | phase, action, refs, size_hint |
| `context_open` | Session opened | `ContextState` | phase, alias, session_hash |
| `context_close` | Session closed | `ContextState` | phase, alias, rounds |
| `state` | State machine state entered | `run_state_machine` | state, iteration |
| `diminishing_returns` | Iteration stopped | `DiminishingReturnsTracker` | reason, delta, iteration |
| `worktree_create` | Worktree created | `sdlc_worktree` | worktree, branch, base_ref |
| `learning_commit` | Structured learning commit recorded | `sdlc_worktree.learning_commit` | state, iteration, worktree, files, feedback_preview |
| `worktree_commit` | Commit made | `sdlc_worktree` | worktree, message, files |
| `worktree_merge` | Branch merged | `sdlc_worktree` | worktree, branch, base_ref |
| `worktree_remove` | Worktree removed | `sdlc_worktree` | worktree |
| `summary` | Summary written | `write_summary` | path, chars, status, elapsed |

All existing v3/v4 events (`pipeline_start`, `phase_start`, `dispatch_*`, `suite_*`, `phase_end`, `pipeline_complete`, `pipeline_failed`, `phase_round_*`, `feedback_*`) remain unchanged and continue to be emitted.

## In-Scope vs Deferred

### In-scope for this design

- Concrete architecture, function signatures, pseudo-code, event contract, file layout, and answers to the six technical questions.
- Worktree lifecycle design with git commit per iteration and structured learning messages.
- Git history capture and plan-phase review so iteration N+1 learns from iteration N.
- State machine states, transitions, and where commits happen (after each EVALUATE state, before REVISE).
- File-reference protocol applied to every phase.
- Context lifecycle via `ContextState`.
- Diminishing returns tracker.
- Required `SUMMARY.md` + `summary` event.

### Deferred to implementation

- Actual git subprocess calls and error handling (mocked in design, real in code).
- Exact quality-score formula (implementation will tune weights).
- UI rendering of new events in `_stderr_callback` (trivial additions, left to implementation).
- Migration of existing `/opt/data/sdlc-test-run-{suite}` temp directories to worktree-based test execution.
- `--worktree` and `--cleanup-on-failure` CLI flags.
- Backward-compatible shim so old `plan(message, plan_output, ...)` callers still work during transition.
- Parser for structured learning-commit message sections (Attempt/Evaluation/Revision/Learnings/Next time) if consumers want to extract them programmatically.

---

# v5 Deep Review — Git-Learning Layer & State Machine Integration

> **Reviewer:** Controller (deepseek-v4-pro:cloud)
> **Date:** 2026-06-28
> **Scope:** 10-point review of the v5 git-learning additions (learning_commit, prepare_git_history, state machine integration, plan phase prompt, event types, concurrency, first-run handling, escaping, missing pieces, overall coherence)
> **Verdict:** Design is sound but has 2 bugs (string escaping, premature commit), 3 gaps (prompt path, first-run handling, error handling), and 1 missing piece (merge conflicts). All fixable in design — no architectural changes needed.

## Finding 1: `learning_commit()` — String Escaping Bug (🔴 Bug)

**Location:** Plan lines 1576-1599, `learning_commit()` function.

**Problem:** The feedback text is embedded directly in a Python triple-quoted f-string:

```python
escaped_feedback = feedback.replace('"', '\\"')[:2000]
message = f"""learn: {state} iteration {iteration}
...
Evaluation:
{escaped_feedback}
...
"""
```

Three issues:

1. **Triple-quote injection:** If `feedback` contains `"""`, it terminates the Python string literal, causing a SyntaxError at runtime. The `replace('"', '\\"')` only handles single double-quotes, not triple sequences.

2. **Unnecessary escaping:** Inside a triple-quoted string, single `"` characters don't need escaping. The `replace('"', '\\"')` is a no-op for correctness but adds literal backslashes to the git commit message (e.g., `He said \"hello\"` instead of `He said "hello"`).

3. **UTF-8 truncation:** `[:2000]` slices on characters, not bytes. Python 3 strings are Unicode-aware so this is actually safe — but if the feedback contains combining characters or grapheme clusters, slicing at index 2000 could split a character sequence. Low risk in practice (ASCII/Latin feedback text).

**Root cause:** Embedding untrusted text in Python string literals is inherently fragile. The correct pattern is string concatenation.

**Fix:**

```python
def learning_commit(
    worktree: str,
    state: str,
    iteration: int,
    feedback: str,
    files: list[str],
    progress_callback: Optional[Callable] = None,
) -> None:
    """Commit a structured learning record after an EVALUATE state drives a revision."""
    # Truncate and sanitize feedback for git commit message.
    # Git commit messages must be valid UTF-8 without null bytes.
    # Truncate to 2000 chars to keep messages manageable.
    safe_feedback = feedback.replace('\x00', '')[:2000]

    # Build message via concatenation — NEVER embed untrusted text in
    # a Python string literal (triple-quote injection risk).
    message = (
        f"learn: {state} iteration {iteration}\n"
        f"\n"
        f"Attempt:\n"
        f"- Produced artifacts in {worktree}/.sdlc/\n"
        f"- State: {state}\n"
        f"- Iteration: {iteration}\n"
        f"\n"
        f"Evaluation:\n"
        f"{safe_feedback}\n"
        f"\n"
        f"Revision:\n"
        f"- Address the evaluation feedback in the next iteration.\n"
        f"- Preserve working decisions; change only the issues noted.\n"
        f"\n"
        f"Learnings:\n"
        f"- Captured from this iteration's evaluation to inform the next round.\n"
        f"\n"
        f"Next time:\n"
        f"- Reference prior learning commits when planning or revising.\n"
        f"- Use structured feedback to avoid repeating the same gaps.\n"
        f"\n"
        f"See HISTORY.md in the worktree for prior iterations.\n"
    )
    git_commit(worktree, message, files)
    # ... progress_callback unchanged ...
```

**Why concatenation is safe:** `subprocess.run` with a list passes each argument as a literal byte sequence to the child process. No shell interpretation occurs. The `\x00` strip prevents null bytes that git rejects. The `[:2000]` truncation is character-safe in Python 3.

## Finding 2: `prepare_git_history()` — `git log --format=%B` Works Correctly (✅ Verified)

**Location:** Plan lines 1614-1638.

**Verification:** `git log --format=%B` outputs the raw commit body (subject + body) for each commit, separated by a blank line. This correctly captures the multi-line structured messages from `learning_commit()`. The output is written to HISTORY.md inside markdown code fences, making it readable by both humans and LLMs.

**Minor issue:** `git log --format=%B` outputs ALL commits on the branch with no delimiter between commits except a blank line. If there are many iterations, the file could be large. Consider adding `--max-count=10` to limit history to recent iterations. Deferred to implementation.

## Finding 3: State Machine — Premature Commit Before Transition Decision (🟡 Gap)

**Location:** Plan lines 1661-1698.

**Problem:** `learning_commit()` is called BEFORE `evaluate_and_transition()`, which means a learning commit is recorded even when `evaluate_and_transition()` decides to go to `COMPLETE` due to diminishing returns. The commit message says "Address the evaluation feedback in the next iteration" but there IS no next iteration.

**Current code:**
```python
elif state == SDLCState.EVALUATE_PLAN:
    feedback = run.plan_result.get('evaluation_feedback')
    if feedback and run.iteration < MAX_ITERATIONS:
        learning_commit(...)                          # ← COMMIT HERE
    state = evaluate_and_transition(run,              # ← THEN decide transition
        SDLCState.REVISE_PLAN, SDLCState.DESIGN_TESTS)
```

**Fix:** Move `learning_commit()` AFTER the transition decision, only when actually going to a REVISE state:

```python
elif state == SDLCState.EVALUATE_PLAN:
    feedback = run.plan_result.get('evaluation_feedback')
    state = evaluate_and_transition(run,
        SDLCState.REVISE_PLAN, SDLCState.DESIGN_TESTS)
    # Only commit learning when we're actually going to revise
    if state == SDLCState.REVISE_PLAN and feedback:
        learning_commit(
            worktree=run.worktree,
            state=SDLCState.PLAN.name,
            iteration=run.iteration,
            feedback=feedback,
            files=[os.path.join(run.worktree, '.sdlc', 'RESEARCH.md')],
            progress_callback=progress_callback,
        )
```

Same pattern applies to `EVALUATE_TESTS` and `REVIEW` states.

## Finding 4: Plan Phase Prompt — Vague File Reference (🟡 Gap)

**Location:** Plan lines 1749-1761.

**Problem:** The prompt says "Review the git history at /worktree" but:
1. The actual file is `/worktree/.sdlc/HISTORY.md` — the prompt should reference the specific path.
2. "Review the git history at /worktree" could cause the subagent to run `git log` itself instead of reading the prepared file.
3. The subagent doesn't know what iteration it's on — the prompt should include the iteration number.

**Fix:**

```python
directive=(
    f"Read the learning history at {history_path}. "
    f"{'This is iteration ' + str(run.iteration) + '. Factor all prior learnings into your plan.' if run.iteration > 1 else 'This is the first iteration — no prior learnings exist.'} "
    f"Inspect the existing codebase for reusable facilities, then write "
    f"a concise implementation plan to {plan_path}. "
    f"Cover: 1) files/functions to reuse, 2) new code needed (KISS/YAGNI), "
    f"3) corner cases, 4) suggested test cases. Do not output the plan in chat. "
    f"{'Explicitly reference what was learned in prior iterations and how this plan addresses those gaps.' if run.iteration > 1 else ''}"
),
```

## Finding 5: `learning_commit` Event — Well-Formed (✅ Verified)

**Location:** Plan lines 1601-1612.

The event carries: `event`, `state`, `iteration`, `worktree`, `files`, `feedback_preview`. This is sufficient for the status callback to render a useful line like:

```
[SDLC] learning_commit: PLAN iteration 1 (plan too brief — missing corner cases)
```

The `feedback_preview` truncation to 120 chars is appropriate for log readability. No changes needed.

## Finding 6: Concurrency — Git Worktrees Are Isolated (✅ Safe)

**Analysis:** Two simultaneous pipelines create separate worktrees on separate branches (e.g., `sdlc/build-palindrome-abc123` and `sdlc/build-fibonacci-def456`). Their git histories are completely isolated — commits on one branch don't affect the other. The learning commits are branch-local.

The known v4 concurrency limitation (shared `__sdlc_*` session registry entries) is unrelated to git and is already documented in the plan (line 496-497). Git worktree concurrency does NOT introduce a new risk.

**One caveat:** If two pipelines somehow get the same branch name (UUID collision — astronomically unlikely with `uuid4().hex[:8]`), `git worktree add -b` would fail. The plan doesn't handle this. Add a retry-with-new-UUID fallback in `create_worktree()`. Deferred to implementation.

## Finding 7: First-Run Git History — Handled but Prompt Should Be Explicit (🟡 Gap)

**Location:** `prepare_git_history()` at plan lines 1614-1638.

**Analysis:** On iteration 1, the worktree is fresh with no commits. `git log --oneline` and `git log --format=%B` both return empty strings. `prepare_git_history()` writes:

```
# SDLC Learning History

## Oneline

```

```

## Full Commit Messages

```

```

```

This is valid — the file exists but contains no history. The plan phase subagent reads it and sees empty history, which correctly signals "first iteration."

**Gap:** The plan phase prompt (line 1754) says "Review the git history at /worktree for lessons from prior iterations" with no handling for the empty case. The subagent might waste time trying to find history that doesn't exist, or might hallucinate learnings.

**Fix:** See Finding 4 — the prompt should explicitly state the iteration number and whether history exists. The `build_control_message` function should check if HISTORY.md has content and adjust the directive accordingly.

## Finding 8: Commit Message Escaping — Subprocess List Is Safe, But Null Bytes Are Not (🔴 Bug)

**Location:** `git_commit()` at plan lines 1552-1560.

**Analysis:** `subprocess.run(['git', 'commit', '-m', message], ...)` passes `message` as a single list element. The shell is NOT invoked (no `shell=True`), so shell metacharacters (`$`, `!`, `#`, `;`, `|`, backticks) are passed literally and pose no risk. This is correct and safe.

**However:** Git commit messages cannot contain null bytes (`\x00`). If the feedback text (which flows into the commit message via `learning_commit`) contains a null byte, `git commit` will fail with a cryptic error. The fix in Finding 1 includes `feedback.replace('\x00', '')` to strip null bytes.

**Newlines:** Multi-line commit messages with a single `-m` flag are valid in git. The first line becomes the subject, subsequent lines become the body. This is the intended behavior for structured learning commits.

**Semicolons and other metacharacters:** Safe because `subprocess.run` with a list doesn't invoke the shell.

## Finding 9: Missing Pieces

### 9a. Git Commit Failure Handling (🟡 Gap)

**Location:** `git_commit()` at plan lines 1552-1560.

```python
def git_commit(worktree: str, message: str, files: list[str]) -> None:
    if not files:
        return
    subprocess.run(['git', 'add'] + files, cwd=worktree, check=True)
    try:
        subprocess.run(['git', 'commit', '-m', message], cwd=worktree, check=True)
    except subprocess.CalledProcessError:
        # Nothing to commit — ignore
        pass
```

**Problems:**
1. The `except` clause catches ALL `CalledProcessError` but the comment says "Nothing to commit." Other failures (lock file, permission denied, disk full, detached HEAD) are silently swallowed.
2. `git add` can also fail (no such file, permission denied) — no error handling.
3. If `git add` succeeds but `git commit` fails for a non-empty reason, the staged changes are left in the index, polluting the next commit attempt.

**Fix:**

```python
def git_commit(worktree: str, message: str, files: list[str]) -> bool:
    """Stage and commit files. Returns True on success, False if nothing to commit.
    Raises subprocess.CalledProcessError on real failures (lock, permissions, etc.)."""
    if not files:
        return False
    # Only add files that exist (subagent might not have written all expected files)
    existing = [f for f in files if os.path.exists(f)]
    if not existing:
        return False
    subprocess.run(['git', 'add'] + existing, cwd=worktree, check=True,
                   capture_output=True, text=True)
    result = subprocess.run(
        ['git', 'commit', '-m', message],
        cwd=worktree, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True
    if 'nothing to commit' in result.stderr or 'nothing added' in result.stderr:
        # Unstage the added files to keep index clean
        subprocess.run(['git', 'reset', '--'] + existing, cwd=worktree,
                       capture_output=True, text=True)
        return False
    # Real failure — let it propagate
    result.check_returncode()
    return False  # unreachable
```

### 9b. Empty Commit (✅ Handled)

The "nothing to commit" case is already caught. With the fix above, it's handled explicitly and the index is cleaned up.

### 9c. Merge Conflicts (🔴 Missing)

**Location:** `merge_worktree_to_main()` at plan lines 1640-1642.

```python
def merge_worktree_to_main(worktree: str, branch: str, base_ref: str = 'main') -> None:
    subprocess.run(['git', 'checkout', base_ref], cwd=REPO_ROOT, check=True)
    subprocess.run(['git', 'merge', '--no-ff', branch, '-m', f"Merge {branch}"], cwd=REPO_ROOT, check=True)
```

**Problem:** If `main` has advanced since the worktree was created, `git merge` can fail with conflicts. The `check=True` will raise `CalledProcessError` and crash the pipeline at the very end, after all the work is done. This is the worst time to crash.

**Fix:** Add merge conflict detection and fallback:

```python
def merge_worktree_to_main(worktree: str, branch: str, base_ref: str = 'main') -> dict:
    """Merge worktree branch to main. Returns {'merged': True/False, 'error': str}."""
    try:
        subprocess.run(['git', 'checkout', base_ref], cwd=REPO_ROOT,
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        return {'merged': False, 'error': f'Checkout failed: {e.stderr[:200]}'}
    result = subprocess.run(
        ['git', 'merge', '--no-ff', branch, '-m', f'Merge {branch}'],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return {'merged': True, 'error': None}
    # Conflict or other failure — abort merge, leave branch for manual review
    subprocess.run(['git', 'merge', '--abort'], cwd=REPO_ROOT,
                   capture_output=True, text=True)
    return {
        'merged': False,
        'error': f'Merge conflict: {result.stderr[:500]}',
        'branch': branch,
        'worktree': worktree,
    }
```

The pipeline should emit a `worktree_merge_failed` event and include the branch name in the summary so the user can manually merge.

### 9d. Diminishing Returns + Learning Commit Interaction (🟡 Gap)

**Location:** Interaction between `DiminishingReturnsTracker` and `learning_commit()`.

**Scenario:** The tracker detects a plateau (same feedback twice) and `evaluate_and_transition()` returns `COMPLETE`. But `learning_commit()` was already called (see Finding 3). The commit message says "Address the evaluation feedback in the next iteration" but the pipeline stops.

**Fix:** Finding 3's fix (move commit after transition decision) resolves this. Additionally, when the tracker triggers, emit a `diminishing_returns` event with the reason, and include the plateau detection in the final SUMMARY.md.

## Finding 10: Overall Coherence (✅ Sound)

**Assessment:** The git-learning layer integrates cleanly with the v5 design:

| Concept | Integration | Status |
|---|---|---|
| Control channel | Plan prompt references HISTORY.md path; subagent reads it via file tools | ✅ Coherent |
| Context lifecycle | Learning commits are orthogonal to session lifecycle — they're git operations, not session state | ✅ Clean separation |
| State machine | Commits happen at EVALUATE→REVISE transitions (after fix #3) | ✅ Fixed |
| Worktrees | Each pipeline has its own worktree+branch; commits are isolated | ✅ Safe |
| File-reference protocol | HISTORY.md is a file in the worktree; plan prompt references it by path | ✅ Coherent |
| Diminishing returns | Tracker stops iteration; learning commits only happen on actual retries (after fix #3) | ✅ Fixed |
| Summary | SUMMARY.md includes iteration count and key decisions from learning commits | ✅ Coherent |

**No contradictions found.** The design is internally consistent after the fixes above.

## Review History

| Reviewer | Model | Date | Verdict | Key Issues |
|---|---|---|---|---|
| Kimi | kimi-k2.7-code:cloud | 2026-06-28 | Architecture sound, ship with fixes | Thread lock, dispatch_comparison plumbing, test mocks, early-return coverage, --quiet flag, callback exception handling |
| DeepSeek | deepseek-v4-pro:cloud | 2026-06-28 | Ship with fixes below | Double-emission bug, early-return count wrong, missing `import threading`, `_stderr_callback` missing dispatch handlers, `_safe_callback` location unspecified, `dispatch_comparison` line numbers off by 2, test plan underspecified |
| Controller | deepseek-v4-pro:cloud | 2026-06-28 | Ship with v4 fixes below | 2 bugs (evaluator crash, max_rounds=1 edge case), 5 gaps (evaluator signature, missing evaluate_council, missing PHASE_EVALUATORS, alias collision, context math), 2 missing pieces (session cleanup, concurrent safety documented) |
| Controller | kimi-k2.7-code:cloud | 2026-06-28 | Architecture extension v5 — logical control channel, context lifecycle, iterative state machine, worktrees, file-reference protocol | 6 new architectural concepts incorporated into v5 extension below |
| Controller | deepseek-v4-pro:cloud | 2026-06-28 | v5 git-learning layer: ship with 2 bugfixes + 3 gap fixes | 2 bugs (triple-quote injection in learning_commit, premature commit before transition decision), 3 gaps (vague plan prompt path, no first-run handling, git error handling too broad), 1 missing piece (merge conflict handling) — all fixes integrated above |

## Summary

This v5 extension turns the SDLC orchestrator into an iterative, context-aware state machine running inside isolated git worktrees. The orchestrator communicates with subagents through a logical control channel (short prompts with file paths), manages session lifecycles explicitly, detects diminishing returns to stop iteration, and always produces a final summary that teaches how the new system works. The next step is to implement `sdlc_worktree.py`, `sdlc_control.py`, `sdlc_state.py`, and the refactored phase functions in `sdlc.py`.

SUGGESTION:{"next": "Create a follow-up task to implement the v5 design files (sdlc_worktree.py, sdlc_control.py, sdlc_state.py) and refactor sdlc.py phase functions to the file-reference protocol", "reason": "The design is complete and concrete; implementation requires writing new modules and updating existing signatures in sdlc.py, model_utils.py, and pipeline.py", "can_do": true}
