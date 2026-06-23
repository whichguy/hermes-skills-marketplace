---
name: messaging-platform-formatting
description: Format assistant responses for messaging-platform gateways such as Telegram,
  WhatsApp, Signal, Slack, Discord, and email; verify Hermes platform hints/formatters
  when behavior is unclear.
version: 1.0.0
author: Hermes Agent
license: MIT
tags:
- messaging
- telegram
- formatting
- markdown
- gateway
- hermes
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    config:
    - key: messaging-platform-formatting.enabled
      description: Enable messaging-platform-formatting skill behavior
      default: true
      prompt: Enable messaging-platform-formatting skill?
    tags:
    - messaging
    category: productivity
---
---

# Messaging Platform Formatting

Use this skill when the user asks how responses should be formatted on a messaging platform, notices poor rendering in Telegram/Discord/Slack/etc., or asks whether a Hermes setting controls output formatting.

## Core approach

1. **Identify the active delivery platform.** The system prompt may already include a platform-specific hint. Treat it as authoritative for final-response shape.
2. **Prefer platform-native readability over generic Markdown.** On mobile chat clients, concise headings and bullets are usually clearer than tables or dense prose.
3. **Check both layers when researching Hermes formatting behavior:**
   - Prompt guidance: `agent/prompt_builder.py` and `agent/system_prompt.py` platform hints.
   - Delivery formatter: platform adapter under `gateway/platforms/<platform>.py`.
4. **Do not assume CLI display settings affect gateway formatting.** Settings such as `display.final_response_markdown` can be CLI/TUI-oriented; verify the gateway adapter path before recommending a config change.
5. **Report findings as operational guidance, not just code trivia:** tell the user what to do differently in replies and whether any config change is actually needed.

## Telegram response style

For Telegram, use standard Markdown in the final response and let Hermes convert it to Telegram MarkdownV2. Keep the source response Telegram-friendly:

- Use short `##` headings when helpful.
- Use bullets and labeled `key: value` lines.
- Use `**bold**` for labels or important terms.
- Use `inline code` and fenced code blocks for commands, paths, logs, or snippets.
- Use normal Markdown links: `[label](url)`.
- For daily briefs, cron updates, alerts, and watchlist summaries, prefer clickable text links over bare URLs whenever a useful interface exists: `[Google Calendar event](...)`, `[Gmail Inbox search](...)`, `[Drive doc](...)`, `[ESPN scoreboard](...)`, `[Docker Hub tag](...)`. Link the human-usable interface, not just an API endpoint.

### Jim's mandatory hyperlink rules (every response, not just briefs)

These are **non-negotiable** — Jim corrected these twice in one session:

1. **Business/place names** — always hyperlink to the business website: `[VASA Fitness](https://vasafitness.com/...)`
2. **Addresses** — always hyperlink to Google Maps: `[7655 N Union Blvd, Venue City](https://maps.google.com/?q=...)`
3. **Phone numbers** — always wrap in `tel:` link: `[(555) 123-4567](tel:5551234567)`
4. **Event times/dates** — always hyperlink to a pre-populated Google Calendar add-event URL (see `references/google-calendar-deeplink.md` for the URL template)
5. **Never raw URLs** — always use `[named label](url)` format

Missing any of these is a formatting error. Apply to ALL responses, not just recommendations or briefs.
- Avoid pipe tables. Telegram has no table syntax; use row groups instead.
- Keep paragraphs short; Telegram is read on mobile more often than a terminal.
- For recommendation-heavy replies, lead with the recommendation rather than a list of questions.
- Use risk/status emojis to make review items scannable: 🟢 low/safe, 🟡 medium/needs care, 🔴 high/approval-sensitive, ⚪ info-only.
- Always include compact quick-reply options when asking the user to choose, so they can answer with `A`, `B`, `C` or `1`, `2`, `3`.
- Avoid making the user answer many separate questions. Collapse choices into one recommended path plus alternatives.

### Recommendation card pattern

Use this shape when recommending skills, memories, cron changes, approvals, or next actions:

```markdown
## 🟢 Recommendation

**Do:** approve the safe/default action.
**Risk:** 🟢 Low
**Why:** one short sentence.

## Quick reply

**A** — Approve recommended path
**B** — Show details first
**C** — Stop / change direction
```

Example instead of a table:

```markdown
## Results

**Alpha**
- Status: ok
- Notes: ready

**Beta**
- Status: blocked
- Notes: waiting on access
```

## Hermes verification checklist

When asked whether Hermes has a setting for platform formatting:

1. Load the `hermes-agent` skill first, because this is Hermes configuration/troubleshooting.
2. Inspect platform hints and adapter formatter behavior if source is available.
3. Check the active config only for relevant display/gateway settings; redact secrets if showing output.
4. Distinguish between:
   - **Model guidance**: platform hint injected into the system prompt.
   - **Transport conversion**: adapter converting standard Markdown to platform-specific markup.
   - **User preference**: concise, readable final-response structure.
