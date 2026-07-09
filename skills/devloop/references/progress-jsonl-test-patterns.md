# Progress.jsonl — Design & Test Patterns

> Captured 2026-07-07 after the sync cron rewrote the progress mechanism and
> 5 new integrity tests were added.

## Design: open-append-close-per-event

The original design (2026-07-06) used a file-handle-based approach:
`_progress_open()` opened a handle, `_progress_close()` closed it, and
`_PROGRESS_FILE` held the handle. This required `_progress_close()` to be
called on every terminal path (COMPLETE, HUMAN_REVIEW, NO_TERMINATION,
dispatch_error) — a leak-prone pattern.

The sync cron (2026-07-07) rewrote this to `_progress_event()` which opens,
appends, and closes the file on every event:

```python
def _progress_event(run_dir, step, **data):
    ts = round(time.time(), 3)
    record = {"ts": ts, "step": step, **data}
    if run_dir:
        try:
            p = Path(str(run_dir)) / "progress.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass
    return record
```

**Why this is better:**
- No file handle to leak — each event is self-contained
- No `_progress_close()` needed — no cleanup to forget
- Inherently crash-safe — a crash mid-run leaves a valid, closed file
- No stale `_PROGRESS_RUN_DIR` state to leak between runs

## Test patterns for progress.jsonl integrity

5 tests added 2026-07-07 (`test_progress.py` Stages 5+6):

### Stage 5: Terminal path integrity

| Test | What it verifies |
|---|---|
| `test_progress_jsonl_dispatch_error_has_terminal` | progress.jsonl exists and has terminal/dispatch_error event when coder crashes |
| `test_progress_jsonl_no_termination_has_terminal` | progress.jsonl exists and has terminal event on NO_TERMINATION bug sentinel |
| `test_progress_jsonl_all_events_valid_json` | Every line in progress.jsonl parses as valid JSON — no corruption from crash paths |

### Stage 6: Sequential run independence

| Test | What it verifies |
|---|---|
| `test_progress_jsonl_sequential_runs_are_independent` | Two sequential runs produce separate progress.jsonl files with no cross-contamination |
| `test_progress_jsonl_does_not_leak_across_runs` | Stale `_PROGRESS_RUN_DIR` is overwritten by `run_v1` — no leak to wrong directory |

### Test harness pattern

All tests use the same pattern:
1. Create a `tempfile.TemporaryDirectory()`
2. Reset `loop._PROGRESS_START = None` and `loop._PROGRESS_RUN_DIR = None`
3. Call `loop.run_v1()` with deterministic mock functions (no LLM)
4. Assert on the returned `res["terminal"]`
5. Read `progress.jsonl` from the run directory
6. Assert on event count, step names, JSON validity, or cross-run independence

The `_progress_events()` helper reads and parses progress.jsonl:
```python
def _progress_events(run_dir):
    p = os.path.join(run_dir, "progress.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]
```

## Key insight: no `_progress_close()` to test

The original task was "add tests that verify `_progress_close()` fires on all
terminal paths." But the sync cron's rewrite eliminated `_progress_close()`
entirely — the open-append-close-per-event design makes it unnecessary. The
tests instead verify the *outcome*: progress.jsonl exists, has valid events,
and has a terminal event on every exit path. This is a better test target
because it tests the observable behavior, not the implementation detail.

## Digest alignment pitfall (2026-07-07)

`devloop_digest.py` was written against an imagined schema (`kind=tool_ok` style
records) rather than the actual `_progress_event()` output format. This caused
every field to be empty/null on all runs: `n_criteria=0`, `judge_verdicts=None`,
`evidence_results=[]`, `duration_s=None`.

**Root cause:** The digest was developed in parallel with the progress mechanism
(Phase 2+3 of the improvement roadmap) and the two were never tested together
against real trace data. The digest's `_parse_progress()` looked for
`step == "complete"` to detect terminal state, but the actual format uses
`step == "terminal"` with a `terminal` field.

**Fix (2026-07-07):** Rewrote `_parse_progress()` to match the actual schema:

| Field | Old (wrong) | New (correct) |
|---|---|---|
| `n_criteria` | Looked for `step == "charter"` with `n_criteria` | Reads from `step == "charter_result"` |
| `judge_verdicts` | Not parsed at all | Reads `verdicts` array from `step == "judge"` |
| `evidence_results` | Not parsed at all | Reads `passed`/`total`/`red`/`per_criterion` from `step == "evidence"` |
| `duration_s` | Not computed | Computed from first→last `ts` delta |
| `terminal` | Looked for `step == "complete"` | Reads `step == "terminal"` with `terminal` field |
| `rebuilds` | Not parsed | Counts `step == "rebuild_fail"` events |

**Prevention:** Any consumer of `progress.jsonl` must be tested against real
trace data before deployment. The 20-test suite in `tests/test_devloop_digest.py`
now validates parsing against all known record shapes (COMPLETE, HUMAN_REVIEW,
INTERRUPTED, rebuilds, old format, corrupt JSON, empty file).
