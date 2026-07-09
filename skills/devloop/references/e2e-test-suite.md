# E2E Test Suite — 8 Small Scenarios + Runner

> Built 2026-07-09. Replaces the old single-scenario smoke test with a structured
> suite of small, independent scenarios, each running one devloop cycle.

## Why this exists

The old E2E approach had two problems:
1. **One big scenario** — the multi-file E2E was the only real-model test, and it was flaky (~50% HUMAN_REVIEW due to judge non-determinism). When it failed, you couldn't tell which part broke.
2. **No structured evaluation** — the test was pass/fail. No control channel analysis, no judge verdict data, no per-scenario metrics.

The suite fixes both: 8 small scenarios covering diverse task types, each independently verifiable, with a runner that captures control channel markers, judge verdicts, and produces a structured report.

## Scenarios

| # | Test | File | Task Type | What it stresses |
|---|---|---|---|---|
| 1 | `test_simple_add` | `test_simple_add.py` | Single function `add(a,b)` | Simplest happy path |
| 2 | `test_string_reverse_words` | `test_string_manip.py` | String manipulation with edge cases | Empty string, single word, multi-word |
| 3 | `test_multi_function_calc` | `test_multi_function.py` | 4 functions in one file | Charter decomposition, multiple criteria |
| 4 | `test_fizzbuzz` | `test_conditional.py` | Conditional logic | Multiple branches, all paths |
| 5 | `test_error_handling` | `test_error_handling.py` | `safe_divide` raising `ValueError` | Exception-raising behavior |
| 6 | `test_class_stack` | `test_class_based.py` | `Stack` class with methods | Stateful objects, not just pure functions |
| 7 | `test_flatten` | `test_data_transform.py` | Recursive list flattening | Nested/recursive logic |
| 8 | `test_multifile` | `test_multifile.py` | Multi-file with cross-import | **Quarantined** (judge non-determinism) |

Each scenario is a standard pytest test that:
- Creates a fresh git repo in a temp directory
- Runs one devloop cycle with real models
- Asserts `COMPLETE` terminal
- Imports and verifies the produced code (not just trusting COMPLETE)
- Cleans up after itself

## Runner

`tests/test_e2e_suite/runner.py` — runs each scenario one at a time as an isolated subprocess.

### Features

- **Isolated subprocesses** — each scenario runs in its own process, no state leakage
- **Control channel parsing** — extracts correlation IDs, begin/end marker pairing, crash markers, enriched details from stderr
- **Judge verdict analysis** — reads `judge_verdicts.jsonl` for split votes and tiebreaker resolution
- **Structured JSON report** — written to `/opt/data/devloop-diagnostics/e2e-suite-report.json`
- **`--repeat N`** — for diagnostic runs (e.g., 20-run sprint)
- **Scenario filtering** — run a single scenario by name

### Usage

```bash
cd /opt/data/skills/software-development/devloop

# Run all non-quarantined scenarios (~20-35 min):
DEVLOOP_RUN_REAL=1 python3 tests/test_e2e_suite/runner.py

# Run a specific scenario:
DEVLOOP_RUN_REAL=1 python3 tests/test_e2e_suite/runner.py test_simple_add

# Run all including quarantined:
DEVLOOP_RUN_REAL=1 DEVLOOP_RUN_MULTIFILE=1 python3 tests/test_e2e_suite/runner.py

# 20-run diagnostic on the quarantined scenario:
DEVLOOP_RUN_REAL=1 DEVLOOP_RUN_MULTIFILE=1 python3 tests/test_e2e_suite/runner.py test_multifile --repeat 20
```

### Report format

