# Telegram MarkdownV2 field notes from Reddit/forum/dev research

Use these notes when the user asks whether Telegram/Hermes formatting should change based on community experience.

## Recurrent external pattern

Telegram bot MarkdownV2 is brittle in real-world automations because many ordinary characters are reserved and must be escaped in plain text:

```text
_ * [ ] ( ) ~ ` > # + - = | { } . !
```

Common failure mode: `Bad Request: can't parse entities: Character '<char>' is reserved and must be escaped with the preceding '\'`.

## Concrete experiences observed

- **n8n dynamic value with decimal point**: A Telegram MarkdownV2 message failed because a dynamic numeric value such as `0.751654` contained `.`. The dot was in the evaluated value, not the template expression. Suggested workaround in the thread: switch parse mode to HTML or explicitly escape dynamic values.
- **n8n formatting not rendering**: Users needed to set the Telegram node's parse mode (`Markdown`, `MarkdownV2`, or `HTML`) explicitly; bot formatting is not automatic.
- **n8n MarkdownV2 feature request**: Spoiler syntax (`||spoiler||`) required explicit MarkdownV2 support in the integration, showing that platform/integration formatter support matters.
- **Stack Overflow escaping pitfalls**: Answers repeatedly list MarkdownV2 reserved characters, but warn that globally escaping everything makes intended markup like `*bold*` render literally.
- **Stack Overflow link pitfalls**: Escaping link syntax and URL punctuation naively can break `[label](url)` entities; converters must protect links/code/entities before escaping surrounding text.
- **GitHub/python-telegram-bot issues**: Mature libraries have hit reserved-character errors such as unescaped periods, confirming this is ecosystem-wide rather than user error.
- **Reddit search signal**: Reddit search results surface recurring threads on Telegram MarkdownV2 parse mode, ChatGPT Telegram bots, partial Markdown support, and Markdown formatting issues. Direct Reddit extraction may be blocked, but the discovered thread titles align with the same pain points.

## Practical recommendation for Hermes

- Do **not** ask the assistant/model to emit raw Telegram MarkdownV2 escapes in final answers.
- Prefer simple standard Markdown as the source format and let the Hermes Telegram adapter convert to MarkdownV2.
- If rendering breaks, treat it as a converter/testcase issue in the platform adapter, not as a reason to hand-escape every response.
- Avoid pipe tables in Telegram; use headings plus bullet row-groups or key-value blocks.
- For integrations that expose parse mode but lack a robust converter, HTML parse mode is a common workaround. For Hermes specifically, keep the current MarkdownV2 adapter path unless a concrete bug requires code changes.

## Good regression-test ideas

When modifying a Telegram formatter, add cases for:

- Dynamic plain text with decimals, exclamation marks, hyphens, parentheses, underscores, and dots.
- Intended formatting spans: `**bold**`, `*italic*`, `~~strike~~`, `||spoiler||`.
- Inline code and fenced code containing reserved MarkdownV2 characters.
- Links with punctuation-heavy URLs.
- Pipe tables, ensuring Telegram output becomes readable row groups rather than literal broken table syntax.