5. If no config change is needed, say so directly and provide the preferred response pattern.

## Hermes Telegram implementation map

When modifying or debugging Hermes Telegram formatting, the relevant files are:

- **Platform guidance:** `agent/prompt_builder.py`, `PLATFORM_HINTS["telegram"]`
- **Formatter:** `gateway/platforms/telegram.py`, `TelegramAdapter.format_message()` + helpers `_escape_mdv2()`, `_strip_mdv2()`, `_wrap_markdown_tables()`
- **Tests:** `tests/gateway/test_telegram_format.py`

**Enhancement workflow:** (1) Check platform hint first — if the formatter supports a construct but the hint omits it, patch the hint. (2) When adding formatter behavior, protect code spans/blocks before conversion, add conversion before generic MarkdownV2 escaping. (3) Preserve dynamic content safety: escape with `_escape_mdv2()`. (4) Add focused tests; run:

```bash
uv run --frozen --extra dev --extra messaging python -m pytest tests/gateway/test_telegram_format.py -q -o 'addopts='
```

**Do not** teach the model to emit raw Telegram MarkdownV2. Hermes accepts standard Markdown and the adapter converts it. Do not switch to HTML parse mode without a full design review.

## References

- `references/local-business-research.md` — local business lookup workflow, Yelp pitfalls, Venue City venue notes, Jim's required output format for business recommendations.
- `references/hermes-telegram-formatting.md` — concise notes from a source inspection of Hermes Telegram formatting paths and practical guidance.

## Jim's Time Format Preference

All times shown in **Mountain Time (MT)** while Jim is in Venue City for USAW NCW (Jun 20–28 2026); Pacific Time when home in Your City. **Short labels only** — write `9:30 PM`, state the timezone **once** at the top of the message, omit it on every subsequent time. Never append tz suffix per line — it clutters.
- `references/telegram-markdownv2-field-notes.md` — external field notes from Reddit/forum/dev-community research on MarkdownV2 escaping, parse modes, links, dynamic values, and table pitfalls.
- `references/telegram-formatting-recency-verification.md` — recency-weighted verification workflow for separating current Telegram/Hermes evidence from older forum lore, including the focused Hermes formatter test command.
- `references/recommendation-cards-and-quick-replies.md` — user-preferred Telegram pattern for recommendation-first cards, risk/status emojis, and `A/B/C` or `1/2/3` quick replies.
- `references/telegram-formatting-research-2026-06.md` — session research summary and patch notes from 2026-06 covering blockquote hint + task checkbox conversion, focused formatter test results (104 passed), and exact implementation map (prompt_builder.py, telegram.py, test_telegram_format.py).
- `references/google-calendar-deeplink.md` — URL template + parameter encoding for Google Calendar add-event deep-links; when to include them; Jim's timezone rules.

## Hermes Telegram implementation map

When modifying or debugging Hermes Telegram formatting, the relevant files are:

- **Platform guidance:** `agent/prompt_builder.py`, `PLATFORM_HINTS["telegram"]`
- **Formatter:** `gateway/platforms/telegram.py`, `TelegramAdapter.format_message()` + helpers `_escape_mdv2()`, `_strip_mdv2()`, `_wrap_markdown_tables()`
- **Tests:** `tests/gateway/test_telegram_format.py`

**Enhancement workflow:** (1) Check platform hint first — if the formatter supports a construct but the hint omits it, patch the hint. (2) When adding formatter behavior, protect code spans/blocks before conversion, add conversion before generic MarkdownV2 escaping. (3) Preserve dynamic content safety: escape with `_escape_mdv2()`. (4) Add focused tests; run:

```bash
uv run --frozen --extra dev --extra messaging python -m pytest tests/gateway/test_telegram_format.py -q -o 'addopts='
```

**Do not** teach the model to emit raw Telegram MarkdownV2. Hermes accepts standard Markdown and the adapter converts it. Do not switch to HTML parse mode without a full design review.
- `references/telegram-formatting-research-2026-06.md` — session research summary and patch notes from 2026-06: blockquote hint + task checkbox conversion (`- [ ]`→`☐`, `- [x]`→`☑`), focused formatter test results (104 passed), exact implementation map.

## Recency-aware research guidance

When the user asks whether Telegram formatting lessons from Reddit, forums, or StackOverflow are still relevant, do not stop at generic community summaries. Weight sources by current authority:

1. Current Telegram Bot API documentation.
2. Current Hermes source/tests for the active formatter.
3. Recent Hermes commits touching gateway/platform formatting.
4. Recent community reproductions.
5. Older Reddit/forum/StackOverflow posts only as illustrative background.

Prefer verifying current Hermes behavior with the focused formatter test suite when source is available:

```bash
uv run --extra dev --extra messaging python -m pytest tests/gateway/test_telegram_format.py -q -o 'addopts='
```

Then report which conclusions are current and which examples are historical. If `uv` creates or updates local artifacts while preparing the test environment, clean up unrelated tracked changes before finalizing.

