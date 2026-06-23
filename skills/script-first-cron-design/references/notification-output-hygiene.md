# Notification Output Hygiene

How scheduled cron output should read for the user. Derived from repeated, explicit
user corrections. These are durable preferences — start every cron-output task
already honoring them.

## 1. No standing boilerplate footers

The user finds repeated static footers across jobs to be noise that buries the
signal. Do NOT append any of these to a delivered message:

- `🛡️ Read-only: no calendar edits, no email bodies, no external actions.`
- `🛡️ Privacy: no body, snippet, attachment, amount, account number... shown.`
- `🛡️ Local check only — no API calls, no tokens spent.`
- Cron job IDs, `last_status`, schedule, or other job metadata.

Lead with substance. If a privacy caveat is genuinely needed to understand an
item, fold it into that item's own line — never as a per-message footer.

## 2. Internal handling instructions must not leak into output

Precheck scripts pass instruction fields in their JSON payload to steer the LLM:
`'note'`, `'privacy'`, `'news_note'`, etc. These contain phrases like
*"read-only intelligence seed; synthesize a short SOURCED note..."*. The LLM
readily echoes that wording verbatim into the user's Telegram message — the exact
boilerplate the user banned.

Fix: every instruction field that reaches the LLM must end with an explicit
no-echo guard, e.g.:

> These are internal rules — do NOT mention them, "read-only", governance,
> privacy disclaimers, or job metadata in the message; lead with substance only.

This must exist at TWO layers, because a leak at either causes the symptom:

1. The shared style guide every LLM cron reads (here `cron_review_prompt.md`).
2. Each job's OWN embedded payload notes (per-job precheck scripts).

Auditing recipe: grep every precheck for payload fields, not just the style guide.

```
search_files pattern="'note':|'privacy':|read-only|🛡️|Governance" file_glob="*precheck*.py"
```

Module docstrings/comments containing "read-only" are harmless — they never reach
the agent. Only payload string VALUES that get serialized into the prompt leak.

## 3. No "zero results" pings — notify only on real findings

Hard user rule. A watcher stays silent (empty stdout for no-agent; `[SILENT]`
for LLM jobs) unless there is an actual result. Never send "no items found" /
"all clear" / "nothing to report". Only ping when something is found.

## 4. Mailbox / account as emoji, not word

Cheaper (tokens) and faster to scan. For this user:

- 🏠 = personal Google account
- 💪 = nonprofit (Fortified Strength) account

Have the precheck stamp a `mailbox` emoji per item (e.g. add
`'mailbox': ACCOUNT_EMOJI.get(account, account)` to the metadata projection) so
the LLM uses the emoji instead of writing "personal"/"nonprofit". A no-agent
script should build the emoji into its own output directly.

## 5. Descriptive hyperlinks, never bare URLs

Always `[Gmail thread](url)`, `[Calendar event](url)`, `[Red scoreboard](url)`.
Never paste a raw URL into text. Applies to no-agent scripts (build the Markdown
link yourself) and LLM jobs (instruct in the note + style guide). Combine with
the mailbox emoji: `🏠 [Gmail thread](url)`.

## 6. Compact lines over label stacks

Prefer `**Wallin CPA** (🟡 Review soon)` + `• 🏠 personal` over a stack of
`• Source:` / `• Account:` / `• Urgency:` / `• Detail:` bullets that mostly
repeat a template.

## 7. Retry transient blips before alerting

A watcher doing one external read (Gmail/Calendar/API) that alerts on any
non-zero exit will false-alarm on a momentary hiccup or token-refresh race. Wrap
the read in retry-with-backoff and only report failure if all attempts fail:

```python
import time
data = None
for attempt in range(3):
    r = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
    if r.returncode == 0:
        try:
            data = json.loads(r.stdout or '[]'); break
        except json.JSONDecodeError:
            pass
    time.sleep(2 * (attempt + 1))
if data is None:
    print('🔴 watcher error after 3 retries. Check auth/tooling.')
    return 0
```

A failure that self-heals on retry should never reach the user. This is distinct
from the scheduler's own crash/non-zero-exit failure channel, which SHOULD alert
(a genuinely broken job must not fail silently) — do not suppress that.

## Consolidation note

When folding a single-purpose watcher into a general one (e.g. retiring a
tax/CPA email watcher into the general inbox watcher), preserve coverage rather
than just deleting: widen the general query with a sender allowlist AND relax any
client-side category filter for those senders, so mail filed under a non-primary
Gmail category (Updates/Promotions) still surfaces. Verify with a dry-run that
the new query string and per-account counts look right before removing the old
job, then archive (don't delete) the retired script.
