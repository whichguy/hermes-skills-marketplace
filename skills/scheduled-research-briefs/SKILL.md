---
name: scheduled-research-briefs
description: Design, run, and refine scheduled research/monitoring briefs that synthesize
  current information into concise blog-like recommendations instead of raw dumps.
version: 1.0.0
author: Hermes Agent
metadata:
  hermes:
    tags:
    - cron
    - research
    - monitoring
    - executive-brief
    - synthesis
    - telegram
    created_by: agent
    config:
    - key: scheduled-research-briefs.enabled
      description: Enable scheduled-research-briefs skill behavior
      default: true
      prompt: Enable scheduled-research-briefs skill?
    category: research
platforms:
- linux
- macos
- windows
license: MIT
---


# Scheduled Research Briefs

## When to use

Use this skill when creating, updating, running, or reviewing recurring research jobs, monitoring reports, daily digests, optimization reviews, repository watchlists, ecosystem scans, or other scheduled briefings.

This includes jobs that use Hermes cron, web search, GitHub/API checks, RSS/blog monitoring, session_search, or skills research to produce user-facing updates.

## Core principle

A scheduled research job should deliver **decision-ready synthesis**, not a transcript of everything it found.

For Jim, default to a concise, Telegram-readable, blog-like executive brief:

- Explain what the topic is and why it matters.
- Synthesize 3–5 insights rather than listing every source.
- Give 1–3 recommendations with adopt/adapt/reject/monitor framing when applicable.
- Include a balanced pros/cons section for the most important idea.
- End with a clear bottom line and one suggested next action.
- Cite only a few high-quality sources with one-line context.

If the user says a report is “too much text,” “hard to read,” or asks for “blog-like” / “informational” output, patch the scheduled job prompt immediately rather than merely apologizing.

If the user complains that a scheduled brief/update is poorly formatted or shows UTC/raw timestamps, treat that as a first-class scheduled-brief defect: patch the existing cron job prompt and, when there is a precheck/script, patch the script to emit local timezone context and friendly local-time labels. Do not only explain the issue back to the user.

## Recommended report shape

Use this as the default structure unless the user requests otherwise:

```markdown
## Today's focus
2–3 sentences explaining the theme in plain English.

## Key insights
3–5 bullets. Each says what it is, why it matters, and confidence/source recency.

## Recommendations
Only the best 1–3. For each:
- Recommendation: adopt / adapt / reject / monitor
- Why: concise rationale
- Effort: low / medium / high
- Risk: low / medium / high, including privacy/security notes

## Pros and cons
A balanced discussion of the main idea/tool.

## Notable items
Only include relevant tools/repos/articles/workflows; omit low-quality finds.

## Bottom line
One paragraph with the practical takeaway.

## Suggested next action
One concrete low-risk next step the user can approve or ignore.

## Sources
3–6 curated links with one-line context.
```

For calendar/event/morning briefs, use a tighter operational shape instead. For Jim, default to a polished, upbeat "morning card" rather than a dry status report:

```markdown
## 🌅 Good morning, Jim
One warm sentence with today's local date/timezone and a quick tone-setting summary.

## 📅 Today's schedule
Bullets with friendly local times, e.g. `5:30–7:30 PM PDT`. Use tasteful emojis/icons when obvious (`🏋️`, `🍽️`, `✈️`, `⛪`, `💼`) but avoid clutter. Include source/account provenance only when it matters.

## ⚡ Needs attention
Only actionable email/calendar/Drive/tax/travel items. If nothing needs action, use one quiet line at most: `✅ No priority items need action.`

## 👀 Worth knowing
Optional, max 3 genuinely useful low-priority notes. Omit if there is nothing worth saying.

## 🎯 Suggested next step
One concrete low-friction next action. If there is no real action, suggest reviewing the first scheduled event or simply enjoying the day.
```

Negative-result rule for morning/calendar briefs: do **not** include active all-clear / no-info messages for specific categories. Avoid lines like `No CPA alerts`, `No info from CPA`, `No tax items`, `No Drive changes`, or `No nonprofit calendar items`. Mention a source/category only when there is something actionable, noteworthy, or genuinely useful.

Never render user-facing Telegram updates with raw JSON, pipe tables, or raw UTC/ISO timestamps unless the user explicitly requests machine-readable output.

