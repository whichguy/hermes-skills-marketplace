# Cron Model Selection: Haiku vs Sonnet

## Decision rule

For any LLM-backed cron job, apply this test before defaulting to Sonnet:

> **Is the LLM a pure formatter receiving structured precheck output?**
> If yes → Haiku. If it synthesizes, drafts, ranks, or exercises judgment → Sonnet.

## Haiku: safe when ALL of these apply
- A precheck script already gathered, filtered, and structured all data
- LLM role is templated rendering (fill-in-the-blank + house style) with no ranking or tradeoffs
- Output quality is bounded by the structure of the input, not the model's judgment
- No email drafting, research synthesis, or privacy-sensitive graph inference

## Sonnet: required when ANY of these apply
- Multi-source synthesis (calendar + email + weather + priorities → morning brief)
- Email draft replies — prose quality and tone judgment are load-bearing
- Research/watchlist briefs — model must evaluate and recommend
- Weekly planning digests — forward-looking priorities need reasoning
- Privacy-sensitive relationship/context graph inference — nuance required
- Flagship daily output users compare against human quality

## Applied audit (Jim's crons, Jun 2026)

| Job | Model | Rationale |
|---|---|---|
| morning-brief | Sonnet | Multi-source flagship digest |
| calendar-travel-alerts | n/a | `no_agent` — script only |
| Daily Hermes watchlist | Sonnet | Research synthesis + security analysis |
| Weekly efficiency check | n/a | `no_agent` — script only |
| Daily auto-update guard | n/a | `no_agent` — script only |
| Email access monitor | n/a | `no_agent` — script only |
| Weekly system tidy-up | n/a | `no_agent` — script only |
| Daily World Cup standings | n/a | `no_agent` — script only |
| **inbox-triage-heartbeat** | **Haiku** ✅ | Already Haiku — email triage + draft prep |
| followup-sweep | Sonnet | Email draft quality matters |
| weekly-review | Sonnet | Planning synthesis |
| **eod-wrap** | **Haiku** ✅ | Precheck does all work; LLM formats 5–8 bullets |
| **Upcoming meetings** | **Haiku** ✅ | Precheck → JSON → short templated note (high freq: every 25m) |
| personal-context-review | Sonnet | Privacy-sensitive relationship inference |
| AI service monitor | n/a | `no_agent` — script only |
| NCW meet alerts | n/a | `no_agent` — script only |
| Weekly wiki ingest | Sonnet | Wiki prose quality compounds; low freq → small saving |
| Daily GitHub backup | n/a | `no_agent` — script only |
| USAW TO Duty Reminders | n/a | `no_agent` — script only |
| **USAW TO Schedule Change Watch** | **Haiku** ✅ | Pure JSON formatter, fixed template |

## Cost impact
The highest-leverage switches are **high-frequency formatter jobs**:
- `Upcoming meetings` runs every 25 min (~58×/day) — Haiku saves ~20× per-token cost on every fire
- `inbox-triage-heartbeat` runs every 30 min — already Haiku, confirms the pattern works

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
