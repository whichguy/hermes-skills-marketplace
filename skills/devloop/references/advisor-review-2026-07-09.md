# Advisor Review — 2026-07-09

3-seat panel (DeepSeek V4 Pro, Kimi K2.7 Code, GLM 5.2) reviewed devloop across 3 areas:
linter reference + coverage, control channel output, and E2E test suite. 158s total.

## Key Findings

### P0: `loop.py:757` lint_discovery count bug (all 3 advisors converged)

`lint.discover()` returns a `list` of dicts, but `loop.py:757` calls
`.get("linters", {})` as if it were a dict. Result: the `lint_discovery` progress
marker always reports "0 linter(s) available" regardless of actual linters.

**Fix:** `sum(len(r["available"]) for r in _discovery if r.get("covered"))`

### P0: `.cpp/.hpp` not wired despite g++ installed

`g++` is on PATH but `_LANGUAGES` only covers `.c`/`.h`. One-line change to add
`_gpp_syntax` builder and `(".cpp", ".hpp")` row.

### P0: `pyflakes` installed but not wired

`/opt/data/.venv/bin/pyflakes` exists but not in the `.py` linter chain. Zero-cost
addition that catches F821-style undefined names beyond ruff's narrow scope.

### P1: Judge distrust reasons not in stderr

Per-judge vote breakdown and reason text only appear in `progress.jsonl`, not in
the human-visible `judge` ❌ marker. All 3 advisors flagged this.

### P1: Coder summary missing from implement marker

The `implement` completion marker lists filenames but not the coder's strategy
summary. The `summary` field from the implementer result is captured in trace.jsonl
but never surfaced to stderr.

### P1: No non-Python E2E scenario

All 8 E2E scenarios produce only `.py` files. A JSON config scenario would
exercise `json.tool` end-to-end — the cheapest high-value addition.

### P1: `test_multifile` quarantine should be data-collecting

Currently skips entirely. Should run and report `accepted_flaky` when failure
reason is judge split/tiebreaker, rather than losing all signal.

### P1: `test_class_stack` judge crash needs investigation

`crash_count=1`, `0/4 criteria trusted` on first attempt, recovered on retry.
May reveal a dispatcher resilience bug in `dod_oracle.judge_assertions`.

### P2: End-of-run summary/rollup marker

The `complete` marker should include a structured summary line: branch name,
produced files, judge verdict count, lint skip/research flags, rebuilds, replans.

### P2: ETA annotations inconsistent

Only some ⏳ markers include `~<eta>`. Should suppress for <30s phases, show for
long phases.

### P2: Crash markers only cover implement + run_task

`design`, `judge`, `evidence`, and `overfit_audit` have no crash wrappers — a
crash in those phases leaves the last marker as ⏳.

## Advisor Convergence

All 3 advisors independently converged on:
- `loop.py:757` count bug (P0)
- Wire `.cpp/.hpp` (P0)
- Add non-Python E2E scenario (P1)
- Judge distrust reasons in stderr (P1)
- Coder summary in implement marker (P1)
- Investigate test_class_stack judge crash (P0)
- Re-evaluate multifile quarantine (P1)

## Unique Insights

- **DeepSeek**: Reference doc availability columns stale (PyYAML, sqlparse, pyflakes).
  Crash markers only cover 2 of 6 long phases.
- **Kimi**: `lint_discovery` probes frozen tests, not coder output — if coder
  produces `.cpp`, the gap is invisible. Linter reference sync test already exists.
  Quarantine should be data-collecting.
- **GLM**: `test_trace_view.py:26` has stale stub data (dict vs list shape).
  ETA annotations should be suppressed for <30s phases.

## Full Reviews

- `/opt/data/devloop-diagnostics/advisors/review-deepseek.md` (136s, 14.4K chars)
- `/opt/data/devloop-diagnostics/advisors/review-kimi.md` (158s, 15.7K chars)
- `/opt/data/devloop-diagnostics/advisors/review-glm.md` (150s, 14.2K chars)
