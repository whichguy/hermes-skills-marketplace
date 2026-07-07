# Interactive Suggestion Buttons — Implementation Guide

## Architecture

The LLM appends `SUGGESTION:{...}` (JSON on one line) at the very end of its
response text. The gateway post-processes this:

1. **Non-streaming path** (`base.py:_process_message_background`): Before
   `self._send_with_retry()`, the adapter checks `hasattr(self, "send_suggestion")`.
   If true, calls `extract_suggestion(text_content)` to strip the marker and
   extract fields. After the main text is sent, calls `self.send_suggestion()`
   to deliver interactive buttons in a separate message.

2. **Streaming path** (`run.py:_deliver_suggestion_from_response`): After
   streaming completes and `_deliver_media_from_response` runs, the gateway
   checks the full response text for a marker. If found and the adapter has
   `send_suggestion`, sends a separate button message. (The marker also
   appears in the already-streamed text — future work could edit the streamed
   message to remove it.)

3. **Platforms without `send_suggestion`**: Marker stays in the text as
   plain text. No behavior change.

## Marker Format

```
SUGGESTION:{"next": "Email Albert Shin", "reason": "CO expires Jul 15", "can_do": true}
```

Fields:
- `next` (str): the recommended user action
- `learn` (str): optional brief explanation of what the agent did
- `reason` (str): why this is the next step
- `can_do` (bool): whether the agent can auto-execute (controls "Do it" button)
- `options` (list, optional): array of `{label, prompt}` dicts for dynamic buttons

### Dynamic Options Mode (2026-06-26)

When `options` is present, the adapter renders one button per option instead of
the static Explain/Do it/Dismiss buttons:

```json
SUGGESTION:{"next": "Review the plan", "reason": "Plan needs your input", "can_do": false, "options": [
  {"label": "Start Phase 1", "prompt": "Go ahead and implement Phase 1 now."},
  {"label": "Review full plan first", "prompt": "Show me the full plan before starting."},
  {"label": "Skip to Phase 3", "prompt": "Skip to Phase 3 and implement the markdown blocks."}
]}
```

**How it works:**
- Parser extracts `options` list from the JSON
- Delivery path passes `options` to `send_suggestion()`
- Each platform renders one button per option + a Dismiss button
- On click, the option's `prompt` is injected as a synthetic user message

**Platform limits:**

| Constraint | Slack | Telegram |
|---|---|---|
| Max options | 20 (25 elements per actions block) | 8 (self-imposed) |
| Button label | 75 chars (truncated to 72 + "...") | 60 chars |
| Prompt storage | Button `value` (2000 chars) | In-memory dict (expires on restart) |
| Click response | New bot message in same thread | New bot message in same chat |

**Design principles:**
- Labels should be action-oriented ("Start Phase 1" not "Option 1")
- Prompts should be self-contained and specific
- Max 3-4 options for best UX — more overwhelms the user
- A Dismiss button is always appended

### Options-Only Mode (2026-06-26)

The parser accepts suggestions with `options` but no `next` field. The
delivery path handles this: if only options are present, the suggestion
text is built from the `reason` field alone. If neither `next` nor
`options` are present, the suggestion is dropped (no buttons sent).

### Post-Click UX (2026-06-26)

When a user clicks a dynamic option button, the suggestion message is updated
in-place before the agent response arrives:

1. **All buttons removed** — `reply_markup=None` (Telegram) or actions block
   replaced with a plain section (Slack)
2. **Selection shown** — "✓ Selected: {label}" appended to the message text
3. **Agent response** — arrives as a new message in the same thread/chat

This prevents double-clicks and gives immediate visual feedback. On Telegram,
if the in-memory prompt dict was lost (gateway restart), the message is edited
to remove buttons and the user sees "This suggestion has expired — please
re-request."

### Button Hierarchy (Slack)

Only the **first** option button gets `style: "primary"` (green). All
subsequent options use the default style. This creates a visual hierarchy
that guides the user toward the recommended first choice without hiding
alternatives.

### Council Review Pattern (2026-06-26)

For non-trivial design decisions (new features, UX changes, protocol
extensions), dispatch an `advisors` panel (`hermes chat -q` subprocesses):
send the design question + code context to a reasoning model for structured
review. The advisors panel returns a table of questions, verdicts, and
recommendations. This caught several issues in the dynamic options design:
options-only mode necessity, post-click UX gaps, button hierarchy, and
double-click guard requirements.

## Parser: `gateway/suggestion_parser.py`

```python
from gateway.suggestion_parser import extract_suggestion, Suggestion

cleaned_text, suggestion = extract_suggestion(response_text)
# cleaned_text: response with marker removed
# suggestion: Suggestion(next=..., learn=..., reason=..., can_do=..., options=..., raw_text=...) or None
```

The regex `SUGGESTION:\s*(\{.*?\})\s*$` only matches at end of text (DOTALL).
Invalid JSON or missing `next`/`learn` → returns `(original_text, None)`.

Options are capped at 8 in the parser (universal limit, both platforms).

