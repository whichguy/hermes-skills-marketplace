# Adversarial Self-Review — Live Test (2026-06-28)

Pattern 5 (Adversarial Meta-Review) was used to review the advisors skill
itself — the pattern that defines Pattern 5. This is the meta-pattern: use
the adversarial review on the review framework.

## Setup

- **Panel:** DeepSeek (Reasoner) + Kimi (Coder) + Qwen (Local Lens)
- **Target:** `skills/autonomous-ai-agents/advisors/SKILL.md` (v3.1.0)
- **Question:** "Review the advisors skill for correctness, completeness, and
  clarity. Flag any bugs, missing steps, or structural issues."

## Round 1 — Independent Review

| Seat | Time | Key Findings |
|---|---|---|
| DeepSeek | 134.6s | 4 code bugs (missing import sys, etc.), pattern count wrong, orphaned "refine" in overview, Pattern 4 should merge into primitive |
| Kimi | 53.2s | Missing when-to-use tables for Patterns 2/3, Pattern 5 code duplication, Quick Reference incomplete |
| Qwen | 27.7s | Pattern 7 needs stopping condition, Pattern 2 vs 1 guidance missing |

**Consensus:** 10 issues identified, categorized as 3 must-fix, 5 should-fix, 2 nice-to-have.

## Round 2 — Adversarial Meta-Review

Hostile auditor prompt: "Find the specific factual error in this consensus,
or say NO SPECIFIC ERROR FOUND."

| Seat | Time | Finding |
|---|---|---|
| DeepSeek | 45.2s | **CAUGHT CONTROLLER ERROR:** Consensus said "DeepSeek did not flag code issues" — but DeepSeek's review explicitly flagged 4 code bugs including the `import sys` error. The controller misrepresented DeepSeek's review in the synthesis. |
| Kimi | 38.1s | Confirmed the misrepresentation. Also noted consensus understated Kimi's findings (said "minor" but Kimi flagged structural issues). |
| Qwen | — | Timed out |

**Decision tree applied:**
- DeepSeek's finding: VERIFIED ERROR → correct the consensus
- Kimi's finding: VERIFIED ERROR → correct the consensus
- Qwen timeout: DISCARD (no data)

## Step 4 — Final Synthesis

Corrected the consensus to accurately reflect each seat's findings. Applied
all 10 fixes to the skill. Committed as v3.2.0.

## What This Validates

1. **The adversarial round works.** It caught a real synthesis error that
   would have gone unnoticed — the controller (me) misrepresented what
   DeepSeek actually said. This is exactly the failure mode Pattern 5 was
   designed to catch.

2. **The hostile auditor prompt is effective.** "Find the specific factual
   error" forced the models to compare the consensus against their own
   original reviews, not just rubber-stamp.

3. **2/3 seats is sufficient.** Qwen timed out but DeepSeek + Kimi both
   independently caught the same error. A 2-seat result is actionable.

4. **The meta-pattern works.** Using Pattern 5 to review the skill that
   defines Pattern 5 is a valid self-improvement loop. The pattern
   validated itself and then improved itself.

## Controller Pitfall

The synthesis step (Step 4 in Pattern 1) is the weakest link. When
synthesizing 3 long reviews, it's easy to misattribute findings or
understate a seat's contribution. The adversarial round is the safety net
for this — but the controller should also:

- Re-read each seat's original output before writing the consensus
- Quote specific passages, don't paraphrase from memory
- If a seat's output is too long to fully absorb, flag that as a limitation
