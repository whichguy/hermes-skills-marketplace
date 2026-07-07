# Stdout Contamination from `sitecustomize.py` — JSON Parsing Fix

## Problem

A `sitecustomize.py` module (slack-enhancements, profiling, coverage) prints a
banner to **stdout** on every Python invocation:

```
[slack-enhancements] sitecustomize loaded — patches deferred to gateway:startup hook
```

Precheck scripts that call `subprocess.run(['python', 'google_api.py', ...])` and
then `json.loads(r.stdout)` fail with `JSONDecodeError` because the banner text
precedes the JSON payload.

## Why it's insidious

1. **The banner starts with `[`** — the same character as a JSON array. A naive
   "find the first `[` in stdout" extraction grabs the banner, not the JSON.
   `stdout.index('[')` returns 0 (the `[` in `[slack-enhancements]`), not the
   `[` that starts the actual JSON array.

2. **`except Exception: break` kills the fallback.** The original `run()` pattern
   had a `uv run --with <deps>` fallback attempt for `ModuleNotFoundError`, but
   the broad `except Exception: break` caught `JSONDecodeError` (a subclass of
   `ValueError` → `Exception`) and broke out of the loop before the uv attempt
   was tried. The script reported `command_failed: JSONDecodeError` instead of
   either succeeding via uv or reporting the real `ModuleNotFoundError`.

3. **All siblings break simultaneously.** Since the banner is global (every
   `python` invocation), ALL precheck scripts (`inbox_triage`, `followup_sweep`,
   `email_wiki`) fail at the same time with the same error. This looks like a
   systemic Google auth failure when credentials are actually fine.

## Fix: `_extract_json()` helper

```python
def _extract_json(stdout):
    """Extract JSON from stdout that may have non-JSON preamble (e.g. sitecustomize)."""
    if not stdout:
        return '[]'
    # The sitecustomize banner '[slack-enhancements] ...' starts with '[' too.
    # The real JSON starts on a line that is just '[' or '{' (google_api.py
    # pretty-prints). We track byte offset as we iterate lines so we don't
    # confuse the banner '[' with the JSON '['.
    offset = 0
    for line in stdout.splitlines(keepends=True):
        if line.strip() in ('[', '{'):
            return stdout[offset:]
        offset += len(line)
    # Fallback: find '[' followed by newline (pretty-printed array), or
    # first '{' (the banner never contains '{', so any '{' is the JSON start)
    for i, ch in enumerate(stdout):
        if ch == '[' and i + 1 < len(stdout) and stdout[i + 1] == '\n':
            return stdout[i:]
        if ch == '{':
            return stdout[i:]
    return stdout  # let json.loads fail with the original
```

Key design decisions:
- **Byte offset tracking** with `splitlines(keepends=True)` — not
  `stdout.index(line)` which finds the FIRST occurrence of that line's text
  (the banner `[` line would match before the JSON `[` line).
- **`line.strip() in ('[', '{')`** — the JSON start is a line containing only
  `[` or `{` because `google_api.py` uses `json.dumps(indent=2)`. The banner
  line `[slack-enhancements]...` does not match because it has more content.
- **Fallback `{` anywhere** — the banner never contains `{`, so the first `{`
  in stdout is always the JSON start. This handles compact single-line objects
  like `{"status": "ok"}` where `{` is followed by `"` not `\n`.
- **Fallback `[` followed by `\n`** — distinguishes `[banner...]` (followed by
  more text) from the JSON `[\n  {` (followed by newline).

## Fix: `run()` exception handling

```python
def run(cmd):
    """Run a Google API command, retrying through uv when local deps are absent."""
    attempts = [cmd]
    if cmd and cmd[0] == 'python':
        attempts.append(UV_GOOGLE_DEPS + cmd)
    last_error = None
    for attempt in attempts:
        try:
            r = subprocess.run(attempt, text=True, capture_output=True, timeout=90)
            if r.returncode == 0:
                return json.loads(_extract_json(r.stdout))
            last_error = (r.stderr or r.stdout or '').strip()[-400:]
            if 'ModuleNotFoundError' not in last_error:
                break
        except json.JSONDecodeError:
            # stdout had non-JSON content — try next attempt (e.g. uv fallback)
            last_error = 'JSONDecodeError'
            continue
        except Exception as e:
            last_error = type(e).__name__
            continue
    return {'error': 'command_failed', 'detail': last_error}
```

