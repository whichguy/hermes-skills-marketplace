# Cron Message House Style + Subprocess False-Alarm Fix

Session-derived detail for making cron/daily-update messages pretty, clickable, and
correct. Applies to both `no_agent` script output and LLM briefs.

## House style (Telegram, converted from standard Markdown)

A shared formatter module (e.g. `${HERMES_HOME}/scripts/cron_style.py`) keeps every job
consistent and lets future tweaks happen in one place. Core elements:

- **Header:** emoji + bold title + italic subtitle/timestamp, then a `━━━━━━━━━━━━━━━` divider.
  Example: `⚽ *World Cup — Daily Update*` / `_Saturday, June 13 · 8:15 AM PDT_`.
- **Sections:** emoji + bold label (`📅 *Today's Schedule*`).
- **Bullets:** `• ` lead; bold the label half of `key: value` lines (`• *Time:* ...`).
- **Status icons, consistent meaning everywhere:** 🟢 ok/safe, 🟡 needs care/soon,
  🔴 high/approval-sensitive or failure, ⚪ info-only/FYI.
- **Clickable links — required.** Every referenced item is `[descriptive text](url)`,
  never a bare URL and never a plain label when a URL exists:
  - Google Calendar event → event `htmlLink` field.
  - Gmail → `https://mail.google.com/mail/u/0/#search/<urlencoded query>`.
  - Drive → file `webViewLink`.
  - World Cup → ESPN scoreboard/standings pages (human pages, not the JSON API URLs).
  - Hermes/Docker update guard → Docker Hub tags page + Hermes docs.
- **Footer:** italic privacy/source line (`🛡️ _Read-only: no calendar edits._`,
  `📊 _Live data from ESPN. Times in Pacific._`).
- Times always in the user's local zone (`America/Los_Angeles`), friendly labels, no raw UTC/ISO.

This is a standing user preference: "make them very pretty, formatted, using emojis and
hyperlinking key things so I can click back to the items referenced."

## Pitfall: subprocess-dependency crash misreported as a domain error

Symptom seen in this session: the Google auth guard delivered
`🔴 nonprofit: invalid_grant — re-auth needed` while credentials were actually valid.

Root cause: the guard ran `subprocess.run(['python', 'setup.py', '--account', a, '--check'])`
with the bare interpreter, which lacks `googleapiclient`. The check crashed with
`ModuleNotFoundError: No module named 'googleapiclient'`, and the classifier's catch-all
mapped any non-`AUTHENTICATED` output to an auth failure. The real cron path works because
it wraps calls in `uv run --with google-api-python-client --with google-auth-oauthlib
--with google-auth-httplib2`.

### Fix pattern (verified)

```python
UV_GOOGLE_DEPS = [
    'uv', 'run',
    '--with', 'google-api-python-client',
    '--with', 'google-auth-oauthlib',
    '--with', 'google-auth-httplib2',
]

def check(alias):
    cmd = ['python', str(SETUP), '--account', alias, '--check']
    attempts = [cmd, UV_GOOGLE_DEPS + cmd]
    last_output = ''
    for attempt in attempts:
        result = subprocess.run(attempt, text=True, capture_output=True, timeout=180)
        output = (result.stdout or '') + (result.stderr or '')
        if result.returncode == 0 and 'AUTHENTICATED' in output:
            return None
        last_output = output
        if 'ModuleNotFoundError' in output or 'No module named' in output:
            continue  # retry through uv before judging
        return classify(output)
    return classify(last_output)
```

Verification: run the script directly. A healthy guard should be **silent (empty stdout,
exit 0)**. If it still prints a domain error after the uv retry, that error is real.

General rule: any script-only watchdog that shells out to another tool must run that tool
in the dependency environment the tool actually needs, and must distinguish
"could not run the check" from "the check ran and reports a problem." Never deliver a
plumbing failure as a substantive alert.

## LLM-review layer

The user wants script-only outputs additionally reviewed by an LLM before delivery to catch
false alarms like the above. Convert judgment-sensitive guards (auth, tax/CPA,
calendar/travel, update) to precheck-script + LLM-review (`no_agent: false`) so a model can
sanity-check the draft, fix obvious errors, flag `⚠️ needs attention`, and apply the house
style with clickable links — while staying silent when nothing is actionable. Keep trivial
high-frequency watchdogs pure `no_agent` to control cost; confirm scope with the user.
