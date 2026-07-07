"""evidence.py — the trust anchor. Runs verification commands as subprocesses and
reports the REAL exit code. An LLM asserting "tests green" is the silent-wrong-answer
failure mode this module exists to eliminate.

Invariants:
  * FAIL CLOSED — any exception / timeout / non-zero exit => passed=False. A None or
    error NEVER reads as pass (fixes the legacy "non-determinism returns None" defect).
  * No shell=True — commands are arg lists; never interpolate untrusted text into a shell.
  * Timeout/token caps are sourced from Hermes config, never hardcoded low (project policy).
  * Round-trippable — Evidence survives a checkpoint save/load via to_dict()/from_dict().

Borrowed pattern: oh-my-hermes evidence_tool.py (subprocess runner + injection guards).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, asdict
from typing import Sequence

_TAIL = 4000  # chars of stdout/stderr to retain in the immutable record


@dataclass(frozen=True)
class Evidence:
    criterion_id: str
    cmd: tuple[str, ...]
    exit_code: int | None
    passed: bool
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        """Rehydrate from persisted JSON (cmd comes back as a list -> tuple)."""
        return cls(
            criterion_id=d["criterion_id"],
            cmd=tuple(d.get("cmd", ())),
            exit_code=d.get("exit_code"),
            passed=bool(d.get("passed", False)),  # fail-closed default
            stdout_tail=d.get("stdout_tail", ""),
            stderr_tail=d.get("stderr_tail", ""),
            error=d.get("error"),
        )


def _passed(e) -> bool:
    """Read .passed from either an Evidence or a not-yet-rehydrated dict. Fail-closed."""
    if isinstance(e, Evidence):
        return e.passed
    if isinstance(e, dict):
        return bool(e.get("passed", False))
    return False


def evidence_timeout_s() -> int:
    """Per-call subprocess timeout. TODO(step 1): read from the Hermes runtime config
    (config.py / ollama_client.py). The fallback is deliberately HIGH so a slow run is
    never killed prematurely; never lower it to "fix" a slow model (project policy)."""
    return 3600


def run(criterion_id: str, cmd: Sequence[str], cwd: str | None = None,
        timeout: int | None = None) -> Evidence:
    """Run `cmd` (an arg list) and return an immutable Evidence record keyed to a DoD id."""
    if not cmd or not isinstance(cmd, (list, tuple)):
        return Evidence(criterion_id, tuple(cmd or ()), None, False,
                        error="empty or non-list command (refusing to run via shell)")
    timeout = timeout or evidence_timeout_s()
    try:
        r = subprocess.run(
            list(cmd), cwd=cwd, capture_output=True, text=True,
            timeout=timeout, shell=False, check=False,
        )
        return Evidence(
            criterion_id=criterion_id,
            cmd=tuple(cmd),
            exit_code=r.returncode,
            passed=(r.returncode == 0),
            stdout_tail=(r.stdout or "")[-_TAIL:],
            stderr_tail=(r.stderr or "")[-_TAIL:],
        )
    except subprocess.TimeoutExpired:
        return Evidence(criterion_id, tuple(cmd), None, False, error=f"timeout after {timeout}s")
    except (OSError, ValueError) as e:
        return Evidence(criterion_id, tuple(cmd), None, False, error=f"{type(e).__name__}: {e}")


def all_passing(ledger: dict, required_ids: Sequence[str]) -> bool:
    """True iff every required criterion id has a passing Evidence record. Fail-closed:
    an empty required set is NOT a pass (absence of evidence is not evidence of passing),
    and a missing id is a fail. Accepts Evidence objects or persisted dicts."""
    if not required_ids:
        return False
    return all(cid in ledger and _passed(ledger[cid]) for cid in required_ids)
