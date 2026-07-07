"""devloop configuration — the 5 locked decisions (2026-06-29) as constants.

IMPORTANT: token caps and per-call timeouts are NOT defined here. They MUST be read
from the Hermes runtime config at call time. Never hardcode a lower cap/timeout to
"fix" a slow model. `evidence.py:evidence_timeout_s()` is where the subprocess timeout
WILL be sourced from Hermes config — it is currently a TODO with a deliberately HIGH
fallback (so a slow run is never killed), to be wired in step 1.
"""
from __future__ import annotations

# --- Decision 2: ambiguity / autonomy (correctness-biased) -------------------
# PROCEED only if no blocking open-question AND min(assumption.confidence) >= floor.
CONFIDENCE_FLOOR: float = 0.65   # lowered 0.7->0.65 (spike: reasonable defaults scored 0.60-0.66 and over-routed to human; paired with planner confidence-calibration in the CHARTER/REFINE prompts)

# --- Decision 3: council timing ----------------------------------------------
COUNCIL_EVERY_MERGE: bool = True   # v1: advisors council runs at every merge gate
COUNCIL_SIZE: int = 3              # advisor seats that MUST be consulted (fail-closed if fewer present)
COUNCIL_QUORUM: int = 2            # distinct seats that must affirm (fail-closed otherwise)

# --- Canonical decision strings (single source; avoids casing drift) ---------
DECISION_PROCEED: str = "PROCEED"
DECISION_ROUTE_HUMAN_REVIEW: str = "ROUTE_HUMAN_REVIEW"

# --- Decision 4: LEARNINGS in back-off ---------------------------------------
LEARNINGS_READ_WINDOW: int = 20    # last-N learnings consulted by directed back-off
BACKOFF_PER_TASK_APPENDS: bool = False  # v1: static back-off table only

# --- Decision 1: spike acceptance bar ----------------------------------------
SPIKE_MIN_TASKS: int = 5
SPIKE_RUNS_PER_TASK: int = 2
SPIKE_MAX_PHASE_SKIPS: int = 0     # zero tolerance for phase-skips/wandering

# --- Single reactive back-off backstop (NOT the legacy 3 stagnation systems) --
MAX_LOCAL_REBUILDS: int = 3        # consecutive local re-BUILD fails -> re-PLAN
MAX_REPLANS: int = 3               # re-PLAN exhausted -> HUMAN_REVIEW

# --- Dispatch resilience (parity rebuilds the spike will exercise) ------------
MAX_DISPATCH_RETRIES: int = 2      # #36: retries on a transient (empty/refusal/process-error) phase dispatch
DIAGNOSE_AFTER_ATTEMPT: int = 1    # #35: rebuild attempt at/after which a stronger model diagnoses the red

# --- Determinism debiasing (spike: single flaky judge/advisor votes over-routed to human) -----
JUDGE_VOTES: int = 3               # each judge votes N times; a strict MAJORITY decides (damps flakiness)
ADVISOR_VOTES: int = 3             # the advisor votes N times; block ONLY if a MAJORITY flag a blocking gap

# --- Project OUTER loop (cross-task) -----------------------------------------
PROJECT_MAX_ATTEMPTS: int = 3      # re-attempts per purpose lineage before BLOCKED (mirrors MAX_REPLANS)
# Header the project loop folds prior lessons in under; runner.py strips everything from this
# line onward before the vague_goal_gate (lesson text carries outcome markers/numbers — "changed
# 3 file(s)", "FASTER" — that would otherwise trip the marker screen on every re-attempt).
LESSONS_HEADER: str = "PRIOR LESSONS LEARNED (guidance, NOT new requirements):"

# --- HUMAN_REVIEW async policy (gut-check operational fix) --------------------
HUMAN_REVIEW_STALE_HOURS: int = 48  # checkpoints idle longer than this are flagged stale

# Hermes config keys to read at runtime (do NOT duplicate values here):
#   agent.max_turns, agent.reasoning_effort  -> inherited via the `ask` skill
#   token caps / per-call timeout            -> Hermes config.py / ollama_client.py
