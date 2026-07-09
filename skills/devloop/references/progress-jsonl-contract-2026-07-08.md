# progress.jsonl Contract (2026-07-08)

> Architecture Decision Record for the `progress.jsonl` record schema.
> Producers (`loop.py`, `runner.py`) and consumers (`devloop_digest.py`, messaging hooks)
> MUST conform to this contract. Verified by `tests/test_devloop_digest.py`.

## Record shape

Every line in `progress.jsonl` is a JSON object with at minimum:

```json
{"ts": <float_epoch>, "step": <string>, ...event_fields}
```

- `ts` — Unix epoch timestamp (seconds, float, from `time.time()`). Always present.
- `step` — Phase name (string). Always present. See the step catalog below.
- `...event_fields` — Step-specific fields. See per-step schema below.

## Step catalog

| Step | Emitted by | Fields | Notes |
|------|-----------|--------|-------|
| `charter_result` | `runner.py:125` | `n_criteria`, `n_assumptions`, `n_blocking`, `tiers` | Summary of charter decomposition |
| `roadmap` | `loop.py` (`_progress_roadmap`) | `phases` (list[str]) | Phase sequence preview |
| `charter` | `loop.py` (`_progress`) | `ok`, `detail` | Announcement only |
| `ambiguity_gate` | `loop.py` (`_progress`) | `ok`, `detail` | Gate result |
| `design` | `loop.py` (`_progress`) | `ok`, `detail`, `n_criteria` | Test design start |
| `coverage` | `loop.py` (`_progress`) | `ok`, `detail`, `n_tests`, `n_criteria`, `uncovered` | Coverage gate result |
| `quality_lint` | `loop.py` (`_progress`) | `ok`, `detail` | Static analysis gate |
| `judge` | `loop.py` (`_progress`) | `ok`, `trusted`, `total`, `verdicts` | Judge gate. `verdicts` is a list of per-criterion dicts (see below) |
| `implement` | `loop.py` (`_progress`) | `ok`, `detail` | Coder dispatch start |
| `evidence` | `loop.py` (`_progress`) | `ok`, `attempt`, `passed`, `total`, `red`, `per_criterion` | Evidence gate. `red` is a list[str] of failing criterion IDs. `per_criterion` is a dict[str, bool] |
| `stop_check` | `loop.py` (`_progress`) | `ok`, `detail` | Stop condition evaluation |
| `regression` | `loop.py` (`_progress`) | `ok`, `detail` | Whole-suite regression gate |
| `overfit_audit` | `loop.py` (`_progress`) | `ok`, `detail` | Overfit detection audit |
| `complete` | `loop.py` (`_progress`) | `ok`, `detail` | Announcement before terminal |
| `terminal` | `loop.py` (`_progress_event`) | `terminal`, `reason`, ... | Terminal event. `terminal` is one of: `COMPLETE`, `HUMAN_REVIEW`, `NO_TERMINATION` |
| `rebuild_fail` | `loop.py` (`_emit`) | `rebuild`, `cause` | Rebuild failure during loop |
| `test_redesign` | `loop.py` (`_emit`) | `criteria`, `cause` | Oracle regeneration triggered |
| `test_repair` | `loop.py` (`_emit`) | (varies) | Mid-run test repair |
| `commit_scope` | `loop.py` (`_emit`) | (varies) | Commit scope audit |

## Per-criterion verdict shape (inside `judge` step's `verdicts` array)

```json
{
  "criterion": "c1",
  "encodes": true,
  "judge_a": true,
  "judge_b": true,
  "judge_a_reason": "",
  "judge_b_reason": ""
}
```

- `criterion` — criterion ID (string, matches charter `dod[].id`)
- `encodes` — whether the test encodes the criterion (bool)
- `judge_a` / `judge_b` — judge votes (bool, true = trusted)
- `judge_a_reason` / `judge_b_reason` — one-sentence reason (string, may be empty)

## Terminal values

| `terminal` | Meaning | Exit code |
|-----------|---------|-----------|
| `COMPLETE` | All gates passed, work merged | 0 |
| `HUMAN_REVIEW` | Blocking questions / gate routing / back-off exhausted | 2 |
| `NO_TERMINATION` | Max passes exhausted (bug sentinel) | 1 |

## Consumer obligations

Consumers (`devloop_digest.py`, messaging hooks, future tools) MUST:
1. Parse each line as an independent JSON object (JSONL format).
2. Skip lines that don't parse (corrupt JSON) with a warning to stderr.
3. Handle missing fields gracefully — use `.get()` with defaults.
4. Determine terminal from the `step == "terminal"` event's `terminal` field, NOT from `step == "complete"` (which is just an announcement).
5. Extract `n_criteria` from `step == "charter_result"` (emitted by `runner.py`), with fallback to `step == "coverage"` which also carries `n_criteria`.

## Producer obligations

Producers (`loop.py`, `runner.py`) MUST:
1. Write one JSON object per line, newline-terminated.
2. Always include `ts` (float epoch) and `step` (string).
3. Never change the step names listed above without updating this contract and bumping a version field.
4. Write `progress.jsonl` regardless of `DEVLOOP_PROGRESS` env var — the machine channel is independent of the stderr level.

## Versioning

This is contract version 1. If the schema changes (new steps, renamed fields, removed fields), bump the version and add a `schema_version` field to each record. Consumers must check the version and warn on mismatch.

## Verification

`tests/test_devloop_digest.py` contains 20 tests that validate the consumer against this contract, including:
- Complete run parsing (all steps)
- HUMAN_REVIEW terminal with reason
- Interrupted run (no terminal event)
- Rebuild loop with multiple evidence attempts
- Old format fallback (pre-charter_result)
- Corrupt/empty/missing file handling
- Time window filtering
- Silent-on-empty behavior