```json
{
  "timestamp": 1752000000.0,
  "results": [
    {
      "scenario": "test_simple_add",
      "status": "passed",
      "duration_s": 127.3,
      "exit_code": 0,
      "markers": {
        "total_markers": 23,
        "run_ids": ["a3f1b2c4"],
        "begin_count": 11,
        "end_count": 12,
        "crash_count": 0,
        "terminals": ["✅ complete (0s): 1 criteria, 0 untrusted, 0 suspects, 0 findings"],
        "enriched_details": ["file(s) changed: calc.py", "criteria trusted: 1/1"]
      },
      "judge_verdicts": {
        "total_verdicts": 1,
        "split_votes": 0,
        "tiebreaker_resolved": 0,
        "criteria": ["c1"],
        "details": [{"criterion": "c1", "judge_a": true, "judge_b": true, "split": false}]
      }
    }
  ],
  "summary": {
    "total": 7,
    "passed": 7,
    "failed": 0,
    "skipped": 1,
    "timeout": 0,
    "total_duration_s": 1247.5,
    "total_split_votes": 0
  }
}
```

### What to look for

| Signal | What it means |
|---|---|
| `markers.begin_count != markers.end_count` | Unpaired markers — a phase started but never confirmed completion (or vice versa) |
| `markers.crash_count > 0` | A phase crashed mid-execution |
| `judge_verdicts.split_votes > 0` | Judge non-determinism — judges disagreed on at least one criterion |
| `judge_verdicts.tiebreaker_resolved < split_votes` | Tiebreaker didn't resolve all splits (all three judges disagreed) |
| `status: "failed"` with `HUMAN_REVIEW` in stderr | Devloop couldn't complete — check the terminal reason |
| `status: "timeout"` | Scenario exceeded 10-minute timeout |

## Shared fixtures

`tests/test_e2e_suite/conftest.py` provides:

- `skip_if_not_enabled()` — skips test unless `DEVLOOP_RUN_REAL=1`
- `skip_if_quarantined(name)` — skips test unless `DEVLOOP_RUN_MULTIFILE=1`
- `_e2e_dir(name)` — creates a temp directory under `.devloop/e2e/<name>/`
- `_git_repo(root)` — initializes a git repo in the directory
- `_import_fresh(path, name)` — imports a Python module from a path, bypassing cache
- `_run_devloop(repo, request, root, name)` — runs one devloop cycle via `runner.run_task`
- `_find_produced_file(worktree_path)` — discovers the actual `.py` file the coder produced (see below)

### `_find_produced_file` — discover the coder's output file

**Why this exists:** E2E tests originally hardcoded the expected output filename
(e.g., `os.path.join(worktree["path"], "strings.py")`). But the coder may choose a
different name — `reverse.py` instead of `strings.py`, `calc.py` instead of `safe_div.py`.
The devloop pipeline completes successfully (judge trusted, evidence passed, regression
green, merge committed), but the test fails at the independent corroboration step because
it can't find the file at the hardcoded path. This is a **test harness bug**, not a
devloop defect.

**How it works:**

1. Try `.devloop/result.json` → `changed_files` — the canonical record of what the
   coder produced. Returns the first `.py` file found.
2. Fallback: scan the worktree for non-test `.py` files (excludes `test_*.py`,
   `conftest.py`, `__init__.py`). Returns the first match.
3. If nothing found, raises `FileNotFoundError`.

**Usage in tests:**

```python
from tests.test_e2e_suite.conftest import _find_produced_file

# Before (brittle — hardcoded filename):
mod = _import_fresh(os.path.join(out["worktree"]["path"], "strings.py"), "str_e2e")

# After (robust — discovers the actual file):
produced = _find_produced_file(out["worktree"]["path"])
mod = _import_fresh(produced, "str_e2e")
```

**Pitfall:** Never hardcode the expected output filename in an E2E test. The coder
chooses the filename, and the test should discover it. The only contract the test
should enforce is that the produced module has the expected functions/classes/behavior
— not that it has a specific filename.

**Proven on:** 2026-07-09 — 2 of 7 E2E scenarios failed (test_string_reverse_words,
test_error_handling) because the coder chose different filenames than the tests
expected. Both fixed by switching to `_find_produced_file`. All 7 test files updated
for consistency; unused `import os` removed from all 7.

