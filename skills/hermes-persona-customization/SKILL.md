---
name: hermes-persona-customization
description: "Use when modifying Hermes agent behavior via SOUL.md, personality directives, or system prompt configuration. Covers HERMES_HOME path resolution, system prompt layering, session-type exclusions, platform-aware formatting, and phased implementation (prompt → skill → code)."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [hermes, persona, soul-md, behavior, system-prompt, customization]
    related_skills: [hermes-agent, messaging-platform-formatting]
---

# Hermes Persona & Behavior Customization

## Overview

Modify how Hermes communicates and behaves by editing persona files and system prompt directives. The primary lever is SOUL.md — the agent identity file injected as slot #1 in the system prompt. This skill covers the full lifecycle: finding the right file, understanding what reaches which session types, writing directives that work across platforms, and knowing when to escalate from prompt-level to code-level.

## When to Use

- User wants to change Hermes' communication style, response format, or default behaviors
- Adding structured post-response blocks (tutorials, next-steps, tips)
- Configuring adaptive behavior based on user familiarity
- Implementing session-type exclusions (no suggestions in cron, subagents, etc.)
- Debugging "why isn't my SOUL.md directive working?"

Don't use for:
- One-off project instructions (those go in AGENTS.md)
- Model/provider config (use `hermes model` or config.yaml)
- Tool enable/disable (use `hermes tools`)

## Critical: Finding the Right SOUL.md

**The #1 pitfall is editing the wrong file.** There are often multiple SOUL.md files on disk, but only ONE is loaded.

### How to Find the Active File

```bash
echo $HERMES_HOME  # The active Hermes home directory
```

The loaded SOUL.md is at: `$HERMES_HOME/SOUL.md`

The code path (from `agent/prompt_builder.py:1369`):
```python
soul_path = get_hermes_home() / "SOUL.md"
```

`get_hermes_home()` resolves in this order:
1. `$HERMES_HOME` env var if set
2. `~/.hermes/` (default)

### Common Mismatches

| Scenario | Wrong Path | Correct Path |
|---|---|---|
| Custom `HERMES_HOME=/opt/data` | `/opt/data/.hermes/SOUL.md` | `/opt/data/SOUL.md` |
| Default install | `~/.hermes/.hermes/SOUL.md` | `~/.hermes/SOUL.md` |
| Profile mode | `~/.hermes/SOUL.md` | `~/.hermes/profiles/<name>/SOUL.md` |

**Always verify**: `echo $HERMES_HOME` before writing. If the file you're editing doesn't start with `$HERMES_HOME/SOUL.md`, it won't be loaded.

### The Dead File Detector

If a SOUL.md file exists under a `.hermes/` subdirectory, it is almost certainly a stale artifact from a prior install layout. The `.hermes/` directory is for plans/scratch/scripts, not the Hermes home itself.

## System Prompt Layering

The system prompt is assembled in three tiers (from `agent/system_prompt.py`):

| Tier | What's in it | Cached? | Changes when? |
|---|---|---|---|
| **Stable** | SOUL.md identity, tool guidance, skills index, platform hints, env hints | Yes (prefix cache) | Session start only |
| **Context** | AGENTS.md, .cursorrules, system_message | Yes | Working dir changes |
| **Volatile** | Memory, user profile, timestamp | No | Every turn |

SOUL.md is in the **stable** tier — slot #1. It's loaded once per session and cached. But the SOUL.md file comment says "loaded fresh each message" — this is because the file is re-read from disk on prompt rebuild (after compression), not because it's re-injected every turn.

### What This Means for Directives