Target length: 600–900 words for normal reports. If the channel is Telegram or the user complains about verbosity, tighten toward a one-screen or 5-minute-read version.

## Cron update workflow

When refining an existing scheduled brief:

1. List cron jobs first; never guess IDs.
2. Update the existing job rather than creating duplicates when the topic is the same.
3. Keep the job report-only unless the user explicitly approves side effects.
4. Use a deterministic precheck script when the brief depends on repeatable data collection. The script should emit compact structured context; keep `no_agent: false` because the LLM is still needed for ranking, judgment, and synthesis.
5. Encode the desired format directly in the cron prompt.
6. Include tool fallback instructions when current research is required.
7. Run once for verification if the user asks to see the result.
8. If the job only queues on the scheduler's next tick, say that clearly; do not claim the output until it actually arrives or is retrieved.

Do not convert synthesis briefs to script-only/no-agent just to save tokens. Use script-only mode for deterministic alert/no-alert jobs; use precheck-plus-LLM mode for executive briefs and watchlists.

## Model watchlists and agent bakeoffs

When a scheduled brief tracks new models or compares Hermes-supported providers (for example OpenAI/Codex vs Claude/Fable), treat it as a **model watchlist plus decision brief**, not a generic news digest.

- First verify the user's current provider/model setup and whether direct provider credentials are available for a live same-prompt bakeoff.
- If a live bakeoff is not possible, label the result as a research/config review and do not fabricate model outputs.
- Track material outcome evidence: repeatable Hermes/agent workflow improvements, production case studies, benchmark repos with prompts/results, and provider metadata.
- Separate hype/demo activity from proven default-model readiness.
- Default recommendation for promising new agentic models is usually **monitor** or **test as specialist** until they win representative local bakeoffs on quality, latency, cost, safety, and user correction burden.
- Keep model-tracking cron jobs report-only unless the user explicitly approves config/provider changes.

For detailed criteria and output shape, see `references/model-watchlist-and-agent-bakeoffs.md`.

## Research execution pattern

For current public ecosystem research:

1. Prefer live web tools if available.
2. If web search is unavailable or weak, use terminal with public APIs or curl/Python against authoritative sources.
3. For GitHub ecosystem scans, use GitHub Search API or repo API to verify:
   - repo URL and description
   - stars/forks as rough adoption signal
   - updated/pushed timestamps
   - license
   - README install method
   - required permissions, hooks, MCP servers, credentials, or external access
4. Treat fresh, low-star repos as candidates to monitor, not proof of quality.
5. Do not install public skills/plugins/marketplaces just to inspect them; inspect README/API metadata first.

## Recommendation rubric

Use the following labels consistently:

- **Adopt** — safe and useful as-is, usually as a read-only source or reporting format.
- **Adapt** — useful pattern, but reimplement with Hermes/user guardrails.
- **Monitor** — promising but too new, broad, or unverified.
- **Reject** — conflicts with the user's risk tolerance, privacy posture, or workflow.

Default posture for public agent/skill/plugin packs:

- Discovery hubs: often **adopt as research sources**, not installed components.
- Workflow/playbook repos: often **adapt selectively**.
- MCP/plugin bundles: usually **monitor** until permission scope is audited.
- Fully autonomous "keep working until done" packs: often **reject or adapt with strict approval gates**.

## Safety and privacy guardrails

Scheduled research jobs must not perform side effects unless specifically approved:

- No installing skills/plugins/MCP servers.
- No editing config, code, memory, or cron jobs from inside the cron run.
- No sending external messages.
- No credential access beyond what is explicitly scoped.
- No destructive commands.
- No raw private snippets or long copied source text in the final report.

When the report is about agent tooling, emphasize permission surface: filesystem, shell, browser, GitHub, email/calendar, databases, Confluence/Notion, MCP servers, and hooks.

## Broad approval handling

If the user says they approve “all next actions” after a report, apply only the concrete low-risk actions that were actually proposed or implied by the report. Still preserve separate gates for installing tools, granting credentials, sending external messages, destructive commands, memory writes, or privacy-sensitive automation.

For broad approval of a scheduled research report's suggested next action:

1. Identify the exact suggested next action from the delivered report.
2. Execute only that scope.
3. If execution reveals a harmless job-quality improvement, update the cron prompt/toolsets and report it.
4. Do not treat broad wording as blanket approval to install repositories, add MCP servers, or enable autonomous workflows.

