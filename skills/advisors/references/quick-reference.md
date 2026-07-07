# Quick Reference

```
# ── Data Channel Principle (v3.4+)
# Brief data lives on disk. Controller context carries only prompts + file paths.
# Use dispatch_advisors.py for multi-seat panels. Use prompt_model.py for single
# queries. Only synthesis.md (~1-2K chars) enters controller context.

# ── dispatch_advisors.py (preferred for panels)
# CLI all-in-one:
python3 dispatch_advisors.py run -q "question" --context-file data.md --outdir /tmp/advisors
# Python import:
from dispatch_advisors import AdvisorDispatch
ad = AdvisorDispatch(outdir='/tmp/advisors')
ad.prepare_brief(question="...", context_file="data.md", verify_preamble=True)
ad.dispatch(seats=[("deepseek-v4-pro:cloud", "Reasoner"), ("kimi-k2.7-code:cloud", "Coder")])
ad.synthesize()  # GLM reads seat files from disk → synthesis.md
print(ad.read_synthesis())  # ~1-2K chars into context

# ── prompt_model.py (primitive — single queries, legacy dispatch)
python3 prompt_model.py -m <model> -p <prompt> [--context ...] -o <file>

# Pattern 1: Advisors (3 parallel + GLM synthesis) — most decisions
1. Show dispatch plan
2. prepare_brief() → dispatch() — seats read brief from disk (data stays out of context)
3. synthesize() — GLM reads seat files from disk → synthesis.md
4. read_synthesis() — ~1-2K chars into context, report to user

# Pattern 2: Sequential Review Chain — cumulative expertise
1. Dispatch model A → read output
2. Dispatch model B with A's output as context → read
3. Dispatch model C with B's output as context → read
4. Report final refined answer

# Pattern 3: A/B Comparison — model divergence check
1. Dispatch same prompt to 2 models → 2 files
2. diff the output files
3. Report where they agree and diverge

# Pattern 4: Single Model Query — one model is enough
python3 prompt_model.py -m <model> -p <prompt> [--context ...] -o <file>

# Pattern 5: Adversarial Meta-Review (opt-in, high-stakes only)
1. Run Pattern 1 above, save consensus to file (GLM synthesis)
2. Dispatch same panel with hostile-auditor prompt: "find the specific factual
   error in this consensus, or say NO SPECIFIC ERROR FOUND"
3. Do NOT read meta-reviews into main context
4. Dispatch final synthesis to GLM: prompt_model.py -m glm-5.2:cloud -t file -o final.md
5. Read only final.md into context, report to user

# Pattern 6: 4-Round Deliberation (design/architecture decisions)
1. Round 1: Parallel divergent — N models, same question, independent answers
2. Round 2: Consolidate — dispatch to GLM (not in main context)
3. Round 3: Parallel convergent — same panel, hostile-auditor framing on synthesis
4. Round 4: Final synthesis — dispatch to GLM, read only final.md into context

# Pattern 7: Iterative Plan Refinement — multi-version review
1. Write plan v1 → dispatch broad 3-seat panel → patch → v2
2. Dispatch 1-seat targeted review (did fixes hold?) → patch → v2.1
3. Add new features → v3 → dispatch full panel → converge
4. Stop when: no new issues, or 3 rounds max (see "When to Stop")

# Pattern 8: Advisors as Fixers — apply patches, not just recommend
1. Dispatch fixer model with -t file,terminal
2. Controller verifies patches + runs test suite independently
3. Commit with THESIS/LEARNINGS/REFERENCES

# Pattern 9: Plan → Review → Implement → Quality Review — user's preferred workflow
1. Write plan to file (problem, per-item fixes, order, risks, scope)
2. Dispatch 2-3 seat advisor review (Pattern 1) — verify claims against source
3. Dispatch fixer (Pattern 8) — apply patches, run tests
4. Controller verifies independently, commits
5. Dispatch 2-3 seat quality review (Pattern 1) — find bugs the controller missed
6. Fix any bugs found, add tests, commit, push
```
