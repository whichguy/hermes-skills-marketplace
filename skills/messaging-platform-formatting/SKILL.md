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
- **Use Markdown links for Telegram chat messages**: `[descriptive text](url)` — never bare URLs. The Hermes adapter (`format_message()` in `plugins/platforms/telegram/adapter.py`) converts `[text](url)` links to Telegram MarkdownV2 format automatically, protecting URLs from over-escaping. Do NOT use HTML `<a href>` tags in Telegram chat messages — the adapter uses `parse_mode=MARKDOWN_V2` (not HTML), so HTML tags get mangled by the MarkdownV2 escaper and render as broken text.
- **Exception — Google Calendar event descriptions**: Google Calendar supports HTML, not Markdown. Use `<a href="url">text</a>` HTML tags in calendar event descriptions. This is the only context where HTML links should be used.
- For daily briefs, cron updates, alerts, and watchlist summaries, prefer clickable text links over bare URLs whenever a useful interface exists: `[Google Calendar event](url)`, `[Gmail Inbox search](url)`, `[Drive doc](url)`, `[ESPN scoreboard](url)`, `[Docker Hub tag](url)`. Link the human-usable interface, not just an API endpoint.

### Jim's mandatory hyperlink rules (every response, not just briefs)

These are **non-negotiable** — Jim corrected these twice in one session:

1. **Business/place names** — always hyperlink to the business website: `[VASA Fitness](https://vasafitness.com/...)`
2. **Addresses** — always hyperlink to Google Maps: `[7655 N Union Blvd, Colorado Springs](https://maps.google.com/?q=...)`
3. **Phone numbers** — always wrap in `tel:` link: `[YOUR_PHONE_NUMBER](tel:YOUR_PHONE_NUMBER)`
4. **Event times/dates** — always hyperlink to a pre-populated Google Calendar add-event URL (see `references/google-calendar-deeplink.md` for the URL template)
5. **Never raw URLs** — always use `[named label](url)` Markdown format for Telegram chat; `<a href="url">named label</a>` HTML format for calendar event descriptions

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

## Advanced Telegram Formatting via Markdown (no parse mode switch needed)

The Hermes adapter (`format_message()` in `plugins/platforms/telegram/adapter.py`) converts standard Markdown to Telegram MarkdownV2. These constructs are supported in the current MarkdownV2 pipeline:

