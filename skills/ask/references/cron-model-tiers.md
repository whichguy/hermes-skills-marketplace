# Cron Model Assignment Tiers

Established Jun 2026 after a DeepSeek-reviewed audit of 17 LLM-driven cron jobs.

## Tier System

| Tier | Model | Alias | Speed | Cost | Use When |
|---|---|---|---|---|---|
| 🟢 Fast local | `qwen3.6:35b-a3b` | `fast`, `local` | 114 tok/s, ~4s | Free | Simple formatting, classification, triage, watchdog evaluation, meeting summaries |
| 🔵 Cloud workhorse | `glm-5.2:cloud` | `glm` | ~10-30s | Cheap | User-facing daily synthesis, briefings, research digests, anything the user reads |
| 🟡 Premium reasoning | `deepseek-v4-pro:cloud` | `deepseek` | ~20-60s | Mid-tier | Weekly deep analysis, complex multi-source synthesis, decisions with high cost of error |

## Decision Framework

**Start with fast/local.** Only escalate when the job:
- Produces user-facing content the user reads daily (→ GLM)
- Requires deep reasoning across multiple sources (→ DeepSeek)
- Has a high cost of error if the model gets it wrong (→ DeepSeek)

**Never use DeepSeek for:** simple formatting, classification, triage, watchdog evaluation, meeting summaries, or anything that runs more than daily.

**Never use fast/local for:** complex multi-source research synthesis, decisions where a wrong answer costs real money/time, or content the user reads as their primary daily briefing.

## GLM Language Warning

`glm-5.2:cloud` defaults to Chinese output. ALL cron job prompts using GLM MUST include:
```
respond in English only
```
in the prompt. Without this, GLM cron jobs produce Chinese responses.

## DeepSeek Review Pattern

When making model assignment decisions across multiple cron jobs (batch reassignment), follow this workflow:

1. Gather full context on each job (prompt, schedule, precheck script, current model)
2. Send the full context to DeepSeek with: "Review these cron jobs and recommend model assignments. For each job, explain WHY the model fits the task."
3. Apply DeepSeek's recommendations — it catches nuances the fast model misses
4. Verify with a spot-check on the most critical job

**Pitfall:** The fast model (qwen3.6) makes reasonable-but-wrong assignments on batch decisions. It correctly identifies simple vs complex but misses domain-specific nuances (e.g., GLM defaults to Chinese, user-facing briefings need quality, watchdogs that run every 30m should use the cheapest model that can do the job). Always use DeepSeek for the review pass.

## Session Reference (Jun 2026)

Final assignments after DeepSeek review:

**Fast/Local (6 jobs):** inbox-triage-heartbeat, upcoming-meetings, node-dep-watchdog, python-dep-watchdog, buttons-watcher, open-threads

**GLM (9 jobs):** morning-brief, eod-wrap, ncw-briefing, session-wiki-capture, calendar-digest, email-digest, news-digest, weekly-review, market-brief

**DeepSeek (2 jobs):** deep-research-brief, weekly-deep-analysis
