# Advisor Review — Devloop Improvement Roadmap (2026-07-07)

> 3-seat panel (DeepSeek V4 Pro, Kimi K2.7 Code, Qwen 3.6 35B) → GLM 5.2 synthesis.
> All three independently converged on the same four-pillar roadmap.

## Experimental Baseline

| Experiment | What | Result |
|---|---|---|
| E1: SKILL.md slim | Moved 18 FIXED pitfalls → `references/fixed-pitfalls-archive.md` | 65KB → 41KB (36.6% reduction), 448/448 tests pass |
| E2: Live devloop run | `devloop "Create slug.py..."` greenfield | COMPLETE in 212s. Progress markers work but lack Phase 2 detail |

## Advisor Consensus — Four-Pillar Roadmap

### P0 — ✅ SHIPPED 2026-07-07

1. **✅ Slim SKILL.md to 10-14KB.** → **11.6KB / 165 lines.** Moved to `references/`: engine-pipeline.md, scout-pipeline.md, terminal-contract.md, observability-testing.md, improvement-loop.md, pitfalls-index.md, fixed-pitfalls-archive.md. Kept: frontmatter + description, "how to run," "what comes back," trust boundary, pitfalls index (1-line summaries + links), env knobs table. Commit: `d06b488`.

2. **✅ Phase 2 + Phase 3 + Phase 4 progress output.** Shipped together in one implementation pass:
   - **`progress.jsonl`** written to every trace bundle alongside `trace.jsonl` — machine-parseable event stream with `ts`, `step`, `detail`, `ok`, `elapsed_s`
   - **`DEVLOOP_PROGRESS`** env knob: `verbose` (default, all stderr), `compact` (loop markers only), `quiet` (no stderr, jsonl still written). Was documented but never implemented — now real.
   - **Planning announcements** (`runner.py`): `🧭 planning loop beginning` with request, target, branch, planner model, prior learnings, env survey. Post-charter announcement shows decomposed DoD.
   - **Per-criterion judge verdicts** with elapsed time, individual judge votes, and reason text on distrust
   - **Evidence pass/fail counts** with attempt numbers during rebuild loops
   - **Terminal events**: COMPLETE and HUMAN_REVIEW both emit progress events
   - **HUMAN_REVIEW bypasses compact/quiet**: all 6 HUMAN_REVIEW exit paths emit unconditional stderr
   - **12 new tests** (`test_progress.py`), 460/460 full suite passes, zero regressions
   - Commits: `d06b488`, `77baf2d`, `2b39692`, `bbd3bac`

### P1 — Partially shipped

3. **✅ Daily script-first digest cron.** `scripts/devloop_digest.py` (512 lines) — scans `devloop-traces/` for last 24h, parses `progress.jsonl` (preferred) or `trace.jsonl` (fallback), emits markdown digest (run count, terminal breakdown, avg/p95 wall-clock, failure modes, learning themes). Silent on empty. JSON mode (`--json`). Cron job `6fcb443fd52b` runs daily at 12pm UTC (5am PT), no-agent, silent on empty, delivers to Slack. Commit: `2b39692`.

4. **E2E/CLI dry-run verification seam.** Add `verify_cmd` field to criterion schema so integration-tier criteria can run the real binary with `--dry-run` instead of (or alongside) pytest. Thread through `evidence.py`. Closes the `calendar-quick-add` gap. Needs advisor review before implementation (touches false-complete boundary).

### P2 — Deferred correctly

5. Project outer loop live caller (wire to cron or `hermes devloop-project`)
6. Content-restructuring wrapper (prompt-file + Kimi dispatch — proven alternative, formalize it)
7. Multi-language oracle spine (design doc only)
8. Token/cost accounting (blocked on platform)

## Experiments to Run (in order)

| # | Experiment | Hypothesis | Result |
|---|---|---|---|
| E1 | SKILL.md slim | <14KB SKILL.md preserves invocation correctness | ✅ **11.6KB / 165 lines.** 460/460 tests pass. 6 new reference files. |
| E2 | Phase 2+3 progress | Per-criterion verdicts + evidence counts are actionable mid-run | ✅ **Shipped.** `progress.jsonl` + `DEVLOOP_PROGRESS` levels + planning announcements + per-criterion judge verdicts + evidence pass/fail + terminal events. 12 new tests. |
| E3 | Digest prototype | Script-first digest surfaces useful patterns at zero LLM cost | ✅ **Shipped.** `scripts/devloop_digest.py` (512 lines). Cron `6fcb443fd52b` at 12pm UTC daily. |
| E4 | CLI dry-run criterion | Integration-tier dry-run catches command-format bugs | ⏳ **Next.** Needs advisor review before implementation. |
| E5 | Skill registration | Devloop registers cleanly as a Hermes skill | ⏳ Deferred. |

Run **E1 + E2 + E3 in parallel** (independent, low-risk). Then E4 with advisor review. Then E5.

## Disagreements (all resolved)

1. **Phase numbering error (Qwen).** Qwen swapped Phase 2/3 labels — resolved to canonical numbering.
2. **Digest frequency (Qwen vs DeepSeek/Kimi).** Qwen said weekly; DeepSeek/Kimi said daily. **Daily wins** — matches user's ~5am PT morning-info pattern.
3. **Progress delivery mechanism.** DeepSeek proposed `--progress-file`, Kimi proposed `progress.jsonl`, Qwen proposed Telegram delivery. **Resolution: emit `progress.jsonl` to trace directory** — digest cron and messaging hooks can both consume it.

## Caveats

- **SKILL.md slimming risk:** Moving pitfalls to 1-2 line summaries could lose nuance. E1 must verify models still avoid known pitfalls from summaries alone.
- **E2E seam touches false-complete boundary.** `verify_cmd` introduces a new trust surface — needs same fail-closed discipline as existing evidence gate. Advisor review before implementation is not optional.
- **`progress.jsonl` is a new artifact.** Must be handled by crash-finalize path. Test concurrent-write safety.
- **Digest assumes trace.jsonl is stable.** Add schema-version check that exits with visible warning on mismatch.
- **Interrupted-run resume gap** (DeepSeek raised as gap #9) is correctly deferred to P2 but should stay on the roadmap.

## Confidence

**High.** All three advisors independently converged on the same four-pillar structure with the same priority ordering. Only disagreements were labeling errors, frequency nuances (resolved by user profile), and delivery-mechanism details (complementary, not conflicting).