## Adapter Pattern: `send_suggestion`

Modeled on `send_exec_approval`. Optional method — adapters without it are
unaffected.

### Telegram (`gateway/platforms/telegram.py`)

```python
async def send_suggestion(self, chat_id, suggestion_text, can_auto_execute=False, metadata=None, options=None):
    # Static mode (no options): InlineKeyboardMarkup with:
    #   Row 1: [✏️ Explain (sg:explain)] [▶️ Do it (sg:do)]  (Do it only if can_auto_execute)
    #   Row 2: [✕ Dismiss (sg:dismiss)]
    # Dynamic mode (options present): one button per option + Dismiss
    #   Each option button: callback_data = "sg:opt:{short_id}"
    #   Prompt stored in self._suggestion_options[short_id] (in-memory, expires on restart)
    # Uses _send_message_with_thread_fallback, ParseMode.MARKDOWN_V2
```

Callback handler in `_handle_callback_query` (prefix `sg:`):
- `sg:dismiss` → `query.edit_message_text(text=current_text, reply_markup=None)`
- `sg:explain` → injects synthetic `MessageEvent` with
  "Explain what you did in the previous response..."
- `sg:do` → injects synthetic `MessageEvent` with
  "Execute the suggested next step from the previous response."
- `sg:opt:{id}` → looks up prompt in `_suggestion_options`, edits message to
  show "✓ Selected: {label}" + removes buttons, injects prompt as synthetic
  `MessageEvent`. If prompt not found (expired), edits message to remove
  buttons and shows "This suggestion has expired — please re-request."

Synthetic messages use the same pattern as CLI handoff (`run.py:4695`):
```python
from gateway.session import SessionSource, Platform
from gateway.platforms.base import MessageEvent
source = SessionSource(platform=Platform.TELEGRAM, chat_id=..., ...)
event = MessageEvent(text=prompt, source=source, internal=True)
await self.handle_message(event)
```

Authorization reuses `_is_callback_user_authorized` (same as approval buttons).

### Slack (`gateway/platforms/slack.py`)

```python
async def send_suggestion(self, chat_id, suggestion_text, can_auto_execute=False, metadata=None, options=None):
    # Static mode: Block Kit: [divider] + [section: mrkdwn text] + [actions: buttons]
    #   Buttons: ✏️ Explain (hermes_suggest_explain, primary),
    #            ▶️ Do it (hermes_suggest_do, primary, only if can_auto_execute),
    #            ✕ Dismiss (hermes_suggest_dismiss)
    # Dynamic mode: one hermes_suggest_option button per option + Dismiss
    #   First option: style="primary" (green), rest: default
    #   value: option's prompt (up to 2000 chars)
    # Uses chat_postMessage with blocks=, thread_ts from _resolve_thread_ts
```

Action handler `_handle_suggestion_action`:
- Registered in `_start()` via `self._app.action(action_id)(self._handle_suggestion_action)`
- `hermes_suggest_dismiss` → `chat_update` to remove actions block
- `hermes_suggest_explain` / `hermes_suggest_do` → synthetic `MessageEvent`
  via `self.handle_message(event)`
- `hermes_suggest_option` → `chat_update` to replace actions block with
  "✓ Selected: {label}" section, then injects prompt as synthetic `MessageEvent`

Authorization reuses `SLACK_ALLOWED_USERS` env var (same as approval buttons).

### WhatsApp / Other Platforms

No `send_suggestion` method. The `SUGGESTION:` marker remains in the text
and is rendered as plain text by the SOUL.md directive. No code changes
needed.

## Base Adapter Integration (`gateway/platforms/base.py`)

In `_process_message_background`, after media extraction and before TTS/text
delivery, **always strip the marker** (even on platforms without
`send_suggestion`):

```python
_suggestion = None
from gateway.suggestion_parser import extract_suggestion
_cleaned, _suggestion = extract_suggestion(text_content)
if _suggestion:
    text_content = _cleaned
    if not hasattr(self, "send_suggestion"):
        # No interactive buttons — render as clean plain text.
        _line = f"\n\n⚡ Next: {_suggestion.next or _suggestion.learn}"
        if _suggestion.reason:
            _line += f" — {_suggestion.reason}"
        text_content = text_content + _line
```

**Critical**: Suggestion button delivery must be **outside** the
`if text_content:` guard so it runs even if the main text was empty
(marker-only response):

```python
# After the text send block (inside the `if response:` block,
# but OUTSIDE `if text_content:`):
if _suggestion and hasattr(self, "send_suggestion"):
    try:
        _next = _suggestion.next or _suggestion.learn
        _suggestion_text = f"⚡ Next: {_next}"
        if _suggestion.reason:
            _suggestion_text += f" — {_suggestion.reason}"
        await self.send_suggestion(
            chat_id=event.source.chat_id,
            suggestion_text=_suggestion_text,
            can_auto_execute=_suggestion.can_do,
            metadata=_thread_metadata,
            options=_suggestion.options,  # dynamic options
        )
    except Exception as _sg_err:
        logger.debug("[%s] send_suggestion failed: %s", self.name, _sg_err)
```

