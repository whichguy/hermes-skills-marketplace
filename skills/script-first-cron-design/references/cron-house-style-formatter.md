# Shared Cron Output House Style

When a user wants cron/scheduled updates to look "pretty" and consistent —
emojis, hyperlinked references, friendly local time — do NOT hand-format each
script independently. That drifts immediately and is painful to retune. Build
ONE shared formatter module that every script-only job imports, plus a matching
style block in the prompt for LLM-driven briefs.

This pattern was requested by Jim: pretty, emoji-headed, clickable updates where
key referenced items (calendar events, Gmail threads, Drive docs, scoreboards)
are descriptive Markdown hyperlinks he can click back to.

## The module

A reusable formatter ships with this skill at `scripts/cron_style.py`. Copy it
into the deployment's scripts directory (e.g. `${HERMES_HOME}/scripts/cron_style.py`)
so sibling cron scripts can `import cron_style as cs`.

Helpers it provides:

- `local_time(value, with_date=True)` → friendly Pacific label, never raw UTC/ISO.
- `now_label()` → "Saturday, June 13 · 8:15 AM PDT" for headers.
- `link(text, url)` → `[text](url)`, falls back to plain text when url is None.
- `header(emoji, title, subtitle=None)` → emoji title + `━━━` divider.
- `section(emoji, title)`, `bullet(text, icon=None)`, `kv(label, value, icon=None)`.
- `footer(text)`, `render(blocks)` to join.
- Status icon vocabulary: `ICON_OK 🟢`, `ICON_WARN 🟡`, `ICON_HIGH 🔴`, `ICON_INFO ⚪`.

## House-style rules (keep consistent across ALL jobs)

1. **Emoji-headed title** + a `━━━` divider line; optional italic subtitle.
2. **Bold labels** (`*Time:*`, `*Event:*`) with the value after.
3. **Hyperlink every reference** with descriptive link text, never a bare URL:
   `[Google Calendar event](...)`, `[Gmail Inbox search](...)`,
   `[Drive doc](...)`, `[ESPN scoreboard](...)`. Prefer the human-clickable
   interface over the raw API URL.
4. **Friendly Pacific time** always; scheduler UTC is internal-only.
5. **Status icons** 🟢🟡🔴⚪ with consistent meaning everywhere.
6. **Preserve privacy/read-only footers** that already exist (e.g. "no body,
   amount, or confirmation number was read or shown").
7. No tables — Telegram has none. Headings + bullets only.

## Where the link comes from per source

- Google Calendar events: use the event `htmlLink` field returned by the
  calendar list (`google_api.py` already returns `htmlLink`).
- Gmail: build a search deep link
  `https://mail.google.com/mail/u/0/#search/<url-quoted query>`.
- Drive: use `webViewLink` from the Drive search results.
- External data (ESPN etc.): link the public human-facing page, not the
  `site.api.espn.com` JSON endpoint.

## LLM-driven briefs

Script-only jobs import the module. For LLM briefs (morning brief, watchlist),
embed the same rules as a "Clickable-link rule" + house-style block in the cron
prompt so the model emits the identical look. The precheck script must pass the
links (htmlLink/webViewLink/deep links) through in its JSON so the LLM has real
URLs to hyperlink rather than inventing them.

## Verification

Render a dry-run sample before wiring all scripts — assemble each job's blocks
and `print` once; eyeball the Telegram-converted look and get approval on the
aesthetic ONCE, then apply across every script. Avoids per-file aesthetic churn.

Note: emoji + variation-selector content can trip the terminal security scanner
(MEDIUM "variation selector characters detected"); it's benign for emoji output.
