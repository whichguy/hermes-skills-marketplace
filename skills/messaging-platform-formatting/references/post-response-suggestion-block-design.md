# Post-Response Suggestion Block — Full Design Reference

> Session: 2026-06-24. Research + lifecycle analysis for appending a tutorial/explanation/next-action block after non-tactical Hermes responses.
> Plan document: [[post-response-suggestion-block-plan]] in wiki.

## Research Sources

### Claude Artifacts (code.claude.com/docs/en/artifacts)
- Shareable interactive HTML pages published from Claude Code sessions (PR walkthroughs, dashboards, comparison layouts).
- NOT post-response tutorials — a *medium change* (terminal → visual web page).
- Prompting patterns relevant: "walk through change" (annotated diffs), "compare alternatives" (side-by-side grid), "bring result back to session" (Copy-as-prompt button).
- Claude applies a built-in *design skill* and looks for your design system first.

### ChatGPT Follow-Up Suggestions
- Clickable chips after each response suggesting 2-4 next questions.
- **User sentiment strongly negative**: OpenAI community forum thread "Disable or Customize the Follow-Up Suggestions" — "disruptive," "clutter the interface," "interrupt flow," "even when it promises not to do it it still does."
- Even after adding a settings toggle, users report it can't be fully suppressed on all platforms.
- **Lesson**: Forced suggestions breed resentment. Must be opt-in, suppressible, genuinely useful.

### ShapeofAI "Follow Up" Pattern (shapeof.ai/patterns/follow-up, Emily Campbell, CC-BY)
- Most rigorous UX treatment found.
- Key principles:
  1. **Anchor in what just happened** — base suggestions on the last response, avoid generic next steps.
  2. **Show why** — make the connection clear ("You could also ask…" / "Related topics include…").
  3. **Keep it short and scannable** — 2-4 high-value items max.
  4. **Balance depth and breadth** — mix 1-2 "zoom in" (refine/elaborate) with 1 "zoom out" (pivot/generalize).
  5. **Visually separate** from main output — treat as "light invitations," not part of the answer.
  6. **Less critical as memory builds** — follow-ups become more personalized and less necessary over time.
- Key insight: "Successful follow ups can serve as a pseudo sample prompt, borrowing context from the initial request and giving the user the sense that the AI is moving forward with them."

### Follow-Up Chips (aiuxplayground.com/pattern/follow-up-chips)
- Clickable suggestion buttons after AI responses. Ideal for "search engines, educational tools, and discovery tools."
- Reduces cognitive load by proactively suggesting next steps.

### Proactive Agent Research (arXiv 2410.12361, ICLR 2025)
- Shifting LLM agents from reactive to proactive.
- Agents that anticipate tasks based on user activity, environment state, and context.
- Hermes already does a version of this via system prompt ("proactive and autonomous… infer the likely next need").

### Cursor "Plan Before Code" Pattern
- End prompts with "Investigate and outline your approach step-by-step. Don't code, just tell."
- Generates structured plan with checkpoints. "Stop and recap" pattern.
- More about pre-response planning, but shows value of structured next-step framing.

## Lifecycle Consequences

### Trigger Classification

Gray zone: a complex task ending with a brief "Done" message → **include block** because the journey was non-tactical; user may not know what to verify next. The trigger should be based on what preceded the response, not just the final message length.

Classification options:
- **LLM self-classifies** (system prompt directive): simplest, but inconsistent.
- **Post-processor classifies** (code-level): consistent, but requires heuristics or second LLM call.
- **Always generate, post-processor strips**: wasteful.

### Platform Consequences (verified against Hermes source)

Hermes auto-converts standard markdown to each platform's native format via `format_message()` in each platform adapter. The directive can use standard markdown and the gateway handles conversion. Key difference: `---` (horizontal rule) only renders on Telegram — on Slack and WhatsApp it shows as literal dashes.

| Platform | Bold | Italic | Code | Headers | `---` Divider | Links | Max Lines | Format Approach |
|---|---|---|---|---|---|---|---|---|
| **Telegram** | ✅ `**bold**` | ✅ `*italic*` | ✅ `` `code` `` | ✅ `## H` | ✅ renders as divider | ✅ `[text](url)` | 3 | Full markdown, `---` separator |
| **Slack** | ✅ `*bold*` (auto-converted) | ✅ `_italic_` | ✅ `` `code` `` | ✅ → `*bold*` | ❌ literal dashes | ✅ → `<url\|text>` | 2 | Bold separator, no `---` |
| **WhatsApp** | ✅ `*bold*` (auto-converted) | ✅ `_italic_` | ✅ `` `code` `` | ✅ → `*bold*` | ❌ literal dashes | ❌ → `text (url)` | 2 | Bold separator, no `---` |
| **CLI** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 3 | Full markdown |
| **Email** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 3 | Full markdown |
| **SMS/Signal** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 1 | Plain text only |
| **Cron** | N/A | N/A | N/A | N/A | N/A | N/A | 0 | Must never appear |

Source: `gateway/platforms/slack.py` `format_message()` converts `**bold**`→`*bold*`, `## Header`→`*Header*`, `[text](url)`→`<url|text>`. `gateway/platforms/whatsapp.py` `format_message()` converts `**bold**`→`*bold*`, `## Header`→`*bold*`, `[text](url)`→`text (url)`. `gateway/platforms/telegram.py` converts to MarkdownV2 with `_escape_mdv2()`.

