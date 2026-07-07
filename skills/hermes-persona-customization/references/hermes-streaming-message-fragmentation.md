# Hermes Streaming & Message Fragmentation

Reference for diagnosing and fixing "multiple separate messages instead of
in-place updates" — the user sees a stream of new messages rather than one
message that progressively edits itself.

## The Problem

User observes Hermes posting many separate messages during a response instead
of editing one message in place. Each tool call, interim commentary, and the
final answer arrive as distinct messages, triggering multiple notifications.

## Root Cause: Config Interaction

Several config keys interact to produce this behavior. The streaming system
(`GatewayStreamConsumer` in `gateway/stream_consumer.py`) supports progressive
editing of a single message, but these settings override that:

| Config key | Location | Effect when enabled |
|---|---|---|
| `fresh_final_after_seconds` | `streaming:` | **Telegram only** — hardcoded to `0.0` for all non-Telegram platforms in `run.py:16375-16378`. On Telegram: if response takes >N seconds, final answer is sent as a new message instead of editing the preview. |
| `interim_assistant_messages` | `display:` (global + per-platform) | Text like "Let me check that..." between tool calls is sent as **separate messages**. |
| `tool_progress` | `display.platforms.<name>` | Tool call progress bubbles are sent as **separate messages**. |
| `cleanup_progress` | `display:` (global + per-platform) | When `false`, tool progress bubbles persist after the response finishes. |
| Segment breaks | architectural | When the agent makes tool calls, the stream consumer finalizes the current text segment and starts a new message for the next one. This is by design and cannot be disabled. |

## Recommended Config for Minimal Fragmentation (Slack)

```yaml
display:
  platforms:
    slack:
      interim_assistant_messages: false  # No separate commentary messages
      tool_progress: "new"                # One progress bubble per tool-call round (edited in place)
      cleanup_progress: true              # Deletes progress bubbles after response (requires gateway restart for adapter code)
```

`fresh_final_after_seconds` does NOT need to be set for Slack — it's already hardcoded to `0.0` in `run.py:16375-16378` for all non-Telegram platforms.

### What Each Change Does

1. **`interim_assistant_messages: false`** — Stops the agent from sending
   separate "I'll look into that..." messages between tool calls. These
   mid-turn status lines are suppressed entirely.

2. **`tool_progress: "new"`** — One progress bubble per tool-call round (edited
   in place) instead of one per individual tool call. The biggest single win
   for reducing message count on Slack. Use `"off"` to suppress entirely.

3. **`cleanup_progress: true`** — Deletes tool-progress bubbles after the
   final response lands. Now works on Slack (adapter implements `delete_message`
   via `chat.delete` API as of Jul 2026). Requires gateway restart for the
   adapter code change to take effect.

4. **`fresh_final_after_seconds`** — No action needed for Slack. The code at
   `run.py:16375-16378` hardcodes `0.0` for all non-Telegram platforms, so
   Slack never gets fresh-final behavior regardless of the config value.

## Architecture Notes

### How Streaming Works

`GatewayStreamConsumer` (in `gateway/stream_consumer.py`) manages the
streaming lifecycle:

1. **Initial send**: First chunk of text is sent as a new message, message ID
   is captured.
2. **Progressive edits**: Subsequent chunks edit the same message in place
   via the adapter's `edit_message()` method.
3. **Segment breaks**: When a tool call starts, the current text segment is
   finalized (sent as a complete message) and a new message begins for the
   next segment. This is architectural — tool calls inherently break the
   streaming flow.
4. **Finalization**: When the LLM finishes, the last segment is finalized.

### Fresh-Final Logic (Telegram Only)

The `fresh_final_after_seconds` threshold (in `stream_consumer.py:1247-1267`)
checks: if the preview message has been visible for ≥ N seconds, send the
completed answer as a **fresh new message** and best-effort delete the old
preview. This is so the timestamp reflects completion time. Setting it to
`0.0` disables this — the preview is always edited in place.

**Important:** This logic is **hardcoded to `0.0` for all non-Telegram platforms**
in `run.py:16375-16378`. Slack, WhatsApp, Discord, etc. never get fresh-final
behavior regardless of the config value. The `streaming.fresh_final_after_seconds`
config key only affects Telegram.

### Platform Differences

- **Telegram**: Has `prefers_fresh_final_streaming` hook that always uses
  fresh-final (rich message send path renders better markdown than edit path).
  This is a platform limitation, not configurable.
- **Slack**: Supports progressive editing natively. The config changes above
  work well.
- **WhatsApp**: Does not support message editing at all — every chunk is a
  new message. No config can fix this.
- **Webhooks**: `interim_assistant_messages` and `tool_progress` are
  automatically disabled for webhooks (no edit support).

## Config Application

Use the Hermes venv Python to edit config.yaml (system Python may lack PyYAML
due to PEP 668):

```bash
/opt/hermes/.venv/bin/python3 -c "
import yaml
with open('/opt/data/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
# Apply changes...
with open('/opt/data/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
"
```

Or use `hermes config set` for individual keys:

```bash
hermes config set streaming.fresh_final_after_seconds 0.0
hermes config set display.platforms.slack.interim_assistant_messages false
hermes config set display.platforms.slack.cleanup_progress true
hermes config set display.platforms.slack.tool_progress off
```

## Pitfalls

1. **Setting `fresh_final_after_seconds` too low but not zero (Telegram only)**: Values like
   `5.0` still trigger fresh-final for any response with tool calls (which
   almost always exceed 5 seconds). Use `0.0` to truly disable. **Not applicable
   to Slack** — hardcoded to `0.0` in `run.py:16375-16378`.

2. **Confusing `interim_assistant_messages` with `tool_progress`**: They're
   independent. Interim messages are natural-language status ("Let me check
   that..."). Tool progress is structured ("🔧 terminal: git status"). Both
   need to be addressed for minimal fragmentation.

3. **WhatsApp can't be fixed**: WhatsApp has no edit-message API. Every chunk
   is always a new message. The only mitigation is to reduce chunk count by
   disabling interim messages and tool progress.

4. **Segment breaks are unavoidable**: When the agent makes a tool call, the
   streaming flow must break. The text before the tool call is finalized as
   one message, tool progress (if enabled) is another, and the post-tool
   response is a third. This is architectural — the only fix is to reduce
   tool calls or suppress progress messages.