## Jim's Hyperlink Rule (enforced — never skip)

Every response that references a real-world place, business, phone number, or event must include:
- 📍 **Addresses** → `[Street Address](https://maps.google.com/?q=...)` Google Maps link
- 📞 **Phone numbers** → `[(NNN) NNN-NNNN](tel:NNNNNNNNNN)` tel: link
- 🌐 **Business/website names** → named hyperlink, never raw URL
- 📅 **Event times/dates** → [Google Calendar add-event link](https://calendar.google.com/calendar/r/eventedit?text=...&dates=...&location=...&details=...) pre-populated with title, date/time, location, details

This rule fired twice in the same session ("Always add hypertext links", "Did you hypertext phone numbers — always do this"). It is non-negotiable and applies to ALL output including cron deliveries.

## Change/Diff Report Formatting (Jim's rule, enforced)

When presenting a change report, diff, or modification summary on Slack or Telegram:

1. **Hyperlink all names** — never show full raw URLs. Use `[Jim](url)` format for people, file paths, and resources.
2. **Label each change type explicitly**: **Added**, **Removed**, or **Moved**.
3. **Identify who made the change** and **how long ago** at the top: `**Changes by [Jim](url) · 2h ago**`
4. **Use bullet groups, not tables** — consistent with the Telegram no-tables rule.
5. **Bold change-type labels** for scannability on mobile.

Template:
```markdown
**Changes by [Actor](url) · {relative time}**

**Added**
- [Item name](url) — one-line description

**Removed**
- [Item name](url) — one-line description

**Moved**
- [Item name](url) — from X to Y
```

This rule was set by Jim in a Jun 2026 WhatsApp session after he corrected two omissions: (a) names must be hyperlinks, not raw URLs, and (b) each change must be clearly labeled with its type, actor, and recency.

## Interactive / Tappable Suggestion Buttons — Platform Status

When ending a response with suggested next actions, make them tappable where possible. Current status per platform (as of Jun 2026):

| Platform | Status | Best workaround |
|----------|--------|----------------|
| **Telegram** | ⚠️ Pending [Issue #15311](https://github.com/NousResearch/hermes-agent/issues/15311) | `/commands` render as tappable blue links — tap sends instantly |
| **Slack** | ⚠️ Pending [Issue #34587](https://github.com/NousResearch/hermes-agent/issues/34587) | Block Kit button API exists but not exposed by Hermes yet |
| **WhatsApp (Baileys)** | ❌ Not supported | Baileys doesn't support interactive buttons; WA Business Cloud API supports up to 3 quick-reply buttons (different adapter) |

**Jim's preference:** format suggested follow-ups as short tappable `/commands` on Telegram. On WhatsApp and Slack, use concise backtick-wrapped prompt text the user can tap-to-copy. Until native button support lands, DO include 2–3 suggested next actions at the end of substantive responses.

## Pitfalls

- Do not recommend hand-writing Telegram MarkdownV2 escapes in normal answers; Hermes expects standard Markdown and performs conversion.
- Do not use Markdown tables for Telegram unless the data truly demands it. Even if Hermes can rewrite some pipe tables, direct bullet groups look cleaner.
- For community-research answers, distinguish direct source extraction from search-result signals. If Reddit extraction is blocked but search results expose relevant thread titles, say so and rely more heavily on accessible forums/APIs for concrete evidence.
- Treat Telegram formatting failures as adapter/converter regression-test candidates. Capture examples involving dynamic decimal values, punctuation-heavy links, spoilers, code spans, and pipe tables.
- Do not persist transient setup failures from local inspection as durable rules. Capture only stable formatter architecture and recommended output shape.
- If the relevant built-in Hermes skill is protected, do not edit it; create or update a separate class-level user skill like this one.
- **Yelp is blocked** — both `web_extract` and `browser_navigate` fail on yelp.com (CAPTCHA / fetch error). Use search snippet text (`site:yelp.com` queries surface descriptions) or go directly to business websites. Never report "searched Yelp" if you only saw search result snippets — be honest about what was actually accessed.
- **Local business research sequence:** (1) web_search for the category + city, (2) web_extract the top 2-3 business sites directly, (3) cross-check with a targeted search for hours/price/specific-amenity confirmation. Don't iterate through Yelp pages that won't load.
- **`tel:` links in Telegram** — Telegram does not always render `[(NNN) NNN-NNNN](tel:NNNNNNNNNN)` as a tappable call button; it shows as styled text instead. This is a Telegram rendering quirk, NOT an agent error. Always write phone numbers in this format regardless — the number remains clearly visible and manually dialable. Do not abandon the format because it doesn't render as a tap target.
- **Hyperlink rules are non-negotiable** — Jim corrected these explicitly and repeatedly. If you skip a Maps link, tel: link, website link, or Calendar deep-link, that is a formatting error, not a style choice. When in doubt, over-link rather than under-link. The rule applies to ALL responses — not just recommendations, briefs, or cron output.