- Changes to SOUL.md take effect on the **next message** (no restart needed, per the file's own documentation)
- But prompt caching means the *content* is stable for the session — if you change SOUL.md mid-session, it won't take effect until the next prompt build
- For immediate effect: `/reset` (CLI) or `/restart` (gateway)

## Session-Type Reach

Not all session types load SOUL.md. This determines whether your directive reaches that context.

| Session Type | Loads SOUL.md? | Why | Code path |
|---|---|---|---|
| Interactive (CLI, Slack, Telegram, etc.) | ✅ Yes | Default behavior | `load_soul_identity=True` |
| Cron jobs | ✅ Yes | "Some execution modes still want HERMES_HOME persona" | `load_soul_identity=True` in `system_prompt.py:91` |
| Subagents (delegate_task) | ❌ No | `skip_context_files=True` | SOUL.md not loaded |
| Kanban workers | ✅ Yes (but dominated by KANBAN_GUIDANCE) | Kanban guidance overrides | `load_soul_identity=True` |

### Implications for Behavioral Directives

- **Cron sessions WILL see your directive** — you must explicitly write "Never include in cron sessions" in the directive text for prompt-level exclusion
- **Subagents will NEVER see your directive** — exclusion is built-in
- **Kanban workers see it but kanban guidance dominates** — usually safe

For hard exclusion (code-level, not just prompt-level), you need a post-processor in the agent loop — that's a code change, not a persona change.

## Writing Effective Directives

### Structure

```markdown
## Directive Name

After **[trigger condition]** responses, [what to do]. This replaces [old behavior] — [why].

### When to Include
**Include** after: [list of trigger scenarios]
**Skip** for: [list of exclusion scenarios]
**Never include** in: [session types that must be excluded]

### Format
[Exact format with code block example]

### Rules
- [Numbered constraints]

### Adaptive Depth
[If behavior should vary by user familiarity]

### What to Avoid
- [Common mistakes]
```

### Key Principles (from ShapeofAI research)

1. **Anchor in what just happened** — no generic suggestions
2. **Show why** — each recommendation needs a reason
3. **Keep it short** — max 2-3 items, not a second response
4. **Balance depth and breadth** — mix zoom-in and zoom-out options
5. **Visually separate** — horizontal rule or distinct formatting
6. **Less critical as memory builds** — adaptive depth reduces over time

### Platform-Aware Formatting

**Key insight**: Hermes auto-converts standard markdown to each platform's native format via `format_message()` in each platform adapter (`gateway/platforms/<platform>.py`). So directives can use standard markdown (`**bold**`, `` `code` ``, `## Header`) and the gateway handles conversion. But `---` (horizontal rule) only renders on Telegram — on Slack and WhatsApp it shows as literal dashes.

| Platform | Bold | Italic | Code | Headers | `---` Divider | Links | Max Suggestion Lines | Format Approach |
|---|---|---|---|---|---|---|---|---|
| **Telegram** | ✅ `**bold**` | ✅ `*italic*` | ✅ `` `code` `` | ✅ `## H` | ✅ renders as divider | ✅ `[text](url)` (adapter converts to MarkdownV2) | 3 | Full markdown, `---` separator, Markdown links |
| **Slack** | ✅ `*bold*` (auto-converted from `**`) | ✅ `_italic_` | ✅ `` `code` `` | ✅ → `*bold*` | ❌ literal dashes | ✅ → `<url\|text>` | 2 | Bold separator, no `---` |
| **WhatsApp** | ✅ `*bold*` (auto-converted from `**`) | ✅ `_italic_` | ✅ `` `code` `` | ✅ → `*bold*` | ❌ literal dashes | ❌ → `text (url)` | 2 | Bold separator, no `---` |
| **CLI** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 3 | Full markdown |
| **Email** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 3 | Full markdown |
| **SMS/Signal** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 1 | Plain text only |

**Rules**:
- Use standard markdown in directives — the gateway converts per platform
- Don't use `---` on Slack or WhatsApp — it renders as literal dashes. Use a blank line + bold labels instead
- On SMS/Signal, use plain text only: `Next: actionable step — reason`
- Each platform's `format_message()` handles: `**bold**` → native bold, `## Header` → native bold, `[text](url)` → native link format

## Phased Implementation

When adding a new behavioral directive:

### Phase 0: Prompt-level (SOUL.md)
- Edit `$HERMES_HOME/SOUL.md` directly
- Zero code, zero risk
- LLM self-classifies (inconsistent but acceptable for v1)
- Test for 1-2 weeks
- Session-type exclusion is prompt-level (leaky for cron)

### Phase 1: Skill + slash command
- Formalize as a skill with format templates, examples, pitfalls
- Add a slash command for per-session control (e.g., `/suggestions on|off`)
- Add config toggle in config.yaml
- Platform-specific format adjustments

### Phase 2: Code-level post-processor
- Post-processor in agent loop (after LLM response, before delivery)
- Hard session-type exclusion (no cron, no subagents)
- Platform-aware formatting at code level
- Truncation guards (e.g., Telegram 4096 char limit)
- Use cheap model for suggestion generation if second LLM call needed

## Common Pitfalls

1. **Editing the wrong SOUL.md file.** Always verify with `echo $HERMES_HOME` first. The `.hermes/` subdirectory is NOT the Hermes home.

2. **Assuming subagents load SOUL.md.** They don't — `skip_context_files=True` prevents it. If you need a directive to reach subagents, it must be in AGENTS.md or injected via the delegation context.

3. **Expecting cron to skip directives automatically.** Cron sessions DO load SOUL.md. You must write explicit exclusion text in the directive for prompt-level exclusion.

4. **Using `---` horizontal rule on Slack or WhatsApp.** `---` only renders as a divider on Telegram. On Slack and WhatsApp it shows as literal dashes. Use a blank line + bold labels instead. This was discovered by reading `gateway/platforms/slack.py` `format_message()` and `gateway/platforms/whatsapp.py` `format_message()` — neither converts `---` to a native divider.

5. **Using markdown formatting on WhatsApp/Signal.** These platforms render markdown as literal characters.

5. **Layering new directives without removing old ones.** If the new directive replaces an existing behavior (like "recommended next step"), explicitly remove or supersede the old text in SOUL.md. Don't layer — the LLM may follow both.

7. **Forgetting prompt caching implications.** SOUL.md is in the stable tier. Mid-session edits won't take effect until the next prompt rebuild (compression or `/reset`).

8. **Suggesting instead of doing.** If the next step is low-risk and reversible, the existing "Be proactive and autonomous" persona already says to just do it. The suggestion block should only surface things needing user decision or verification. Don't suggest "verify the deploy" — go verify it and report. Suggest "email Albert Shin" — that needs user context Hermes doesn't have.

9. **Over-suggesting.** CHI 2025 study found that more frequent/more numerous suggestions performed *worse*. The default should be silence — only append the block when there's a genuinely non-obvious next step the user needs to take or verify. Better to stay silent than suggest something irrelevant.

## Verification Checklist

- [ ] Verified `$HERMES_HOME` before writing to SOUL.md
- [ ] Directive has explicit trigger conditions (when to include/skip)
- [ ] Session-type exclusions are explicit in the directive text
- [ ] Platform-aware formatting with plain-text fallback for non-markdown platforms
- [ ] Old directive text removed or explicitly superseded (not layered)
- [ ] Wiki plan document created for complex multi-phase implementations
- [ ] Memory updated with any new HERMES_HOME path discoveries

## Key Design Principles (from community research)

1. **Default to silence** — better to stay silent than suggest something irrelevant. Irrelevant suggestions train users to ignore all future suggestions (MindStudio, ChatGPT backlash, CHI 2025).
2. **Do, don't suggest** — if the next step is low-risk and reversible, Hermes should just DO it per the existing proactive persona. The suggestion block is only for things needing user decision or verification (Reddit "Absolute Mode" movement).
3. **Fewer is better** — CHI 2025 study found Persistent Suggest (5 items, frequent) performed *worse* than standard Suggest (3 items, less frequent). More suggestions = worse performance.
4. **Low false-positive tolerance** — surface only meaningful signals. One irrelevant suggestion damages trust in all future suggestions.

## Interactive Button Infrastructure (Phase 1 — Implemented ✅)

The `SUGGESTION:{...}` marker protocol is now implemented and **proven in production** (Jun 26, 2026). The LLM appends a structured JSON marker at the end of its response; the gateway detects it, strips it from the visible text, and delivers it as interactive buttons on platforms that support them.

**Production confirmation:** A Slack button click dispatched `"Tell me a joke about Slack integrations"` through the gateway with zero errors — no triangle, no `no_text`, no `wrapper_descriptor`. The middleware correctly acked the `block_actions` payload and dispatched the suggestion text as a new inbound message.

**Dynamic options mode (2026-06-26):** When the SUGGESTION marker includes an `options` field, the adapter renders one green primary button per option instead of the static Explain/Do it/Dismiss buttons. Each button's click injects the option's `prompt` as a synthetic user message. See `references/interactive-suggestion-buttons-implementation.md` for the full marker format with `options`, platform limits, and design principles.

**Architecture:** Two complementary approaches work together:
1. `platform_registry.create_adapter` wrapper — handles `send()`/`edit()` patches, Home Tab publishing, and `_pop_slash_context` integration
2. `AsyncApp.__init__` middleware — catches all `block_actions` with exact action ID allow-list and dispatches suggestion text

See `hermes-slack-gateway` skill for the full implementation details, pitfalls, and Kimi audit findings.

### Quality Review Fixes (Important)

Three issues were found and fixed during quality review — these are easy to miss when implementing the pattern:

1. **Streaming raw JSON exposure**: Without `_SUGGESTION_RE` in `stream_consumer.py:_clean_for_display()`, the marker appears as raw JSON in the streamed text. Fix: add the regex to strip it from the stream in real-time. The marker is still in the full response for post-stream detection.

2. **Non-supported platforms show raw JSON**: If `base.py` only strips the marker when `hasattr(self, "send_suggestion")` is true, platforms without the method (WhatsApp, SMS, Signal) display raw JSON. Fix: **always strip** the marker, and convert back to clean text on non-supported platforms.

3. **Empty response after marker strip**: If the entire response is just the marker, `text_content` becomes empty after stripping, the text-send block is skipped, and buttons are never sent. Fix: move suggestion delivery **outside** the `if text_content:` guard.

See `references/interactive-suggestion-buttons-implementation.md` for the full implementation guide — marker format, adapter patterns, callback handlers, streaming path, and quality review fixes.

## Autonomy Configuration Audit

Beyond persona/SOUL.md directives, Hermes has config-level autonomy levers
that control what the agent is *allowed* to do without asking. These include
subagent auto-approve, hook auto-accept, goal persistence, approval mode,
and platform toolset parity. For a full audit methodology, lever table, and
the PyYAML-without-system-pip workaround, see
`references/hermes-autonomy-config-audit.md`.

**Key lesson:** When a user approves a multi-phase config plan and all phases
are low-risk + reversible, execute ALL phases in one shot. Do not gate each
phase behind separate confirmation.

## References

- `references/llm-interaction-design-research.md` — Condensed research on post-response suggestion patterns from ShapeofAI, ChatGPT, Claude Artifacts, Follow-up Chips, proactive agent research, and Cursor. Read when designing new behavioral directives informed by LLM interaction UX patterns.
- `references/community-research-and-interactive-capabilities.md` — Community feedback (Reddit, HN, OpenAI forums) on follow-up suggestions, "Absolute Mode" anti-suggestion movement, CHI 2025 proactive assistant study, CMSWire UX patterns, MindStudio proactive AI principles. Plus Hermes interactive button infrastructure audit (Telegram inline keyboards, Slack Block Kit, WhatsApp limitations) with Phase 1 implementation pattern.
- `references/hermes-streaming-message-fragmentation.md` — Diagnosing and fixing "multiple separate messages instead of in-place updates" — config keys that interact to cause message fragmentation (`fresh_final_after_seconds`, `interim_assistant_messages`, `tool_progress`, `cleanup_progress`), recommended Slack config, architecture notes, and platform-specific limitations.