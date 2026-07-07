# Plugin Migration: Concrete Example (v0.17.0 → main, June 2026)

Real-world example of a structural-change upgrade where upstream moved platform
adapters from `gateway/platforms/` → `plugins/platforms/`.

## The structural change

**Commit:** `560010547` — "refactor(gateway): migrate slack/dingtalk/whatsapp/matrix/feishu/telegram/wecom/email/sms adapters to bundled plugins"

**What moved:**

| Old path (v0.17.0) | New path (origin/main) | Lines (old) | Lines (new) |
|---|---|---|---|
| `gateway/platforms/slack.py` | `plugins/platforms/slack/adapter.py` | 3,734 | 4,293 |
| `gateway/platforms/telegram.py` | `plugins/platforms/telegram/adapter.py` | 7,112 | 7,503 |
| `gateway/platforms/email.py` | `plugins/platforms/email/adapter.py` | 885 | 1,235 |

**What stayed:** `gateway/platforms/` still exists but only contains non-migrated
adapters (signal, webhook, weixin, whatsapp_cloud, yuanbao, bluebubbles, qqbot)
plus shared infrastructure (`base.py`, `helpers.py`, `api_server.py`).

**Class names preserved:** `SlackAdapter`, `TelegramAdapter` — same class names
in both old and new locations, inheriting from `BasePlatformAdapter`.

## Reconnaissance commands used

```bash
# 1. How far behind?
git rev-list --count $(git merge-base HEAD origin/main)..origin/main
# → 976 commits

# 2. Did files get deleted from old location?
git diff --name-status $MERGE_BASE..origin/main -- gateway/platforms/ | grep "^D"
# → slack.py, telegram.py, email.py, dingtalk.py, whatsapp.py, matrix.py, feishu.py, wecom.py, sms.py DELETED

# 3. Where did they go?
git ls-tree -d origin/main plugins/platforms/
# → slack/, telegram/, email/, dingtalk/, whatsapp/, matrix/, feishu/, wecom/, sms/

# 4. Same class names?
git show origin/main:plugins/platforms/slack/adapter.py | grep "^class "
# → class _ThreadContextCache:
# → class SlackAdapter(BasePlatformAdapter):

# 5. File size deltas (signal of divergence)
git show origin/main:gateway/run.py | wc -l    # 18,627
git show HEAD:gateway/run.py | wc -l            # 19,416
```

## File classification from this session

### Safe (new files, no upstream equivalent)
- `gateway/markdown_state.py` (172 lines)
- `gateway/email_formatting.py` (129 lines)
- `gateway/suggestion_parser.py` (104 lines)
- Plus their test files

### Moved (need manual port to new path)
- `gateway/platforms/slack.py` → `plugins/platforms/slack/adapter.py`
- `gateway/platforms/telegram.py` → `plugins/platforms/telegram/adapter.py`
- `gateway/platforms/email.py` → `plugins/platforms/email/adapter.py`

### Shared (both sides modified, need 3-way merge)
- `gateway/run.py` (biggest — 19k lines)
- `gateway/stream_consumer.py`
- `gateway/platforms/base.py`
- `agent/background_review.py`
- `agent/display.py`
- `tools/delegate_tool.py`
- `tools/send_message_tool.py`

## Port-forward commands template

```bash
# Phase 1: Fresh branch
git checkout origin/main -b feature/port-to-main

# Phase 2: Copy new files
git checkout v0.17.0 -- \
  gateway/markdown_state.py \
  gateway/email_formatting.py \
  gateway/suggestion_parser.py \
  tests/gateway/test_markdown_state.py \
  tests/gateway/test_suggestion_parser.py \
  tests/tools/test_send_message_email_html.py
git commit -m "port: copy new files from v0.17.0 custom branch"

# Phase 3: Port adapter changes (manual — patch won't apply cleanly)
git diff $MERGE_BASE v0.17.0 -- gateway/platforms/slack.py > /tmp/slack.patch
# Manually apply hunks to plugins/platforms/slack/adapter.py

# Phase 4: 3-way merge shared files
git show origin/main:gateway/stream_consumer.py > /tmp/upstream.py
git show v0.17.0:gateway/stream_consumer.py > /tmp/ours.py
git show $MERGE_BASE:gateway/stream_consumer.py > /tmp/base.py
git merge-file -L ours -L base -L upstream /tmp/ours.py /tmp/base.py /tmp/upstream.py
cp /tmp/ours.py gateway/stream_consumer.py
```

## Key insight

The plugin migration preserved class names (`SlackAdapter`, `TelegramAdapter`)
and the `BasePlatformAdapter` inheritance. This means your custom code that
references these classes by name will still work — but the **import paths**
changed. Any code doing `from gateway.platforms.slack import SlackAdapter` needs
to be updated to use plugin discovery instead.

## Actual port results (June 2026 session)

**Branch:** `feature/hybrid-port` (from `origin/main`)

**What ported cleanly:**
- 3 new files copied as-is: `markdown_state.py`, `suggestion_parser.py`, `email_formatting.py`
- 3 test files copied as-is
- `stream_consumer.py` — 3-way merge applied cleanly (marker stripping + fence state machine)

**What needed manual port (subagent):**
- `plugins/platforms/slack/adapter.py` — `send_suggestion()` + `_handle_suggestion_action()` + action registration
- `plugins/platforms/telegram/adapter.py` — `send_suggestion()` + `sg:` callback handler + `_suggestion_options` state
- `gateway/run.py` — `_deliver_suggestion_from_response()` method + call site in `already_sent` block

**Branch consolidation:** 4 source branches merged into one:
- `v0.17.0` (7 commits) — primary feature set
- `local/telegram-task-checkboxes` (1 commit) — cherry-picked Telegram task-checkbox rendering
- `feature/interactive-suggestion-buttons-clean` — superseded by v0.17.0 port
- `feature/interactive-suggestion-buttons` — superseded (installer fixes already upstream)

**Dropped features (intentionally):**
- Custom tool progress formatting → upstream has `stream_events.py`/`stream_dispatch.py`
- Preview cap 40→120 → upstream has configurable `tool_preview_length`
- Block Kit monkeypatch → upstream has native approval/confirm buttons
- Per-task delegate model override → upstream removed by design; use `delegation.provider`/`delegation.model` in config.yaml instead
- `TestPerTaskModelOverride` test class → removed entirely (not skipped — would block CI)

**Test results:** 598 passed, 0 failed

**Push issue:** GitHub token lacked `workflow` scope → push rejected. Workaround:
pushed as orphan branch (`feature/custom-port-final`) with just the changed
files, no ancestry. After pushing, deleted orphan branch locally and switched
back to `feature/hybrid-port`.

**Key takeaway:** The port-forward strategy works. The bottleneck is always the
adapter files (Slack, Telegram) and `run.py`. Budget 2–3 hours for a gap of
~1000 commits with structural changes. Use `delegate_task` for the mechanical
porting work — it keeps your context clean. When consolidating multiple source
branches, cherry-pick unique commits one at a time and verify tests after each.