## Relationship to old E2E tests

The old `test_e2e_real.py` (single smoke test + quarantined multi-file test) still exists but is superseded by the suite. The suite:
- Covers more task types (8 vs 2)
- Has structured evaluation (control channel + judge verdicts)
- Has a dedicated runner with reporting
- Is easier to extend (add a new file in `test_e2e_suite/`)

The old tests remain for backward compatibility but new scenarios should be added to the suite.

## Known runner limitations (2026-07-09)

The runner's analysis is heuristic — it parses stderr markers and a time-windowed
slice of `judge_verdicts.jsonl`. These limitations are known and documented so future
sessions don't waste time debugging them as if they were devloop defects:

### 1. Judge verdict parser misses redesign cycles

`parse_recent_judge_verdicts` reads verdicts from the **last N seconds** of the run
(by default, the trailing diagnostic window). When a criterion gets a split vote,
triggers a redesign, and is re-judged successfully, the **final trusted verdict** may
fall outside the time window. The parser reports the earlier split vote, making it look
like the scenario passed despite an unresolved split — when in reality the redesign
cycle resolved it.

**Symptom:** `judge_verdicts.split_votes > 0` but `status: "passed"` and the
`enriched_details` show all criteria trusted.

**Fix (not yet applied):** Read the full `judge_verdicts.jsonl` for the run (not just
the trailing window), group by criterion, and report the **final** verdict per criterion.

### 2. Begin/end pairing over-counts with rebuilds

The `begin_count` and `end_count` fields count all `⏳` and `✅/❌` markers. But
rebuilds emit end markers (`❌ rebuild`) without a matching begin, and `summary` emits
an end marker without a begin. This means `begin_count` and `end_count` will never be
equal for runs with rebuilds — and that's correct behavior, not a bug.

**Symptom:** `begin_count=12, end_count=15` on a run with 1 rebuild. The 3 extra end
markers are: `❌ rebuild`, `✅ complete`, `✅ summary`.

**Fix (not yet applied):** Pair markers by phase name, not by count. A phase with a
begin but no matching end is a real bug; a phase with an end but no begin is expected
for rebuild/summary/terminal events.

### 3. Stale report overwrite

The runner writes `e2e-suite-report.json` on every run. If an earlier exploratory run
(e.g., `pytest tests/test_e2e_suite/test_json_config.py`) writes a report, and then
the full suite runs, the full suite's report overwrites it. But if a **partial** run
writes a report AFTER the full suite, the full suite's results are lost.

**Symptom:** The report shows only 1 scenario (`test_json_config`) when you expected 8.

**Prevention:** Always run the full suite through `runner.py`, not through `pytest`
directly. The runner is the canonical entry point. If you need to run a single scenario,
use `runner.py test_<name>`, not `pytest tests/test_e2e_suite/test_<name>.py`.

### 4. `test_json_config.py` is not in SCENARIOS

The file `tests/test_e2e_suite/test_json_config.py` exists but is NOT listed in
`runner.py`'s `SCENARIOS` dict. It was an exploratory scenario that failed (both judges
distrusted the vague "config.json exists" criterion — see devloop-usage-patterns
pitfall #9). It should either be added to SCENARIOS with a concrete task description
or removed to avoid confusion.

## Adding a new scenario

1. Create `tests/test_e2e_suite/test_<name>.py`
2. Import fixtures from `.conftest`
3. Write a single `test_<name>()` function that:
   - Calls `skip_if_not_enabled()`
   - Creates a repo with `_e2e_dir` + `_git_repo`
   - Runs devloop with `_run_devloop`
   - Asserts `COMPLETE`
   - Uses `_find_produced_file()` to discover the coder's output file (never hardcode the filename)
   - Imports and verifies the produced code's behavior (functions, classes, edge cases)
4. Add the scenario to `SCENARIOS` in `runner.py`
5. Run the suite to verify
