# Hermes Autonomy Configuration Audit

Reference for auditing and expanding Hermes autonomy settings. Derived from a
full config audit session (June 2026).

## Audit Methodology

1. Read `config.yaml` directly (find it via `echo $HERMES_HOME` then `$HERMES_HOME/config.yaml`)
2. Check `platform_toolsets` per platform — CLI is often under-provisioned vs Telegram/Slack
3. Cross-reference cron jobs (`cronjob action=list`) for what's already automated
4. Check `approvals`, `delegation`, `hooks`, `goals`, `memory`, `curator`, `kanban` sections
5. Identify gaps where config values still default to conservative settings

## Key Autonomy Levers (beyond persona/SOUL.md)

These are config-level changes, not prompt-level. They control what the agent
is *allowed* to do without asking.

| Lever | Config path | Conservative default | Autonomous setting | Risk |
|-------|-------------|----------------------|-------------------|------|
| Subagent auto-approve | `delegation.subagent_auto_approve` | `false` | `true` | Low — approvals.mode already gates destructive commands |
| Hook auto-accept | `hooks_auto_accept` | `false` | `true` | Low — only fires registered session hooks |
| Goal persistence | `goals.max_turns` | `20` | `40` | Low — just doubles persistence window |
| Nested delegation | `delegation.max_spawn_depth` | `1` | `2` | Medium — adds cost/complexity, evaluate after auto-approve |
| Approval mode | `approvals.mode` | `manual` | `auto` | Low — uses auxiliary LLM for smart gating |

## Platform Toolset Parity

CLI platform often has fewer toolsets than Telegram/Slack. Check
`platform_toolsets.cli` vs `platform_toolsets.telegram` and add missing:
- `messaging` — send to other platforms from TUI
- `computer_use` — desktop automation
- `tts` — voice output
- `kanban` — work queue interaction

Note: `hermes-cli` toolset bundles many core tools (terminal, file, web, memory,
delegation, cronjob, session_search, skills, vision, browser, todo, image_gen).
So the gap is usually only in the auxiliary/optional toolsets.

## Config Editing Without System PyYAML

On hosts where system Python lacks PyYAML (PEP 668 externally-managed),
use the Hermes venv Python:

```bash
/opt/hermes/.venv/bin/python3 -c "
import yaml
with open('/opt/data/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
# ... modify ...
with open('/opt/data/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
"
```

`uv pip install` won't work on externally-managed system Python. The Hermes
venv at `/opt/hermes/.venv/` has PyYAML pre-installed.

## Applying Changes In One Shot

When a user approves a multi-phase plan and ALL phases are low-risk + reversible,
apply ALL phases in a single tool call batch. Do not gate each phase behind
separate confirmation — the user doesn't want to babysit phase progression.

Read the full config, apply all changes, write once, verify once.

## Monitoring Tier

Items that are NOT immediately applied but tracked for future evaluation:
- `delegation.max_spawn_depth: 2` — wait until subagent auto-approve is in use
- Google Drive MCP servers — need OAuth credentials in .env
- `x_search` toolset — add when a use case emerges
- Kanban orchestrator profile — only for multi-profile setups
- `tool_loop_guardrails.hard_stop_enabled` — evaluate after auto-approve to
  check if subagents burn tokens on retry loops