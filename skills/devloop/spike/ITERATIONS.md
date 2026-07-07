# devloop spike — iteration log

Tight run → learn → improve cycles to de-risk the native-loop bet (step 0). Each cycle:
1. **Run** one (or a few) tasks: `python3 spike/probe.py --request "..." [--touches ...] [--expect-human-review]`
   (transcripts saved to `.devloop/transcripts/<ts>_<id>.json`, default-gitignored)
2. **Learn/debug**: read the transcript + fidelity flags; find where the loop deviated.
3. **Improve**: change the smallest thing (usually `spike/spike_skill.md` prose, sometimes the
   parser/harness; later the real SKILL.md prompt sections).
4. **Log** the cycle below and re-run.

Distilled signal only — raw transcripts live in `transcripts/`.

| # | Date | Task (kind) | Verdict | Observation | Change made |
|---|---|---|---|---|---|
| 0 | 2026-06-29 | cursor pagination, /orders+/invoices+openapi (clear multi-file) | pass (8s) | Faithful CHARTER→PLAN→BUILD→VERIFY; added a sensible DoD edge-case (out-of-range limit→400); correct keyset-pagination reasoning; honored gated stop. Runtime appended a benign `SUGGESTION:{…}` trailer. | none (baseline) |
| 1 | 2026-06-29 | "make the thing faster" (vague, negative path) | pass→HUMAN_REVIEW (6s) | ✅ Correctly refused: "no baseline or goal, nothing to measure against" → ROUTE_HUMAN_REVIEW, did NOT charge ahead. The key correctness behavior holds. | none |
| 2 | 2026-06-29 | "speed up orders endpoint, slow for big accounts" (borderline) | pass→PROCEED (9s) | ⚠️ PROCEEDed but **invented an un-measurable DoD** ("within a target wall-clock budget", no number) — violates DoD-as-oracle + the correctness-bias policy. Good scope instinct (pulled in models + tests beyond `touches`). | **CHARTER prose**: criteria must be checkable w/ numeric threshold for perf goals; don't invent targets for unmeasurable goals → route to human + log assumptions |
| 3 | 2026-06-29 | re-run of cycle 2 (same task, post-fix) | pass→HUMAN_REVIEW (16s) | ✅ Prose fix validated: now refuses to fabricate a target, routes to HUMAN_REVIEW, and asks the user for the exact missing numbers (target p95, account size, current latency). | none (confirms cycle-2 fix) |
| 4 | 2026-06-29 | User.email→primary_email rename across model+migration+schemas+routes+callers+tests (large blast radius) | pass→PROCEED (79s) | ✅ Excellent scoping: traced full ripple, used `grep -rn '\.email'` for unknown callers, **grep-zero-match DoD** (great rename oracle), stated its constraint assumption explicitly (new rule held). Did NOT split a large-but-known scope. **79s** (vs 8-16s) — complex tasks much slower. | none |
| 5 | 2026-06-29 | idempotency-key on POST /payments, ×3 repeats (consistency) | pass×3→PROCEED (26s/29s/**152s**) | ✅ Structural consistency PERFECT: 3/3 identical CHARTER→PLAN→BUILD→VERIFY + PROCEED + pass + no flags. ⚠️ Latency variance ~6x (26→152s) on identical input. | none |

| 6 | 2026-06-29 | prompt-review hardening (spike_skill.md) + re-validate (clean + loophole probe) | pass + ROUTE_HUMAN_REVIEW | A `prompt-reviewer` pass found our cycle-2 "measurable criteria" fix had an ASSUMPTION LOOPHOLE ("state assumptions explicitly" let a model *assume* a missing target and PROCEED). Rewrote spike_skill.md: closed the loophole (may only restate requester-supplied values), exhaustive marker whitelist, no code fences, no preamble grouping, headless no-questions. Re-validation: clean task → clean pass + no stray SUGGESTION trailer; loophole probe ("acceptably fast") → ROUTE_HUMAN_REVIEW citing "I must not invent thresholds or label them as assumptions." | spike_skill.md full rewrite; SKILL.md C-2/C-3/H-1/H-3/H-4/H-5/M-1/M-2/M-4 applied; references/prompt-review-2026-06-29.md (B1 blueprint) |

## Updated learnings
- **Structural determinism is strong**: 6/6 runs clean phase fidelity; ×3 repeat of one task gave identical structure. Native-loop orchestration shape is reliable — the core step-0 bet looks good.
- **Latency is highly variable** (cycle 5: 26s/29s/152s same task; cycle 4: 79s): cloud-model wall-clock is NOT stable run-to-run. Real loop MUST keep generous per-call timeouts/budgets (cf. memory: never shorten timeouts to "fix" a slow model). run_one default 1800s is safe.
- **Blast-radius calibration question (open)**: a large-but-known scope PROCEEDs as one plan (no split). Decide for step 2: proactively split big blast radius into kanban subtasks, or only split on mid-run overrun? Cycle 4 suggests the model scopes large tasks competently in one pass, so split-on-overrun may suffice.
- **Carry to step-2 SKILL.md**: the measurable-criteria/assumption rules (cycles 2-3) + grep-zero-match as a strong DoD oracle pattern for refactors/renames (cycle 4).

## Learnings to carry to step-2 SKILL.md (the real CHARTER prompt section)
- **Measurable-criteria rule** (validated cycles 2→3): every DoD criterion must be a checkable predicate; performance/size/latency goals need a numeric threshold; **never invent a target** — an unmeasurable goal routes to HUMAN_REVIEW and asks for the number. Any assumption needed to make a criterion checkable must be stated explicitly (and, under the 0.7 confidence floor, lowers confidence → likely human-review).
- **Native loop fidelity is solid so far** (4/4 runs clean ordering, no skips, gated stop honored) — strong positive signal for the prose-on-native-loop bet vs. a code FSM.
- **Ambiguity calibration is prose-tunable** — a single CHARTER edit flipped borderline behavior to the correctness-biased policy with no code change.

## Open questions to drive runs
- Does a **deliberately vague** request correctly route to HUMAN_REVIEW (not charge ahead)?  ← negative path, highest-value
- Is phase ordering **consistent across repeats** of the same task (n≥2)?
- Does a **large blast-radius** task get split / flagged, or does the model under-scope?
- Does the model ever emit a **forged COMPLETE** (done before VERIFY)? (the gate must catch it)
- Marker discipline: any runs with missing/duplicate/extra markers?