## Self-research: weekly Hermes setup review

A specialized pattern for recurring research that audits the user's own Hermes
deployment. Unlike external topic monitoring, this job gathers local state
first, then searches the web for improvements against that baseline.

**Precheck script pattern** (`hermes_setup_research_precheck.py`):
- Gathers: QMD status + doctor output, wiki lint summary, cron job count/errors
  (including errored job names + scripts + last run), config hash, change
  signature since last run
- Tracks a composite state signature (file sizes + mtimes of wiki, config,
  memory, QMD config) to detect what changed since last run
- **Proposal tracker**: reads `cron/state/research_proposals_seen.json` and
  passes prior proposals to the agent for dedup — "do NOT re-propose unless
  circumstances have materially changed"
- Emits a context block with 8 research areas for the LLM agent

**The 8 research areas** (pragmatic, value-simplicity):
1. QMD / semantic search (new versions, config, embedding models, community tips)
2. Wiki / knowledge base (Karpathy pattern, Obsidian+agent, link maintenance, archiving)
3. Memory / storage tiers (Mem0/Letta/Zep, consolidation, char limits)
4. Cron / automation (script-first patterns, watchdog improvements)
5. Personal context / privacy (relationship graphs, PII redaction)
6. Email pipeline (Gmail API, email-to-knowledge, episodic memory)
7. Backup / DR (git strategies, disaster recovery)
8. Lifecycle (staleness, archiving, embedding drift, model upgrades)

**Key design principles:**
- The agent should focus on **deltas** — what changed since last week, not
  re-researching everything from scratch. If a tool hasn't released a new version,
  say "no changes" and move on.
- **Pragmatic framing**: "value simplicity. Skip theoretical improvements with
  low ROI." The prompt should explicitly tell the agent to not recommend changes
  that add complexity without clear benefit.
- **Change signature tracking** lets the agent know what's new in the local
  setup since last run, so it can focus research on areas that actually changed.
- **Proposal dedup**: the precheck passes prior proposal titles + dates + disposition
  so the agent doesn't re-propose the same thing. The agent appends new proposals
  to the tracker file after delivering.
- Deliver to the user's primary channel (Slack/origin for Jim).

### Fully Qualified Proposal Format (user preference)

**When research identifies a design change that merits action, present it as a
fully qualified proposal — not a suggestion or summary.** Each proposal must
include ALL of these sections:

1. **Problem** — what current issue/gap this addresses, quantified if possible
2. **Recommendation** — the specific design change, detailed enough to implement
3. **Cost-Benefit Analysis** — effort (hours), risk (low/med/high), benefit
   (quantified: token savings, latency, reliability), ongoing cost, ROI verdict
4. **Test Cases** — defined BEFORE the implementation plan, across three layers:
   - Unit tests (individual functions in isolation)
   - Mock tests (external dependencies mocked)
   - System tests (end-to-end through the real system)
   - Each test: name, what it verifies, given/when/then, expected result
   - Edge cases and regression checks (what must not break)
5. **Implementation Plan** — step-by-step tasks with file paths, dependencies,
   migration steps, rollback plan
   - After each test passes OR fails, evaluate whether the test suite should
     improve (meta-loop on test quality)
6. **Data Migration** (if applicable) — what data moves/transforms, migration
   script outline, validation, old data handling

**When NOT to propose:**
- If research finds nothing actionable → "No actionable changes this week" and stop
- If a finding is interesting but not worth the work → "Monitoring" with a one-line reason
- Do NOT present half-baked ideas or suggestions without implementation detail

This format is non-negotiable for this user — no proposal without tests defined
before the implementation plan, and no proposal without a cost-benefit analysis.

## Verification

Before reporting completion:

- Confirm the cron job ID/name that was updated or run.
- Confirm the schedule and delivery target did not unintentionally change.
- Confirm enabled toolsets match the research need.
- If a one-time run was requested, confirm whether it was queued or completed.
- Summarize only evidence actually observed from tools/API/docs.

## References

- See `references/claude-skills-ecosystem-review.md` for a session-derived pattern for reviewing public Claude/Claude Code skills, marketplaces, MCP bundles, and autonomous workflow packs.