### Session-Type Exclusions

- ❌ Cron job sessions (cron platform prompt already says "no user present")
- ❌ Subagent/delegation summaries (subagents have `skip_context_files=True`, don't load SOUL.md — exclusion is built-in)
- ❌ Kanban worker sessions
- ❌ Automated monitoring output
- ✅ Interactive human-facing sessions only

### Conversation Flow Impact

- The LLM needs to track what it already suggested to avoid repetition (stored in conversation context).
- After context compression, old blocks are lost — which is fine (suggestions most valuable early in session per ShapeofAI research).
- Prompt caching: SOUL.md directive is static, cached after first hit. Minimal cache impact.
- Message role alternation: block is part of assistant message, no violation. ✅

### Cost Model

- Per non-tactical response: ~95-185 tokens (tutorial + next steps + formatting)
- Session-level (~9 non-tactical responses × ~140 tokens): ~1,260 extra tokens, ~8-12% overhead
- System prompt addition: ~200 tokens one-time, cached after first hit
- Phase 2 post-processor (if used): +1-3s latency, ~640 tokens per call with cheap model

### Adaptive Depth (via memory)

| User Familiarity | Learn | Next | Tip |
|---|---|---|---|
| New user | Rich, explains tools | Specific, actionable | Surface features |
| Experienced | Skip or 1-liner | Advanced, non-obvious | Skip unless novel |
| Power user (Jim) | Skip entirely | Only non-obvious next steps | Only new skills/features |

### Failure Modes

| Failure | Cause | Mitigation |
|---|---|---|
| Suggestion wrong/misleading | LLM hallucinates next step | Conservative — "verify" not "do" |
| Suggestion redundant | LLM didn't check context | Prompt: "don't suggest what was already discussed" |
| Tutorial condescending | LLM explains basic concepts to expert | Memory-based depth adjustment |
| Block on cron output | Prompt-only rule leaks | Phase 2: code-level session-type exclusion |
| Block exceeds Telegram 4096 | Long response + block | Phase 2: post-processor truncation guard |
| Block suggests unavailable feature | "Try /skill" on WhatsApp | Platform-aware suggestions in prompt |
| User can't disable | No kill switch | Phase 1: `/suggestions on\|off` + config toggle |
| Subagent summary has block | delegate_task inherits prompt | Strip blocks in subagent result post-processing (Phase 2) |

## Implementation Phases

### Phase 0 (now): Personality directive in SOUL.md
- Edit `~/.hermes/SOUL.md` (slot #1 in system prompt).
- Zero code changes, zero risk.
- LLM self-classifies tactical vs non-tactical (inconsistent but acceptable for v1).
- Cron/subagent exclusion via prompt directive + built-in `skip_context_files=True`.

### Phase 1 (if Phase 0 shows value): Skill + slash command
- Create skill with format templates, examples, pitfalls.
- Add `/suggestions on|off` slash command for per-session control.
- Add config toggle `agent.post_response_suggestions: true/false`.
- Platform-specific format adjustments.

### Phase 2 (if Phase 1 proves durable): Code-level post-processor
- Post-processor in agent loop, after LLM response, before delivery.
- Session-type exclusion (hard code): no cron, no subagents, no kanban workers.
- Platform-aware formatting (compact for WhatsApp, full for CLI).
- Truncation guards (Telegram 4096 char limit).
- Use cheap model (Haiku) for suggestion generation if second LLM call needed.

## Example Responses (per-channel)

### Example 1: Research task — Telegram (richest, `---` divider)
> User: What's the latest on the Canyon Creek solar project?

**Main response** (4 paragraphs about solar project status)

---

**📚 Learn** · Queried the wiki first (`[[canyon-creek-solar-project]]`) since you've been tracking this — faster than re-deriving from web sources.

**⚡ Next**: `Email Albert Shin the updated timeline` — the trenching change order expires Jul 15 and he hasn't been notified of the slip

### Example 2: Code task — Slack (compact, no `---`)
> User: Write a script to parse USAW meet cards from PDFs

**Main response** (30 lines of Python, usage example)

*📚 Learn* · Used `pymupdf` for text extraction because meet cards are structured PDFs — `pdfplumber` would also work but adds a dependency you don't need here.
*⚡ Next*: `Test with the 3 sample PDFs in ~/usaw/meet-cards/` — confirms the regex handles hand-written annotations

### Example 3: Quick lookup (tactical — no block)
> User: What time does the Hyatt check in?

**Main response**: Check-in is 3:00 PM at the Hyatt House Colorado Springs.

*(No suggestion block — tactical response, single fact)*

### Example 4: Multi-step task — WhatsApp (2-line max, no `---`)
> User: Set up the approval workflow for the FS board expense reviews

**Main response** (5 tool calls, config changes, test results)

*⚡ Next*: `Send Family Member the /approve command reference` — she's the secondary approver and needs the command syntax
*💡 Tip*: The `approval-workflow-engine` skill has a `--dry-run` flag to test without sending real approvals

### Example 5: SMS / Signal (plain text only)
> User: Did the cron job run?

Next: check gateway logs for the self-healing watchdog — it may have auto-repaired a failed job