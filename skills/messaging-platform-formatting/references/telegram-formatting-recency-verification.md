# Telegram formatting recency verification

Use this reference when a user asks whether Telegram/MarkdownV2 lessons from Reddit, forums, or StackOverflow are still current versus antiquated.

## Recency-weighting rule

Do not treat old forum posts as authoritative by themselves. Weight evidence in this order:

1. Current Telegram Bot API documentation for MarkdownV2 syntax/escaping.
2. Current Hermes source and tests, especially `gateway/platforms/telegram.py` and `tests/gateway/test_telegram_format.py`.
3. Recent Hermes commits touching Telegram formatting.
4. Recent community reports that reproduce the same issue class.
5. Older StackOverflow/Reddit/forum posts only as historical examples of the same durable mechanism.

## Current durable mechanism

Telegram MarkdownV2 still requires escaping these ordinary-looking characters outside protected entities:

```text
_ * [ ] ( ) ~ ` > # + - = | { } . !
```

This makes dynamic values, decimals, punctuation-heavy text, inline links, code spans, and table-like output common edge cases. The lesson is not "Telegram formatting is broken"; it is "Telegram MarkdownV2 is strict, so rely on the platform formatter and keep model output structurally simple."

## Hermes verification path

When validating Hermes behavior, inspect/run the focused formatter tests before concluding from community posts:

```bash
cd /path/to/hermes-agent
uv run --extra dev --extra messaging python -m pytest tests/gateway/test_telegram_format.py -q -o 'addopts='
```

If `uv` updates `uv.lock` as a side effect while preparing the environment, inspect and revert unrelated lockfile changes before finishing:

```bash
git diff -- uv.lock
git checkout -- uv.lock
```

The relevant test suite covers reserved-character escaping, decimal dots, exclamation marks, links, code blocks, inline code, bold/italic/headers, spoilers, blockquotes, bullet lists, Markdown table rewriting into row groups, edit fallback behavior, and long-message continuations.

## Example verified signal

A focused run of `tests/gateway/test_telegram_format.py` passed with `101 passed`, supporting the current recommendation that Hermes already handles Telegram MarkdownV2 conversion and table rewriting in the adapter.

## Communication pattern to the user

When asked whether lessons are stale:

- Explicitly separate **current authoritative facts** from **older illustrative reports**.
- Avoid over-learning from 2016–2023 posts about specific third-party tools.
- Say that recent Hermes tests/commits and current Telegram docs are the authoritative basis.
- Recommend normal Markdown, short headings, bullets/key-value blocks, code blocks for commands/logs, and no manual raw MarkdownV2 escaping.
