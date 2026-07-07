"""state.py — atomic checkpoint + Charter store + run counters + LEARNINGS IO.

Durability/atomicity cannot be prose: a half-written checkpoint corrupts a later
read invisibly. All writes use write-temp-then-rename (atomic on POSIX).

The checkpoint is a POST-MORTEM / HUMAN_REVIEW artifact: the loop writes it at every
step but never re-ingests it (loop-level resume was deleted — every invoke is fresh;
see loop.run_v1). load_checkpoint stays as the inspection/durability reader.

LEARNINGS IO: append_learning writes the project-level lessons journal;
read_learnings reads the last-N (consumed by the project outer loop).

Borrowed pattern: oh-my-hermes omh_state.py atomic-write.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import config
import evidence as _evidence

_CHECKPOINT = "ITERATION_STATE.json"
_SCHEMA_VERSION = 1

# A Charter is a plain dict; these keys must be present before PLAN. Only the fields a downstream
# stage actually consumes are required — the state-flow audit found happy_path / blast_radius /
# backoff_map / advisors_verdict / ambiguity_decision / purpose were written but NEVER re-ingested
# (write-only stubs), so they no longer gate validation. Re-add a key WHEN a stage reads it
# (blast_radius with #13, advisors/ambiguity-journal with the council, etc.).
CHARTER_REQUIRED_KEYS = (
    "interpreted_intent",  # -> implementer prompt + refine draft
    "dod",                 # list[{id, criterion, verify_intent, kind}] -- the loop spine
    "assumptions",         # list[{text, confidence}] -> ambiguity confidence floor; MAY be empty
    "open_questions",      # list[{text, blocking}]   -> ambiguity gate + project escalate; MAY be empty
)
# Keys whose empty value is VALID (an empty list means "none", not "missing").
CHARTER_MAY_BE_EMPTY = frozenset({"assumptions", "open_questions"})


def atomic_write_json(path: str | os.PathLike, obj: Any) -> None:
    """Write obj as JSON atomically (temp file in same dir + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=False, default=_json_default)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _json_default(o):
    """Serialize Evidence (and any to_dict-able) inside the checkpoint."""
    if hasattr(o, "to_dict"):
        return o.to_dict()
    raise TypeError(f"not JSON-serializable: {type(o).__name__}")


def new_run_state(charter: dict) -> dict:
    """Fresh run state with the code-enforced backstop counters."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "charter": charter,
        "rebuild_count": 0,   # consecutive local re-BUILD fails since last PLAN
        "replan_count": 0,    # re-PLANs so far
        "repair_used": False,  # the ONE judged mid-run test repair (loop.py, 2026-07-02)
        "evidence_ledger": {},  # criterion_id -> Evidence.to_dict()
    }


def on_rebuild_fail(state: dict) -> None:
    state["rebuild_count"] = state.get("rebuild_count", 0) + 1


def on_repair(state: dict) -> None:
    """A judged test-repair succeeded (loop.py, user decision 2026-07-02): the repaired oracle
    gets a fresh back-off budget — loop max_passes stays the absolute cap. The at-most-once
    bound lives in `repair_used`, which the LOOP burns BEFORE attempting the repair (a single
    setter, mutant-pinned there; setting it here too would mask that guard)."""
    state["rebuild_count"] = 0
    state["replan_count"] = 0


def on_replan(state: dict) -> None:
    state["replan_count"] = state.get("replan_count", 0) + 1
    state["rebuild_count"] = 0  # local retries reset on a structural re-plan


def save_checkpoint(run_dir: str | os.PathLike, state: dict) -> None:
    """Persist the full run state (Charter + counters + evidence ledger)."""
    atomic_write_json(Path(run_dir) / _CHECKPOINT, state)


def load_checkpoint(run_dir: str | os.PathLike) -> dict | None:
    """Load a persisted run state for INSPECTION/POST-MORTEM, or None if absent/corrupt/
    wrong-shape (fail-safe: never surface garbage). Rehydrates the evidence ledger to
    Evidence. NOT a resume path — the loop never re-ingests a checkpoint (every invoke
    is fresh); this reader exists for humans, tests, and the durability guarantee."""
    p = Path(run_dir) / _CHECKPOINT
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or "charter" not in data:
        return None  # wrong type / partial dict -> restart, never resume garbage
    ledger = data.get("evidence_ledger")
    if isinstance(ledger, dict):
        data["evidence_ledger"] = {
            cid: _evidence.Evidence.from_dict(v) if isinstance(v, dict) else v
            for cid, v in ledger.items()
        }
    return data


def validate_charter(charter: dict) -> list[str]:
    """Return a list of validation errors (empty == valid). Replaces a 120-LOC schema
    validator. An empty list for CHARTER_MAY_BE_EMPTY keys is valid (means "none")."""
    errs: list[str] = []
    for k in CHARTER_REQUIRED_KEYS:
        if k not in charter:
            errs.append(f"missing Charter key: {k}")
        elif k in CHARTER_MAY_BE_EMPTY:
            if not isinstance(charter[k], list):
                errs.append(f"Charter key {k} must be a list")
            else:
                # Element shape matters: gate.ambiguity_gate calls .get() on every entry, so a
                # bare-string assumption/open_question (a common LLM slip) must fail closed HERE
                # with a message — not crash the first gate of every run with AttributeError.
                errs += [f"{k}[{i}] is not an object" for i, x in enumerate(charter[k])
                         if not isinstance(x, dict)]
        elif charter[k] in (None, "", [], {}):
            errs.append(f"missing/empty Charter key: {k}")
    for i, c in enumerate(charter.get("dod") or []):
        if not isinstance(c, dict):     # a malformed (non-dict) criterion fails closed with a message, never crashes
            errs.append(f"dod[{i}] is not an object (a criterion must be a dict)")
            continue
        if not c.get("id") or not c.get("verify_intent"):
            errs.append(f"dod[{i}] missing id or verify_intent (a criterion must be checkable)")
    return errs


def read_learnings(learnings_path: str | os.PathLike,
                   last_n: int = config.LEARNINGS_READ_WINDOW) -> list[dict]:
    """Read the last-N entries from the append-only LEARNINGS.jsonl journal
    (default window from config.LEARNINGS_READ_WINDOW)."""
    p = Path(learnings_path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text().splitlines()[-last_n:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip a malformed line rather than crash directed back-off
        if isinstance(obj, dict):     # ignore parseable-but-non-dict lines (the journal is dict-per-line)
            out.append(obj)
    return out


def append_learning(learnings_path: str | os.PathLike, entry: dict) -> None:
    """Append ONE JSON-line lesson to the append-only journal read by read_learnings. Uses a plain
    fsync'd append — NOT atomic_write_json (which rewrites the WHOLE file and would clobber the
    growing journal). Crash-safe by construction: read_learnings skips a torn trailing line. One
    line per entry (json.dumps emits no embedded newline). This is the WRITE half that pairs with
    read_learnings above (the project outer loop's lessons-learned log)."""
    p = Path(learnings_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=_json_default)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def ev(phase, step, level, *, rc=None, detail="", outcome=""):
    """One diagnostic event (pure — no timestamp; the sink stamps ts/seq/run).
    phase: 'merge'|'sync'|'conflict'|'finalize'|'boundary'|'scrub'
    level: 'info' (decision) | 'warn' (degradation/refusal) | 'error' (a git op failed)."""
    assert phase and step and level in ("info", "warn", "error")
    return {"phase": phase, "step": step, "level": level,
            "rc": rc, "detail": str(detail)[:300], "outcome": str(outcome)}
