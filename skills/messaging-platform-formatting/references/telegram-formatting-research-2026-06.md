# Telegram formatting research and patch notes — 2026-06

## Context

A Telegram/Hermes formatting review compared old Reddit/forum/StackOverflow reports with current Hermes and Telegram behavior. The goal was to avoid learning stale lessons from antiquated third-party limitations while still capturing durable MarkdownV2 pitfalls.

## Durable findings

- Telegram Bot API MarkdownV2 still requires escaping reserved characters: `_ * [ ] ( ) ~ ` > # + - = | { } . !`.
- Community examples from older StackOverflow/n8n posts are useful as symptoms of MarkdownV2 strictness, but not as evidence that Hermes lacks support.
- Current Hermes evidence is more authoritative:
  - `gateway/platforms/telegram.py` implements MarkdownV2 conversion.
  - `agent/prompt_builder.py` injects Telegram-specific platform guidance.
  - `tests/gateway/test_telegram_format.py` has a focused formatter suite.
  - Recent Hermes commits in 2026 touched Telegram MarkdownV2, table rendering, progress edits, and fallback behavior.

## Verification performed

Focused Telegram formatter suite passed before enhancement:

```text
101 passed in 0.40s
```

After adding blockquote hint + task checkbox conversion, focused suite passed:

```text
104 passed in 0.21s
```

Command:

```bash
uv run --frozen --extra dev --extra messaging python -m pytest tests/gateway/test_telegram_format.py -q -o 'addopts='
```

## Patch pattern captured

Changes made in the session:

- `agent/prompt_builder.py`
  - Telegram hint now mentions `> blockquotes` and task checkboxes `- [ ] / - [x]`.
- `gateway/platforms/telegram.py`
  - `format_message()` converts GitHub-style task lists after code protection and before link/header/bold/etc. conversion:
    - `- [ ] Task` → `☐ Task`
    - `- [x] Task` / `* [X] Task` → `☑ Task`
  - Task body is escaped with `_escape_mdv2()` and protected by the placeholder mechanism.
- `tests/gateway/test_telegram_format.py`
  - Added tests for unchecked/checked/uppercase checkboxes, MarkdownV2 escaping in task content, and no conversion inside fenced code blocks.

## Decision guidance

Prefer incremental formatter improvements with tests over broad parse-mode changes. Good candidates are model-output normalizations that make Telegram mobile rendering cleaner without exposing the model to raw MarkdownV2 rules.

Avoid persisting transient setup failures. In this session, `python -m pytest` lacked pytest in the active interpreter; the durable pattern is to use `uv run --frozen --extra dev --extra messaging ...` in the Hermes repo for focused tests.