| Construct | Markdown Syntax | Notes |
|-----------|-----------------|-------|
| **Bold** | `**text**` | Converted to `*text*` |
| *Italic* | `*text*` | Converted to `_text_` |
| ~~Strikethrough~~ | `~~text~~` | Converted to `~text~` |
| ||Spoiler|| | `\|\|text\|\|` | Protected from pipe escaping |
| `Inline code` | `` `code` `` | Protected as placeholder |
| Code blocks | ` ```lang\ncode\n``` ` | Protected; `\\` and `` ` `` escaped inside |
| Headers | `## Title` | Converted to `*Title*` (bold) |
| Blockquotes | `> text` | `>` protected from escaping |
| Links | `[text](url)` | Display text escaped; URL has only `)` and `\` escaped |
| Task lists | `- [ ]` / `- [x]` | Converted to `☐` / `☑` |

### Advanced features that REQUIRE HTML parse mode (not currently available for regular messages)

These features are documented in the [Telegram Bot API](https://core.telegram.org/bots/api#formatting-options) but require `parse_mode=HTML` instead of `MARKDOWN_V2`. The adapter already uses `parse_mode=HTML` for approval prompts and clarify choices (where it controls the content), but not for regular message delivery.

| Feature | HTML Tag | Use Case |
|---------|----------|----------|
| Expandable blockquote | `<blockquote expandable>` | Collapsible details in alerts — "show more" |
| Custom emoji | `<tg-emoji emoji-id="...">` | Requires Premium — not useful |
| Date-time rendering | `<tg-time unix="..." format="r">` | Auto-renders in user's local timezone |
| Syntax-highlighted code | `<pre><code class="language-python">` | Better than MarkdownV2 code blocks |

**To enable these:** would need to add a `format_message_html()` method to the adapter that converts Markdown → HTML (using `html.escape()` instead of `_escape_mdv2()`), then switch the `parse_mode` for regular messages from `MARKDOWN_V2` to `HTML`. This is a separate project — the MarkdownV2 pipeline handles all current needs correctly.

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

- `references/local-business-research.md` — local business lookup workflow, Yelp pitfalls, Colorado Springs venue notes, Jim's required output format for business recommendations.
- `references/hermes-telegram-formatting.md` — concise notes from a source inspection of Hermes Telegram formatting paths and practical guidance.
- `references/hermes-adapter-link-pipeline.md` — **reverse-engineered `format_message()` pipeline**: how the adapter protects Markdown links from the global `_escape_mdv2()` pass via placeholders, why HTML `<a href>` tags break, and the verification script. Read this before concluding any Telegram link formatting is broken.
- `references/telegram-adapter-pipeline.md` — **structured pipeline reference**: complete message formatting pipeline diagram, MarkdownV2 vs HTML feature comparison table, source code locations, and calendar event description guidance. Created during the 2026-07-05 link-formatting fix session.

## Jim's Time Format Preference

All times shown in **Mountain Time (MT)** while Jim is in Colorado Springs for USAW NCW (Jun 20–28 2026); Pacific Time when home in San Ramon. **Short labels only** — write `9:30 PM`, state the timezone **once** at the top of the message, omit it on every subsequent time. Never append tz suffix per line — it clutters.
- `references/telegram-markdownv2-field-notes.md` — external field notes from Reddit/forum/dev-community research on MarkdownV2 escaping, parse modes, links, dynamic values, and table pitfalls.
- `references/telegram-formatting-recency-verification.md` — recency-weighted verification workflow for separating current Telegram/Hermes evidence from older forum lore, including the focused Hermes formatter test command.
- `references/recommendation-cards-and-quick-replies.md` — user-preferred Telegram pattern for recommendation-first cards, risk/status emojis, and `A/B/C` or `1/2/3` quick replies.
- `references/telegram-formatting-research-2026-06.md` — session research summary and patch notes from 2026-06 covering blockquote hint + task checkbox conversion, focused formatter test results (104 passed), and exact implementation map (prompt_builder.py, telegram.py, test_telegram_format.py).
- `references/google-calendar-deeplink.md` — URL template + parameter encoding for Google Calendar add-event deep-links; when to include them; Jim's timezone rules.

## Calendar Event Hyperlink Patterns (Jim's Rule)

Google Calendar event descriptions support basic HTML. When adding links to calendar events, use HTML `<a href>` tags — never raw URLs:

```html
<a href="https://mail.google.com/mail/u/0/#inbox/<thread_id>">📋 View original booking email</a>
<a href="https://maps.google.com/?q=<encoded_address>">📍 <street address></a>
<a href="https://www.alaskaair.com/checkin">✈️ Alaska Airlines Check-In</a>
```

**Gmail booking email link** — mandatory on ALL trip-related calendar events (flights, hotels, Uber, check-in reminders). Find the thread ID by searching Gmail for the confirmation code, then add the HTML hyperlink to every related event's description. This lets Jim tap to see the full booking details from any calendar event in the trip.

**Pattern:** `📋 View original booking email` as the hyperlink text, linking to `https://mail.google.com/mail/u/0/#inbox/<thread_id>`. Apply to every event in the trip chain — not just the flight itself.

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
- 📍 **Addresses** → `[Street Address](https://maps.google.com/?q=...)` Google Maps link (Markdown for Telegram chat)
- 📞 **Phone numbers** → `[(NNN) NNN-NNNN](tel:NNNNNNNNNN)` tel: link (Markdown for Telegram chat)
- 🌐 **Business/website names** → `[Business Name](url)` named hyperlink, never raw URL (Markdown for Telegram chat)
- 📅 **Event times/dates** → [Google Calendar add-event link](https://calendar.google.com/calendar/r/eventedit?text=...&dates=...&location=...&details=...) pre-populated with title, date/time, location, details

**Context matters:** Use `[text](url)` Markdown links for Telegram chat messages (the adapter converts to MarkdownV2). Use `<a href="url">text</a>` HTML links ONLY for Google Calendar event descriptions (which support HTML, not Markdown).

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

| Platform | Status | How it works |
|----------|--------|-------------|
| **Telegram** | ⚠️ Broken | Inline keyboard buttons render but clicking does nothing. The suggestion-stripper hook patches `adapter._handle_callback_query` but `python-telegram-bot`'s `CallbackQueryHandler` captured the original bound method at registration time — the patch has no effect. Bug identified 2026-07-07, fix pending. |
| **Slack** | ✅ Live | Block Kit buttons via `hermes_suggest_option` action_id. Max 20 options, 75-char labels, prompts in button `value` (2000 chars). |
| **WhatsApp (Baileys)** | ❌ Not supported | Baileys doesn't support interactive buttons; WA Business Cloud API supports up to 3 quick-reply buttons (different adapter) |

**Dynamic options mode:** When the SUGGESTION marker includes an `options` field, the adapter renders one button per option instead of a single "Do it" button. Each button's click injects the option's `prompt` as a synthetic user message. See `slack-block-kit-enhancement` skill for full implementation details.

**Jim's preference:** format suggested follow-ups as short tappable `/commands` on Telegram. On WhatsApp, use concise backtick-wrapped prompt text the user can tap-to-copy. Until native button support lands, DO include 2–3 suggested next actions at the end of substantive responses.

### Pitfall: `SUGGESTION:{}` markers leak as raw text when PR #51858 is not deployed

`SOUL.md` emits `SUGGESTION:{"next":"...","reason":"..."}` markers after non-tactical responses. These are meant to be parsed into interactive buttons (Telegram inline keyboards / Slack Block Kit) by `stream_consumer.py::_clean_for_display()` + gateway delivery code. However, PR #51858 (interactive suggestion buttons) is **not merged into all installations**. On installations where it's absent:

- `_clean_for_display()` only strips `MEDIA:` and `[[audio_as_voice]]` — NOT `SUGGESTION:{}` markers
- The raw JSON marker (`SUGGESTION:{"next":"...","reason":"...","can_do":true}`) appears as literal text in Slack, Telegram, and other platform messages
- Users see garbled JSON appended to otherwise clean responses

**When you see raw `SUGGESTION:{}` text in a delivered message**, the installation is missing PR #51858. The fix is deploying the PR code (fork: `whichguy/hermes-agent-1`, branch: `feature/interactive-suggestion-buttons-clean`), not changing the SOUL.md directive. See `hermes-slack-gateway` skill for Block Kit infrastructure details.

## Post-Response Suggestion Block Design

**Implemented in SOUL.md (Phase 0).** The post-response suggestion block replaces the generic "recommended next step" with a structured, context-aware block appended after non-tactical responses. See `references/post-response-suggestion-block-design.md` for the full lifecycle analysis, research sources, phased implementation plan, and example responses.

### Tactical vs Non-Tactical Classification

- **Non-tactical (append block):** research, analysis, code creation/review, debugging, planning, architecture decisions, multi-step task completion.
- **Tactical (skip block):** quick lookups, yes/no, status checks, error messages, tool-only confirmations, approval prompts, mid-conversation progress updates, reminders, responses under 3 sentences.
- **Never include:** cron sessions, subagent summaries, kanban worker sessions (subagents don't load SOUL.md — exclusion is built-in via `skip_context_files=True`).

### Format (platform-aware)

Hermes auto-converts standard markdown to each platform's native format via `format_message()` in each platform adapter. Key difference: `---` (horizontal rule) only renders on Telegram — on Slack and WhatsApp it shows as literal dashes.

**Telegram** (richest): Full markdown — bold, italic, code, `## headers`, `---` divider, `[links](url)`, > blockquotes. 3-line max. Use `---` separator.

**Slack**: Supports bold, code, links, headers (auto-converted). No `---` divider. 2-line max. Use blank line + bold labels.

**WhatsApp**: Supports `*bold*`, `_italic_`, `~strikethrough~`, `` `code` ``. No `---` divider. 2-line max. Use blank line + bold labels.

**SMS/Signal**: Plain text only. 1-line max. No markdown, no emoji headers.

Rules: pick 1-2 components (Learn / Next / 💡 Tip), not all three. Max 3 lines total (Telegram, CLI, Email); 2 on Slack and WhatsApp. Each suggestion references what just happened + includes a reason. Adaptive depth: power users get Next-only, skip Learn entirely.

### Key design principle from research

ChatGPT's forced follow-up suggestions drew strong user backlash ("disruptive," "can't disable"). The block must be **suppressible** (Phase 1: `/suggestions on|off` slash command), **never forced**, and **anchored in what just happened** — not generic suggestions. ShapeofAI's follow-up pattern: "balance 1-2 zoom-in suggestions with 1 zoom-out option."

### Existing directive tension

The Hermes system prompt already says "Always include a concise recommended next step when stopping." The SOUL.md directive explicitly says "This replaces any generic 'recommended next step'." If both fire, the generic directive may still produce an unstructured one-liner alongside the structured block. If this happens during testing, the fix is a code-level override or AGENTS.md directive (Phase 2).

## Interactive Button Infrastructure (for suggestion buttons)

Hermes already has interactive button infrastructure for approval prompts — directly reusable for suggestion buttons. Full audit in `hermes-persona-customization` skill's `references/community-research-and-interactive-capabilities.md`.

**Telegram**: `InlineKeyboardMarkup` + `CallbackQueryHandler` (prefix routing: `ea:`, `mp:`, `gt:`, `update_prompt:`). See `gateway/platforms/telegram.py` lines 2578-2690 for approval prompt pattern.

**Slack**: Block Kit `blocks` with `actions` + `button` elements, action handlers via `self._app.action(action_id)(handler)`. See `gateway/platforms/slack.py` lines 2646-2719 for Block Kit approval pattern. Uses `divider` + `section` + `actions` blocks.

**WhatsApp**: No interactive button support in the adapter. Text-only fallback only. Baileys supports interactive messages but Hermes doesn't implement them.

**Matrix, Discord, Feishu**: All have `send_exec_approval` or interactive card support.

## Community Research on Post-Response Suggestions

Condensed findings from Reddit, HN, OpenAI forums, CHI 2025, and UX design communities. Full details in `hermes-persona-customization` skill's `references/community-research-and-interactive-capabilities.md`.

Key principles:
1. **Default to silence** — irrelevant suggestions train users to ignore all future ones
2. **Do, don't suggest** — low-risk next steps should be auto-executed, not suggested
3. **Fewer is better** — CHI 2025: 5 frequent suggestions performed worse than 3 less frequent
4. **Suppressibility is mandatory** — ChatGPT users revolted when they couldn't disable follow-ups
5. **Interactive buttons > text** — use existing inline keyboard / Block Kit infrastructure where available

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

### Pitfall: Fixing a systemic formatting bug in one skill without sweeping the rest

**The pattern:** A formatting bug (e.g., broken Telegram links) is traced to incorrect guidance in a skill. You patch that skill and the cron job prompts that triggered it. You think you're done. But the same incorrect guidance lives in 2-3 other skills that inherited it from the same wrong diagnosis — and those skills will produce the same bug the next time they're loaded.

**Real example (2026-07-05):** The initial fix patched `cron-output-standards`, `cron-llm-review-house-style`, and 3 cron job prompts. A follow-up sweep found the same stale HTML `<a href>` guidance in `script-first-cron-design` (2 locations) and `hermes-persona-customization` (platform comparison table). Total: 37 `<a href` references across 10 files needed auditing.

**The rule:** When you fix a systemic formatting/guidance error, the fix is NOT complete until you audit every file that could carry the same wrong instruction:

```bash
# Full sweep — search ALL locations, not just the one that triggered the bug
grep -rn '<a href' /opt/data/skills/ --include="*.md" | categorize-each-match
grep -rn '<a href' /opt/data/cron/jobs.json
grep -rn 'HTML.*[Tt]elegram\|[Tt]elegram.*HTML' /opt/data/skills/ --include="*.md"
```

Categorize each match as: (1) calendar event description → correct, leave alone; (2) warning against HTML → correct, leave alone; (3) Telegram chat guidance → WRONG, fix immediately. Only stop when every match is in category 1 or 2.