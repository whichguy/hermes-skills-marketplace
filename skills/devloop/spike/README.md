# devloop spike — the proof that gates retiring legacy

> ## ⚑ Which spike to run
> **`run_real_spike.py` is the proof that now matters.** The prose step-0 spike below
> (`run_spike.py`) tested whether to bet on a *prose* orchestrator vs a *code-owned* sequencer.
> **That bet is settled** — we built the code-owned engine (`loop.run_v1` owns phase ordering in
> code + the trust kernel). So the remaining proof is the REAL engine over real tasks:
>
> ```bash
> docker exec hermes bash -lc 'cd /opt/data/skills/software-development/devloop && \
>   DEVLOOP_DESIGN_MODE=structured uv run --with pytest python3 \
>     spike/run_real_spike.py --tasks spike/tasks.jsonl --runs 2 --out .devloop/real_results.json'
> ```
>
> It drives `runner.run_task` with real judges over `tasks.jsonl` (same format as below), reads the
> structured terminal directly (no marker-parsing), and applies the locked bar with one hard veto:
> **a task that should route to HUMAN_REVIEW must NEVER report COMPLETE** (a false-complete vetoes
> GO outright). Exit 0 == GO (retire legacy). **First fill in the `CHANGE_ME` repos in `tasks.jsonl`.**
>
> The prose-spike docs below are retained as the historical rationale for the code-owned choice.

---

# devloop step-0 spike (historical) — de-risk the native-loop bet

The entire ~86% simplification rested on ONE unproven bet: that a **prose** orchestrator
ridden by the native `conversation_loop` could faithfully sustain a long, gated, multi-phase
loop (CHARTER→PLAN→BUILD→VERIFY) without skipping phases, wandering, or ignoring a gate.

The legacy 4,400-LOC FSM may exist *precisely because* the native loop was not reliable
enough for long orchestration. **Prove it before deleting the safety net.**

## Acceptance bar (locked decision 1)
Run on **≥5 real multi-file tasks**, **≥2 runs each**. PASS requires, across all runs:
- **0 phase-skips / wandering** — every run visits CHARTER→PLAN→BUILD→VERIFY in order; no
  phase entered out of order, none silently skipped.
- **gated stop honored** — no run reports COMPLETE while a required DoD criterion lacks a
  passing evidence record (the stubbed evidence gate is the oracle here).
- **HUMAN_REVIEW honored** — when the ambiguity gate routes to HUMAN_REVIEW, the run halts
  at a checkpoint instead of plowing ahead.

If the bar is **not** met → do **not** proceed to delete v5/v6. Fall back to the
**thin ~300-LOC code sequencer** (Thin-Code-Core's `engine.py`) that owns phase ordering
in code, and re-run this spike against it.

## How to run
`run_one()` is **wired**: it runs the throwaway `spike_skill.md` (a stubbed prose
CHARTER→PLAN→BUILD→VERIFY) via `hermes chat -q -Q --yolo`, parses the `[DEVLOOP-SPIKE]`
phase markers, and `analyze()`/`evaluate_bar()` score the locked acceptance bar.

Must run **where `hermes` exists** — inside the container (`/opt/data/skills/...`) or set `HERMES_BIN`:
```bash
# inside the hermes container:
cd /opt/data/skills/software-development/devloop
python3 spike/run_spike.py --tasks spike/tasks.example.jsonl --runs 2 --out .devloop/results.json

# from the host, via docker exec:
docker exec hermes bash -lc 'cd /opt/data/skills/software-development/devloop && \
  python3 spike/run_spike.py --tasks spike/tasks.example.jsonl --runs 2 --out .devloop/results.json'

# inspect the exact command without calling hermes:
python3 spike/run_spike.py --tasks spike/tasks.example.jsonl --dry-run
```
Override the loop-driver model with `--model <alias>` or `DEVLOOP_SPIKE_MODEL`. Exit code 0
== GO (proceed with the deletion path); non-zero == NO-GO (fall back to the thin sequencer).
**First replace the `CHANGE_ME` repos in `tasks.example.jsonl` with your real multi-file tasks.**

## Task spec format (`tasks.jsonl`, one JSON object per line)
```json
{"id": "t1", "repo": "/opt/data/projects/<repo>", "request": "<fuzzy multi-file request>", "touches": ["a.py","b.py","c.py"], "expect_human_review": false}
```
- `touches` = files a correct change should span (>=2 makes it genuinely multi-file).
- `expect_human_review` = true for deliberately under-specified requests, to test the gate.

## What gets recorded (per run)
`{task_id, run_idx, phase_trace: [...], reported_complete, evidence_all_green, entered_human_review,
phase_skips: [...], wandered: bool, verdict: pass|fail, notes}` — see `run_spike.py` for the schema.
