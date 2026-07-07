# Hermes Telegram Adapter — Message Formatting Pipeline

Reverse-engineered from `/opt/hermes/plugins/platforms/telegram/adapter.py` (2026-07-05).

## Pipeline: Agent Response → Telegram Message

```
agent_response (Markdown)
    │
    ▼
format_message(text)                    # adapter.py:6286
    │
    ├─ _wrap_markdown_tables(text)      # adapter.py:6342 — wraps pipe tables in <pre> for monospace
    │
    ├─ Link protection:                  # adapter.py:6342-6347
    │   [text](url) → [text](<PLACEHOLDER_N>)
    │   URLs stored in a dict, replaced back after escaping
    │
    ├─ _escape_mdv2(text)               # adapter.py:292
    │   Escapes: _ * [ ] ( ) ~ ` > # + - = | { } . !
    │   But NOT the placeholder-wrapped URLs
    │
    ├─ Placeholder restoration:
    │   <PLACEHOLDER_N> → original URL
    │   Only ) and \ inside URLs are escaped
    │
    └─ Result: valid Telegram MarkdownV2
```

## Key Findings

### Links: `[text](url)` works, `<a href>` does NOT

- **`[text](url)`** → adapter protects the URL from escaping → valid MarkdownV2 → Telegram renders as clickable link ✅
- **`<a href="url">text</a>`** → adapter escapes `<` and `>` → becomes `\<a href="url"\>text\</a\>` → Telegram shows literal text, NOT a link ❌

### parse_mode

- Regular messages: `parse_mode=MARKDOWN_V2` (adapter.py send methods)
- Approval prompts: `parse_mode=HTML` (adapter.py:4442, 4557)
- Clarify choices: `parse_mode=HTML` (adapter.py:4557)

### What MarkdownV2 supports (and the adapter converts)

| Feature | MarkdownV2 syntax | Adapter handles? |
|---------|------------------|-----------------|
| Bold | `**text**` | ✅ via `_escape_mdv2` (preserves `*`) |
| Italic | `*text*` or `_text_` | ✅ |
| Strikethrough | `~~text~~` | ✅ |
| Spoiler | `\|\|text\|\|` | ✅ |
| Inline code | `` `code` `` | ✅ |
| Code block | ` ```lang\ncode\n``` ` | ✅ |
| Links | `[text](url)` | ✅ via placeholder protection |
| Headers | `## Header` | ✅ |
| Blockquote | `> text` | ✅ |
| Task lists | `- [ ] item` / `- [x] item` | ✅ |
| Tables | `\| col \| col \|` | ✅ via `_wrap_markdown_tables` |

### What requires `parse_mode=HTML` (NOT available in MarkdownV2)

| Feature | HTML syntax | Notes |
|---------|------------|-------|
| Underline | `<u>text</u>` | Not in MarkdownV2 spec |
| Nested tags | `<b>bold <i>italic</i></b>` | MarkdownV2 doesn't nest |
| Expandable blockquote | `<blockquote expandable>...</blockquote>` | HTML-only |
| Custom emoji | `<tg-emoji emoji-id="...">👍</tg-emoji>` | HTML-only |
| Timestamp | `<tg-time datetime="...">text</tg-time>` | HTML-only |
| Pre with language | `<pre><code class="language-python">...</code></pre>` | HTML-only (but ` ```python ` works in MarkdownV2) |

## Calendar Event Descriptions

Google Calendar event descriptions support **HTML**, not Markdown. Use `<a href="url">text</a>` for links in calendar descriptions. This is the ONE context where HTML links are correct.

## Message Length Limit

Telegram: 4096 characters per message. The adapter auto-splits longer messages.

## Source Locations

- `format_message()`: `/opt/hermes/plugins/platforms/telegram/adapter.py:6286`
- `_escape_mdv2()`: `/opt/hermes/plugins/platforms/telegram/adapter.py:292`
- `_strip_mdv2()`: `/opt/hermes/plugins/platforms/telegram/adapter.py:320`
- `_wrap_markdown_tables()`: `/opt/hermes/plugins/platforms/telegram/adapter.py:6342`
- `parse_mode=HTML` usage: adapter.py:4442, 4557
- Platform hints: `/opt/hermes/agent/prompt_builder.py` (PLATFORM_HINTS['telegram'])
