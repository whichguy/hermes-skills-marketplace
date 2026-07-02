# Stale Session Auto-Recovery

## Problem

When `ask kimi "prompt"` was run, it auto-resumed a stale session ID (`sid_456`)
from `~/.hermes/ask-sessions.json`. That session was test garbage and didn't
exist in Hermes' session store, so `hermes chat --resume sid_456` failed with:

```
Session not found: sid_456
```

The result was empty output — a hard failure with no recovery.

## Root Cause

`_run_agent_mode()` in `ask.py` (line 533-537) auto-resumes sessions by alias:

```python
resume_id = args.resume
if not resume_id and alias_key:
    session_info = get_session(alias_key)
    if session_info:
        resume_id = session_info["session_id"]
```

If the sessions file has a stale entry (test garbage, pruned session, DB reset),
the resume fails and the call returns empty output.

## Fix (Jun 2026)

Two changes in `model_utils.py`:

### 1. `_remove_session()` helper (lines 408-428)

```python
def _remove_session(alias: str) -> None:
    """Remove a stale alias from the sessions registry."""
    try:
        with open(SESSIONS_FILE) as f:
            sessions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if alias in sessions:
        del sessions[alias]
        with open(SESSIONS_FILE, 'w') as f:
            json.dump(sessions, f, indent=2)
```

### 2. Resume fallback in `dispatch_single()` (lines 576-598)

When `--resume` fails with "Session not found" in stderr:

1. Strips `--resume <id>` from the command
2. Removes the stale alias via `_remove_session(alias)`
3. Retries the call fresh (no resume)
4. Sets `resume_session = None` so the new session saves correctly

```python
if "Session not found" in result.stderr:
    # Build command without --resume
    fresh_cmd = [arg for i, arg in enumerate(cmd) if arg != "--resume" and (i == 0 or cmd[i-1] != "--resume")]
    _remove_session(alias)
    result = subprocess.run(fresh_cmd, capture_output=True, text=True, timeout=timeout)
    resume_session = None
```

## Verification

- `_remove_session()` correctly removes entries and preserves others
- Missing file and missing alias are no-ops (no exception)
- `ask kimi "Say hello"` succeeds in 6.2s after fix (was failing with empty output)
- 115/115 non-live tests pass
- 3 stale test entries cleaned from `ask-sessions.json` (kimi, deepseek, test)