## Streaming Path: `gateway/stream_consumer.py`

**Quality fix**: The `_clean_for_display()` static method strips the
`SUGGESTION:` marker from streamed text in real-time, so users never see
raw JSON flash during streaming:

```python
# Class-level regex (added alongside _MEDIA_RE):
_SUGGESTION_RE = re.compile(r"SUGGESTION:\s*\{.*?\}\s*$", re.DOTALL)

# In _clean_for_display():
if "SUGGESTION:" not in text and ...:
    return text  # fast path
cleaned = ...
cleaned = GatewayStreamConsumer._SUGGESTION_RE.sub("", cleaned)
```

This was added during quality review — without it, streaming platforms
(Telegram, Slack — the primary channels) showed raw `SUGGESTION:{...}`
JSON in the streamed message before the button message arrived.

## Gateway Runner Integration (`gateway/run.py`)

`_deliver_suggestion_from_response` mirrors `_deliver_media_from_response`:

```python
async def _deliver_suggestion_from_response(self, response_text, event, source):
    from gateway.suggestion_parser import extract_suggestion
    cleaned_text, suggestion = extract_suggestion(response_text)
    if not suggestion:
        return
    adapter = self.adapters.get(source.platform)
    if not adapter or not hasattr(adapter, "send_suggestion"):
        return
    # Build text and call adapter.send_suggestion(...)
```

Called from the streaming post-delivery block (after `_deliver_media_from_response`,
before footer), wrapped in try/except so failures don't block the response.

## Testing

Parser tests: `tests/gateway/test_suggestion_parser.py` (10 cases).
No pytest in stripped venv — verify with inline `python -c "..."` script.

## Upstream PR

PR #51858 on NousResearch/hermes-agent.
Fork: `whichguy/hermes-agent-1` (GitHub fork remote).
Branch: `feature/interactive-suggestion-buttons-clean` (clean, from origin/main).
Local working branch: `local/telegram-task-checkboxes` (has the same changes
applied manually on top of unrelated work).

## Pitfalls

1. **Don't use `git cherry-pick` when branches diverged significantly.** The
   clean PR branch was built from `origin/main`, but the working branch had
   diverged (Telegram task checkboxes, plugin handlers, etc.). Cherry-pick
   produced massive conflicts in `run.py` (6760-line diff). Solution: apply
   the same patches manually on the working branch.

2. **Streaming raw JSON exposure.** Without `_SUGGESTION_RE` in
   `stream_consumer.py:_clean_for_display()`, the marker text is streamed
   to the user as raw `SUGGESTION:{"next": ...}` JSON before the button
   message arrives. Fix: add the regex to `_clean_for_display()` so the
   marker is stripped from the stream in real-time. The marker is still
   in the full response text for post-stream detection.

3. **Non-supported platforms show raw JSON.** If `base.py` only strips the
   marker when `hasattr(self, "send_suggestion")` is true, platforms without
   the method (WhatsApp, SMS, Signal) display raw JSON. Fix: **always strip**
   the marker, and on non-supported platforms convert it back to a clean
   text line (`⚡ Next: ... — ...`).

4. **Suggestion delivery inside `if text_content:` guard.** If the entire
   response is just the marker (no main text), `text_content` becomes empty
   after stripping, the text-send block is skipped, and suggestion buttons
   are never sent. Fix: move suggestion delivery **outside** the
   `if text_content:` guard.

5. **`git reset --hard` on a branch with untracked files.** New files
   (`suggestion_parser.py`, `test_suggestion_parser.py`) survive `git reset
   --hard` because they're untracked, not staged. But `git checkout` to
   another branch fails if those files exist on the target branch. Stash with
   `-u` before switching.

6. **`gh` CLI not installed.** Install without sudo by downloading the
   binary directly: `curl -fsSL "https://github.com/cli/cli/releases/download/
   v2.65.0/gh_2.65.0_linux_amd64.tar.gz" -o /tmp/gh.tar.gz && tar xzf
   /tmp/gh.tar.gz -C /tmp && cp /tmp/gh_*/bin/gh ~/.local/bin/gh`. Then use
   `gh pr create --repo NousResearch/hermes-agent --base main --head
   whichguy:feature/branch-name`.

7. **Options cap must be at parser level, not per-platform.** The parser
   caps at 8 universally. Platform-specific limits (Slack's 20) are
   irrelevant because the parser enforces the lower bound. This prevents
   platform-specific bugs where one platform renders more buttons than
   another.

8. **Post-click UX must disable buttons before injecting prompt.** If the
   prompt injection happens before the button edit, the user sees the
   agent response arrive while the old buttons are still visible, creating
   a confusing double-message flash. Always edit the suggestion message
   first, then inject the prompt.

9. **Telegram prompt dict is in-memory only.** Gateway restart loses all
   stored prompts. The handler must gracefully handle missing prompts by
   editing the message to remove buttons and showing an expiration notice.
   Do not leave stale buttons that do nothing when clicked.
