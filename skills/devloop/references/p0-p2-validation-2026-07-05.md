# P0-P2 Fix Validation — 2026-07-05

After applying the three render.py fixes (P0: broken DI branches, P1: _lit() datetime,
P2: ANSWERS plumbing + DI guidance), devloop was re-run on the same calendar-quick-add
request that previously failed 5/5 rounds.

## Results: 3/4 criteria now pass judges (was 0/4)

| Criterion | Description | Judges | Status |
|-----------|-------------|--------|--------|
| c1 | parse_event with datetime | 2/2 ✅ | PASSED — _lit() datetime fix works |
| c2 | resolve_location 3-layer fallback | 2/2 ✅ | PASSED |
| c3 | create_event with DI (gws_runner) | 2/2 ✅ | PASSED — DI guidance works |
| c4 | main CLI orchestration | 0/2 ❌ | REJECTED — new failure mode |

## What This Proves

1. ✅ P0 (broken DI branches removed) — no more invalid Python from render.py
2. ✅ P1 (_lit() datetime fix) — c1's test with `datetime(2026,7,6,12,0)` accepted by both judges
3. ✅ P2 (ANSWERS plumbing + DI guidance) — c3's test with `gws_runner` injection accepted; designer now uses DI correctly
4. ❌ c4 (CLI main()) remains — judges reject CLI integration tests even with correct DI

## c4 verify_intent (what the designer produced)

```
calls=[]; main(['lunch tomorrow 12pm at Pizzaiolo','--calendar','work','--duration','90',
'--attendees','a@b.com','--no-reminder'], now=datetime(2026,7,5,10,0),
geocode_fn=lambda x: 'GEO:'+x, gws_runner=lambda **kw: calls.append(kw));
len(calls)==1 and calls[0]['calendar']=='work' and calls[0]['start']=='2026-07-06T12:00:00'
and calls[0]['end']=='2026-07-06T13:30:00' and calls[0]['attendees']==['a@b.com']
and 'reminder_minutes' not in calls[0]
```

The designer IS using DI correctly — the prompt guidance is working. But judges still
reject c4. The test is too complex (too many assertions in one test, inspecting dict
keys from a spy list) and judges are calibrated for unit-level behavioral verification,
not end-to-end pipeline tests.

## Trace

Run: `build-92198-1783255411578801870`
Trace: `/opt/data/devloop-traces/build-92198-1783255411578801870/trace.jsonl`
Design spec: `/opt/data/devloop-traces/build-92198-1783255411578801870/design_spec.json`
Judge verdicts: `/opt/data/devloop-traces/build-92198-1783255411578801870/judge_verdicts.json`

## Next Steps

The c4 failure is the exact use case for the proposed pre-judge static analysis gate.
See `devloop-usage-patterns` skill, failure mode #5 for workarounds.
