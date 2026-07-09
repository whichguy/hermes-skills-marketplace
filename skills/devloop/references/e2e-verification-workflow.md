# E2E verification workflow for devloop changes

When you've made changes to devloop itself (new linters, progress markers, pipeline logic),
run the full e2e pipeline to verify the changes work with real models. Run all three tracks
in **parallel** — they're independent and the total wall-clock is the slowest track, not the sum.

## The three-track parallel e2e

```bash
# Track 1: Devloop smoke test (real v1 loop, ~1-2 min)
cd /opt/data/skills/software-development/devloop
DEVLOOP_RUN_REAL=1 uv run --with pytest python3 -m pytest tests/test_e2e_real.py \
  -k "test_e2e_real_v1_simple_task_completes" -v -s 2>&1

# Track 2a: NBQ e2e (fast ranking with families, ~45-60s)
cd /opt/data
python3 /opt/data/skills/autonomous-ai-agents/next-best-questions/scripts/infogain.py \
  "Build a Python utility that converts CSV files to JSON" --mode focus --json 2>&1

# Track 2b: Investigator e2e (quick mode with triage + parallel rounds, ~3-5 min)
cd /opt/data
python3 /opt/data/skills/autonomous-ai-agents/investigator/scripts/iterate.py \
  --problem "Add a health check endpoint to a Flask API app" \
  --mode quick --output prompt 2>&1
```

## What to verify in each track

| Track | Verify |
|---|---|
| Devloop smoke | All progress markers appear (charter → design → judge → implement → lint → evidence → stop_check → regression → overfit_audit → commit_scope → complete → merge). Ruff + mypy both run (lint count ≥ 2). Exit 0. |
| NBQ | Families mode active (lens tags: scope, contrarian, premortem). `derivable_prob` field present. EVSI scoring computed. `min_met: true`. |
| Investigator | Triage routes questions (derived/findable/judgment). Parallel rounds dispatch. Tombstones track answered + not_found. Refined prompt generated. |

## Known non-fatal warnings

### Investigator: `triage_batch returned list, expected dict`

The triage classifier's JSON output format doesn't always match the expected schema (returns a
list instead of a dict). The code handles it gracefully with a fallback that treats every question
as FINDABLE. This is a P2 fix — the investigation still completes correctly, just with all questions
routed to research instead of the triage paths. First observed 2026-07-08 on a quick-mode run with
`--triage on`.

## Proven results

2026-07-08 — all three tracks passed after the linter expansion + progress marker changes
(485→496 tests):
- Devloop smoke: 2m 45s, PASSED
- NBQ: 55s, 4 questions survived, `min_met: true`
- Investigator: 4m 26s, 4 tombstones (1 answered, 3 not_found), refined prompt generated
