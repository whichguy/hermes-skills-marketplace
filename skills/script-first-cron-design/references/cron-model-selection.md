# Cron Model Selection: Local Fast → Haiku → Sonnet

## Three-tier decision rule

For any LLM-backed cron job, apply this test before defaulting to Sonnet:

> **Is the LLM a pure formatter receiving structured precheck output?**
> If yes → **local fast model** (gemma4:12b-mlx-bf16, free, ~2-5s).
> If it needs some judgment but not deep reasoning → Haiku (cheap cloud).
> If it synthesizes, drafts, ranks, or exercises judgment → Sonnet/GLM (full cloud).

## Local fast model (gemma4:12b-mlx-bf16): safe when ALL of these apply
- A precheck script already gathered, filtered, and structured all data
- LLM role is templated rendering (fill-in-the-blank + house style) with no ranking or tradeoffs
- Output quality is bounded by the structure of the input, not the model's judgment
- No email drafting, research synthesis, or privacy-sensitive graph inference
- **Free** (local Ollama, no API cost), **fast** (~2-5s vs 10-30s for cloud)
- Also add the `ask` skill so the job can delegate sub-tasks to other models if needed

## Haiku: when local fast isn't enough but Sonnet is overkill
- Precheck did most work, but some light judgment needed (prioritization, dedup)
- Output benefits from slightly better prose than local models produce
- High-frequency job where local model quality is borderline
- ~20× cheaper than Sonnet per token

## Sonnet/GLM: required when ANY of these apply
- Multi-source synthesis (calendar + email + weather + priorities → morning brief)
- Email draft replies — prose quality and tone judgment are load-bearing
- Research/watchlist briefs — model must evaluate and recommend
- Weekly planning digests — forward-looking priorities need reasoning
- Privacy-sensitive relationship/context graph inference — nuance required
- Flagship daily output users compare against human quality

## Local fast model: when to keep cloud despite formatting-only role
- **GLM language quirk**: GLM models default to Chinese. If the job's prompt already has the "CRITICAL: ALL output MUST be in English" guard and the job is working, switching to a local model is safe. But if the job was recently debugged (e.g. eod-forecast), keep it on GLM until the new prompt stabilizes — don't change model AND prompt simultaneously.
- **High-stakes formatting**: inbox-triage-heartbeat and followup-sweep draft email replies — even though they're "formatting," the prose quality directly affects the user. Keep on cloud.
- **Research/watchlist**: Hermes watchlist brief and setup research require web search + synthesis — local models lack the reasoning depth.

## Applied audit (Jim's crons, Jun 2026 — updated Jun 28)

| Job | Model | Rationale |
|---|---|---|
| morning-brief | **gemma4:12b** | Precheck does all work; LLM formats |
| calendar-travel-alerts | n/a | `no_agent` — script only |
| Daily Hermes watchlist | **glm-5.2** | Research synthesis + security analysis |
| Weekly efficiency check | n/a | `no_agent` — script only |
| Daily auto-update guard | n/a | `no_agent` — script only |
| Email access monitor | n/a | `no_agent` — script only |
| Weekly system tidy-up | n/a | `no_agent` — script only |
| Daily World Cup standings | n/a | `no_agent` — script only |
| **inbox-triage-heartbeat** | **glm-5.2** | Email draft quality matters — keep cloud |
| followup-sweep | **glm-5.2** | Email draft quality matters — keep cloud |
| weekly-review | **gemma4:12b** | Precheck does all work; LLM formats |
| **eod-forecast** | **glm-5.2** | Recently debugged; keep stable model |
| **Upcoming meetings** | **gemma4:12b** | Precheck → JSON → short templated note (high freq: every 25m) |
| personal-context-review | **gemma4:12b** | Precheck does all work; LLM formats |
| AI service monitor | n/a | `no_agent` — script only |
| NCW meet alerts | n/a | `no_agent` — script only (paused) |
| Hourly wiki ingest | **gemma4:12b** | Precheck does all work; LLM formats |
| Daily GitHub backup | n/a | `no_agent` — script only |
| USAW TO Duty Reminders | n/a | `no_agent` — script only (paused) |
| USAW TO Schedule Change Watch | n/a | `no_agent` — script only (paused) |
| Self-healing cron watchdog | **gemma4:12b** | Precheck does all work; LLM formats |
| Node.js dep watchdog | **gemma4:12b** | Precheck does all work; LLM formats |
| Python dep watchdog | **gemma4:12b** | Precheck does all work; LLM formats |
| Buttons watcher | **gemma4:12b** | Precheck does all work; LLM formats |
| email-wiki-ingest | **gemma4:12b** | Precheck does all work; LLM formats |
| Session-to-wiki | **gemma4:12b** | Precheck does all work; LLM formats |
| Open Threads | **gemma4:12b** | Precheck does all work; LLM formats |
| Hermes setup research | **glm-5.2** | Web research + synthesis |

## Cost impact (Jun 28 update)
**12 jobs moved from cloud to local** (gemma4:12b-mlx-bf16, free). 5 kept on GLM cloud for reasoning quality. ~70% reduction in cloud API usage for cron work. All 17 LLM-driven jobs now have the `ask` skill attached for model delegation.

The highest-leverage switches are **high-frequency formatter jobs**:
- `Upcoming meetings` runs every 25 min (~58×/day) — now free local
- `inbox-triage-heartbeat` runs every 30 min — kept on cloud (email draft quality)
- `Hourly wiki ingest` runs hourly — now free local

## How to flip a job's `no_agent` flag
The `cronjob action=update` API does NOT expose a `no_agent` toggle.
Edit `/opt/data/cron/jobs.json` directly (key is `"id"`, not `"job_id"`):

```python
import json
path = '/opt/data/cron/jobs.json'
data = json.loads(open(path).read())
job = next(j for j in data['jobs'] if j['id'] == '<job_id>')
job['no_agent'] = False   # or True
open(path,'w').write(json.dumps(data, indent=2))
```

Then update the prompt via `cronjob action=update prompt="..."`.
Verify with `cronjob action=list` that `no_agent` is absent/False in the output.