Key change: `except json.JSONDecodeError: continue` (not `break`) so the uv
fallback attempt is still tried. The generic `except Exception` also uses
`continue` instead of `break` for the same reason.

## Second failure mode: banner delivered as cron message (Jun 2026)

The JSON-parsing fix above handles subprocess calls within precheck scripts. But
there is a **second, more severe failure mode**: `sitecustomize.py` prints to
**stdout** on every Python invocation, and `no_agent` cron scripts deliver stdout
verbatim to Telegram/Slack. This means **every cron job that runs Python** sends
the banner text `[slack-enhancements] sitecustomize loaded…` as a user message.

### How it manifests

- Every `no_agent: true` cron job delivers the banner text to the user's chat
- High-frequency jobs are catastrophic: NCW alerts (`* * * * *`) sent **12,624
  messages** (one per minute for ~9 days) before detection
- 14 different cron jobs were simultaneously affected
- The banner appears in cron output files (`cron/output/<job_id>/*.md`)

### Why the JSON fix doesn't help here

The `_extract_json()` helper strips the banner from subprocess stdout *inside*
precheck scripts. But for `no_agent` cron scripts, the banner is on the script's
**own stdout** — there's no JSON to extract, the entire stdout IS the banner.
The cron scheduler delivers it verbatim.

### Fix: redirect sitecustomize print to stderr

The root cause is `sitecustomize.py` using `print()` (stdout) instead of
`print(..., file=sys.stderr)`:

```python
# BAD — contaminates every cron job's stdout
print("[slack-enhancements] sitecustomize loaded…", flush=True)

# GOOD — banner logs to stderr, cron delivers stdout only
print("[slack-enhancements] sitecustomize loaded…", file=sys.stderr, flush=True)
```

Cron's `no_agent` delivery path only reads stdout, so stderr banners are invisible
to the user. The banner still appears in logs for debugging.

### Detection pattern

When a user reports "keeps looping" or "getting the same message repeatedly":
1. Check `cron/output/<job_id>/*.md` files for a repeated banner line
2. `grep -r "sitecustomize\|slack-enhancements" /opt/data/cron/output/*/`
3. Check agent.log for repeated deliveries from the same job_id
4. Look for `* * * * *` (every-minute) schedules — these amplify contamination

### Cleanup

After fixing `sitecustomize.py`, delete contaminated cron output files:
```bash
find /opt/data/cron/output/<job_id>/ -name "*.md" -delete
```
These files contain only the banner text — no real alert content was lost.

## Scripts affected (as of Jun 2026)

All three precheck scripts that call `google_api.py` via subprocess were patched
for the JSON-parsing variant:

- `scripts/inbox_triage_precheck.py` — `run()` + `_extract_json()`
- `scripts/followup_sweep_precheck.py` — `run()` + `_extract_json()`
- `scripts/email_wiki_precheck.py` — `fetch_messages()` + `fetch_body()` both use `_extract_json()`

The second failure mode (banner-as-message) was fixed at the source:
- `${HERMES_HOME}/scripts/slack-patches/sitecustomize.py` — `print()` → `print(file=sys.stderr)`
- This single fix resolved contamination for ALL 14 affected cron jobs simultaneously

## Debugging path that led to the fix

1. Precheck payload showed `errors: [{account: personal, error: command_failed, detail: JSONDecodeError}, ...]` for both accounts.
2. Ran `setup.py --check` → `AUTHENTICATED` (credentials fine).
3. Ran `google_api.py gmail labels` directly → `ModuleNotFoundError: No module named 'googleapiclient'` (system Python lacks deps).
4. Ran via `uv run --with ...` → success (deps available through uv).
5. Concluded: the `run()` function's uv fallback was never being reached.
6. Reproduced: `python google_api.py ... 2>/dev/null` showed the `[slack-enhancements]` banner in stdout, before the JSON.
7. Confirmed: `json.loads(stdout)` fails because the banner starts with `[` but isn't JSON.
8. Confirmed: `except Exception: break` catches `JSONDecodeError` and exits the loop before the uv attempt.

## Verification approach

Ad-hoc test script covering:
- `_extract_json` strips banner before JSON arrays and objects
- `_extract_json` handles empty/None stdout
- `_extract_json` passes through clean JSON (no preamble)
- Live `run()` calls succeed against real Gmail for both accounts
- `email_wiki_precheck._extract_json` parses real `google_api.py` stdout with banner

All 18 checks passed. Temp script cleaned up after.