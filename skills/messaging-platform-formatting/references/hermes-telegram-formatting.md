# Hermes Telegram formatting source-inspection notes

## Stable architecture

Hermes handles Telegram formatting at two layers:

1. **System prompt platform hint**
   - `agent/prompt_builder.py` contains `PLATFORM_HINTS["telegram"]`.
   - The hint says standard Markdown is automatically converted to Telegram format.
   - It lists supported syntax: `**bold**`, `*italic*`, `~~strikethrough~~`, `||spoiler||`, inline code, fenced code blocks, links, and `##` headers.
   - It explicitly warns that Telegram has no table syntax and recommends bullets/key-value pairs.

2. **Gateway adapter formatter**
   - `agent/system_prompt.py` appends the platform hint when `agent.platform` is Telegram.
   - `gateway/platforms/telegram.py` has `TelegramAdapter.format_message(content)` that converts standard Markdown to Telegram MarkdownV2.
   - Sends/edits use Telegram `parse_mode=ParseMode.MARKDOWN_V2` on formatted final text.
   - The adapter includes table rewriting helpers (`_wrap_markdown_tables`, `_render_table_block_for_telegram`) that convert simple GFM pipe tables into Telegram-friendly row groups.

## Config interpretation

When inspecting a user's config:

- `display.final_response_markdown` is primarily a CLI/TUI display setting; do not assume it changes Telegram gateway formatting.
- `display.platforms.<platform>` can hold per-platform display/runtime-footer settings, but Telegram Markdown conversion is implemented in the adapter, not as a simple user-facing toggle.
- The `telegram:` config section may contain delivery/behavior options (reactions, channel prompts, allowlists, etc.) without a separate Markdown toggle.

## Recommended final-answer shape for Telegram

Use source Markdown that is easy for Hermes to convert:

- Short headings.
- Bullets.
- Labeled `key: value` lines.
- Bold labels.
- Code blocks for commands/logs.
- Normal Markdown links.
- No pipe tables; use row groups instead.

Example:

```markdown
## Summary

**Finding**
- Status: confirmed
- Source: Hermes Telegram platform hint + adapter formatter

**Action**
- Config change: none needed
- Style: bullets/key-value lists instead of tables
```

## What not to capture from this session

Do not save environment-specific inspection failures such as missing CLI binaries or missing Python packages as durable facts. They are setup-state issues, not persistent guidance about Hermes formatting.