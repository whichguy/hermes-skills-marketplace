# End-of-Run Summary Marker (2026-07-09)

The `_run_summary` helper in `loop.py` builds a structured one-line summary from the
charter's criteria, the `test_to_criterion` mapping, and the terminal state. It's emitted
as the final `✅ complete` or `❌ HUMAN_REVIEW` marker so the user can understand the
outcome from the control channel alone — no need to read the grounding block.

## Format

```
✅ complete (0s): 1 criteria, 0 untrusted, 0 suspects, 0 findings
❌ HUMAN_REVIEW (0s): 4 criteria, 1 untrusted (c4), 0 suspects, 0 findings
```

## Fields

| Field | Source | Meaning |
|---|---|---|
| `N criteria` | `len(charter.criteria)` | Total criteria in the charter |
| `N untrusted` | `test_to_criterion` entries with `encodes=False` | Criteria whose tests judges distrusted |
| `N suspects` | Overfit audit results | Criteria flagged as potentially overfit |
| `N findings` | Quality lint results | Static analysis findings on test code |

## Implementation

```python
def _run_summary(charter, test_to_criterion, overfit_suspects, quality_findings):
    """Build a one-line summary of the run outcome."""
    n_criteria = len(charter.criteria)
    untrusted = [cid for cid, info in test_to_criterion.items() if not info.get("encodes", True)]
    n_untrusted = len(untrusted)
    n_suspects = len(overfit_suspects) if overfit_suspects else 0
    n_findings = len(quality_findings) if quality_findings else 0

    parts = [f"{n_criteria} criteria"]
    if n_untrusted:
        parts.append(f"{n_untrusted} untrusted ({', '.join(untrusted)})")
    else:
        parts.append("0 untrusted")
    parts.append(f"{n_suspects} suspects")
    parts.append(f"{n_findings} findings")
    return ", ".join(parts)
```

## Call Sites

1. **COMPLETE path** (`loop.py`): After the stop condition passes, before the merge.
   Emitted as `✅ complete (0s): <summary>`.

2. **HUMAN_REVIEW path** (`loop.py`): When the run exits with HUMAN_REVIEW (test fault,
   overfit, or quality lint failure). Emitted as `❌ HUMAN_REVIEW (0s): <summary>`.

3. **`_return_human_review` helper** (`loop.py`): Accepts `charter` and `test_to_criterion`
   kwargs to build the summary. Falls back gracefully to a bare "done" if neither is
   provided (for call sites that don't have access to the charter).

## Why This Exists

Before this, the COMPLETE marker was missing entirely and the HUMAN_REVIEW marker said
only "test fault: criteria ['c4'] have no judge-trusted test" — the user had to read the
grounding block to understand the full outcome. The summary gives a one-line rollup of
every dimension the stop condition checks: criteria count, judge trust, overfit, and
quality lint. A reader can understand the run's outcome from the control channel alone.

## Pitfall: Missing Charter/Test Mapping

Some HUMAN_REVIEW return points in `run_v1` don't go through `_return_human_review` —
they return directly with a bare string. These call sites don't have access to the charter
or `test_to_criterion` mapping, so the summary degrades gracefully to "done." The
`_run_summary` helper is robust to `None` inputs — it returns "done" when it can't build
a meaningful summary.
