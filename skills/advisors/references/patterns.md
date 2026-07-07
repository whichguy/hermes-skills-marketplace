# Patterns

- See [Quick Reference](quick-reference.md) for one-liner command summaries.
- See [Pitfalls](pitfalls.md) for anti-patterns by category.

<a id="pattern-1"></a>
## Pattern 1: Advisors (Multi-Model Consensus)

Send one prompt to N models in parallel, then synthesize their responses.

### When to Use

| Use it | Don't use it |
|---|---|
| Architecture / design decisions | Simple lookups (one model is fine) |
| Security review or risk analysis | Trivial questions (waste of N× tokens) |
| Trade-off analysis with no clear answer | Code generation (use multi-model-dev-pipeline) |
| High-stakes decisions where a wrong answer is costly | Anything under 1 min of reasoning |

### Default Panel

| Seat | Model | Why |
|---|---|---|
| Reasoner | `deepseek-v4-pro:cloud` | Analytical reasoning, architecture |
| Coder | `kimi-k2.7-code:cloud` | Code-focused lens, implementation issues |
| Third Seat | `minimax-m3:cloud` | Different training lineage, cloud model |

**Synthesizer:** `glm-5.2:cloud` — consistent delivery for long synthesis outputs (see pitfall on consensus model as panel member). Or do it yourself (you're a model).

### Process

#### Step 1 — Frame the question

Write a clear, self-contained prompt. **Identical for all seats.** Include all
context the models need — files, constraints, requirements.

**When reviewing code or plans about code**, prepend this preamble to the
question to prevent false positives (learned 2026-06-28: Kimi reported 3
"bugs" in pipeline.py that were already fixed in the actual code):

```
Before identifying issues, verify each claim against the actual source files.
If a file path is mentioned, read it. If you cannot access the file, mark
any claims about it as UNVERIFIED and skip them. Only report issues you
can confirm from the code you actually read.
```

#### Step 2 — Show the dispatch plan

```
## 🏛️ Advisors Dispatch Plan

**Question:** [one-line summary]

| # | Seat | Model | Toolsets | Est. time |
|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | file, web | ~30s |
| 2 | Coder | kimi-k2.7-code:cloud | file, web | ~30s |
| 3 | Generalist | glm-5.2:cloud | file, web | ~20s |

**Synthesis:** glm-5.2:cloud (or controller)
```

#### Step 3 — Dispatch seats (file-referenced, data stays on disk)

**Preferred: use `dispatch_advisors.py`** — writes the brief to disk, dispatches
seats that read the brief from disk, and synthesizes via GLM reading seat files
from disk. The controller's context never carries the data payload.

```python
import sys
sys.path.insert(0, '/opt/data/skills/autonomous-ai-agents/advisors/scripts')
from dispatch_advisors import AdvisorDispatch

ad = AdvisorDispatch(outdir='/tmp/advisors')
ad.prepare_brief(
    question="Should we use PostgreSQL or MongoDB? ACID required, ~100K rows.",
    context_file="/opt/data/wiki/design.md",  # all context data → disk
    verify_preamble=True,  # for code/plan review — prevents false positives
)
# Pass seats as (model, role) tuples — avoids parse_seats ambiguity
ad.dispatch(seats=[
    ("deepseek-v4-pro:cloud", "Reasoner"),
    ("kimi-k2.7-code:cloud", "Coder"),
])  # 2 seats in parallel, each reads brief.md from disk
```

**Legacy alternative (raw prompt_model.py with inline context):**

For small context (< 2K chars, short sessions) where the file-reference overhead isn't worth it,
you can still pass context inline. But this puts the context data into the
controller's `execute_code` call — it enters the conversation transcript.

```python
# Legacy — only for small context
import subprocess, concurrent.futures, time, sys

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"
OUTDIR = "/tmp/advisors"
seats = [("deepseek-v4-pro:cloud", "seat-1.md"), ("kimi-k2.7-code:cloud", "seat-2.md")]

def dispatch(model, outfile):
    cmd = [sys.executable, SCRIPT, "-m", model,
        "-p", QUESTION, "--context", CONTEXT, "-t", "file,web",
        "-o", f"{OUTDIR}/{outfile}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return model, r.returncode

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(dispatch, m, f) for m, f in seats]
    for fut in concurrent.futures.as_completed(futures):
        model, rc = fut.result()
        print(f"{'✅' if rc == 0 else '❌'} {model}")
```

#### Step 4 — Synthesize (dispatch to GLM, not in main context)

**Do not read the review files into your main context** — that pollutes the
running conversation with 10K+ chars per review. Instead, dispatch the
synthesis to a cloud model via `prompt_model.py`. The model reads the files
from disk and writes the synthesis to a file.

```python
# Preferred: use dispatch_advisors.py
ad.synthesize()  # GLM reads seat files from disk → synthesis.md
synthesis = ad.read_synthesis()  # ~1-2K chars into context — this is fine
print(synthesis)
```

```python
# Legacy: raw prompt_model.py
import subprocess, sys

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"
OUTDIR = "/tmp/advisors"

review_files = " ".join(f"- {OUTDIR}/{fname}" for _, fname, _ in seats)
synthesis_prompt = (
    f"Read these review files and synthesize a consensus: {review_files}. "
    f"The original question was: {QUESTION}. "
    "Produce: agreements, disagreements, final answer, confidence, caveats. "
    "Do NOT split the difference — pick the strongest answer and justify it."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "glm-5.2:cloud",
    "-p", synthesis_prompt,
    "-t", "file",
    "-o", f"{OUTDIR}/synthesis.md"
], timeout=120)
```

**Why GLM for synthesis:** It's a generalist that reads all perspectives
without bias toward any single panel member's view. Do NOT use a panel member
model for synthesis (self-bias — see Pitfalls). The synthesis file is small
(~1-2K chars) — read that into your context to report to the user.

#### Step 5 — Report to user

```
## 🏛️ Advisors Complete — 3/3 seats (43s)

| Seat | Model | Time | Confidence | Position |
|---|---|---|---|---|
| Reasoner | deepseek-v4-pro | 6.7s | high | PostgreSQL |
| Coder | kimi-k2.7-code | 5.9s | high | PostgreSQL |
| Generalist | glm-5.2 | 22.6s | medium | MongoDB |

**Consensus:** PostgreSQL (2/3 high, 1/3 medium)
**Disagreement:** Generalist preferred MongoDB; overruled by ACID requirement.
**Caveats:** All assumed <1M rows; revisit at 10M+.
```

### Adjusting the panel

**Fewer seats** (2 + synthesis = 3 calls): For medium-stakes questions.

**More seats** (4-5): For critical decisions. Beyond 5, diminishing returns.

**Domain-specific:**

| Domain | Panel |
|---|---|
| Code architecture | 2 code models + 1 reasoner |
| Security review | 2 code models + 1 reasoner + 1 generalist |
| Product/business | 2 generalists + 1 reasoner |
| Research | 2 reasoners + 1 generalist |

**No synthesis** (`--no-synthesis` equivalent): Just collect independent
answers. Useful when you want raw perspectives without forced consensus.

<a id="pattern-2"></a>
## Pattern 2: Sequential Review Chain

Each model reviews the previous model's output — each reviewer builds on the
last, catching issues the prior model missed.

### When to Use

| Use it | Don't use it |
|---|---|
| Each model has a different expertise (security → perf → UX) | You want independent perspectives (use Pattern 1) |
| Findings are cumulative — later reviewers need earlier context | You need speed (parallel is faster) |
| You want a single refined answer, not multiple perspectives | You want to compare positions (use Pattern 3) |

**Pattern 2 vs Pattern 1:** Use Pattern 2 (sequential) when each reviewer
needs to see what the previous one found — e.g., a security reviewer finds
issues, then a performance reviewer checks if the fixes hurt throughput,
then a UX reviewer checks the user impact. Use Pattern 1 (parallel) when you
want independent perspectives on the same question without anchoring bias.

```python
# Round 1: DeepSeek writes initial analysis
subprocess.run([sys.executable, SCRIPT, "-m", "deepseek-v4-pro:cloud",
    "-p", "Analyze this architecture for issues",
    "--context", open("design.md").read(),
    "-o", "/tmp/round-1.md"], timeout=120)

# Round 2: Kimi reviews DeepSeek's analysis
subprocess.run([sys.executable, SCRIPT, "-m", "kimi-k2.7-code:cloud",
    "-p", "Review this analysis for missed issues or errors",
    "--context", open("/tmp/round-1.md").read(),
    "-o", "/tmp/round-2.md"], timeout=120)

# Round 3: GLM reviews both
subprocess.run([sys.executable, SCRIPT, "-m", "glm-5.2:cloud",
    "-p", "Review these two analyses and produce a final verdict",
    "--context", open("/tmp/round-1.md").read() + "\n\n" + open("/tmp/round-2.md").read(),
    "-o", "/tmp/round-3.md"], timeout=120)
```

<a id="pattern-3"></a>
## Pattern 3: A/B Comparison

Same prompt, two models, diff the outputs — surface where models agree and
where they diverge.

### When to Use

| Use it | Don't use it |
|---|---|
| You want to see if two models converge on the same answer | You need a synthesis (use Pattern 1) |
| Comparing model quality on a specific task | You need more than 2 perspectives (use Pattern 1) |
| Testing prompt sensitivity across models | The question has a clear right answer (use Pattern 4) |

```bash
python3 prompt_model.py -m deepseek-v4-pro:cloud -p "Design an auth system" -o /tmp/plan-a.md
python3 prompt_model.py -m kimi-k2.7-code:cloud -p "Design an auth system" -o /tmp/plan-b.md
diff /tmp/plan-a.md /tmp/plan-b.md
```

<a id="pattern-4"></a>
## Pattern 4: Single Model Query

Just ask one model something — no panel needed. This is the primitive itself
(see [The Primitive: prompt-model](../SKILL.md#the-primitive-prompt-model)) with no
composition. Use this when one model is enough and you don't need cross-model
consensus:

```bash
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review this function for edge cases" \
    --context "$(cat auth.py)" \
    -t file \
    -o /tmp/review.md
```

<a id="pattern-5"></a>
## Pattern 5: Adversarial Meta-Review (Opt-In Second Round)

Pattern 1 + one additional adversarial round. The same panel that produced
the consensus is asked to find specific flaws in it — not to confirm it.

**This is opt-in.** The basic Pattern 1 (3-4 calls) already captures 80-90% of
the value. This pattern doubles cost and latency for a smaller marginal gain.
Use it only when the decision is irreversible, expensive to reverse, or in a
domain with known LLM blind spots (math, logic, causal inference).

### When to Use

| Use it | Don't use it |
|---|---|
| Irreversible or very expensive decisions (production deploy, contract, publication) | Routine code review, research synthesis, planning |
| Domain with known LLM blind spots (math, logic, temporal reasoning) | Anything Pattern 1 already handles well |
| Pattern 1 has shown inconsistent results on similar questions | Simple lookups, trivial questions |
| Cost of being wrong dwarfs cost of analysis (wrong = $10K, analysis = $0.50) | Time-sensitive decisions (< 60s budget) |

### What Was Cut (YAGNI)

The original proposal included a **local draft step** (run the prompt through a
local model first, then have cloud models review the draft). This was cut
based on DeepSeek's YAGNI/KISS review (2026-06-28):

- **Anchoring bias:** Cloud models seeing the draft fixate on its framing,
  errors, and omissions rather than approaching the question fresh. You're
  constraining 3 expensive cloud models to react to a free local model's output.
- **Unnecessary:** Pattern 1 already gives each model the raw question. The
  draft is a middleman that adds latency and potentially reduces quality.
- **The real information gain is round 1:** Diverse models reviewing
  independently is where genuine new findings appear. Everything after that is
  aggregation and validation.

### Why Adversarial (Not Confirmatory)

Asking "is this consensus correct?" produces confirmation bias — LLMs are
trained to be helpful and will generate plausible-sounding but low-value
affirmations. The adversarial framing forces specificity and gives the model
permission to say "nothing wrong."

### The Hostile Auditor Prompt

The key insight from DeepSeek's review: force the model to find a **specific
factual error** or explicitly say "no error found." This prevents manufactured
critiques that look impressive but add no signal.

```
You are a hostile auditor. Identify the single specific factual claim in this
consensus that is most likely to be incorrect. Quote the exact sentence.
Explain why it's wrong using concrete counterexamples or contradictory evidence.
If you cannot find a specific factual error, say "NO SPECIFIC ERROR FOUND" and
do not generate generic criticism.
```

### Process

Uses the same panel as Pattern 1 (see [Default Panel](#default-panel) above).
The panel is: DeepSeek (Reasoner) + Kimi (Coder) + MiniMax (Third Seat).

#### Step 1 — Run Pattern 1 (round 1 + synthesis)

Follow Pattern 1 Steps 1-4: dispatch the question to 3 models in parallel,
read the output files, and synthesize a consensus. Save the consensus to
`/tmp/advisors/consensus.md`. See Pattern 1 for full dispatch code.

#### Step 2 — Dispatch adversarial meta-review (parallel, same panel)

Send the consensus + each reviewer's own original review back to the same
models. Each gets the hostile auditor prompt.

```python
CONSENSUS = open(f"{OUTDIR}/consensus.md").read()

ADVERSARIAL_PROMPT = (
    "You are a hostile auditor. Identify the single specific factual claim in "
    "this consensus that is most likely to be incorrect. Quote the exact "
    "sentence. Explain why it's wrong using concrete counterexamples or "
    "contradictory evidence. If you cannot find a specific factual error, say "
    "\"NO SPECIFIC ERROR FOUND\" and do not generate generic criticism.\n\n"
    "## Consensus\n" + CONSENSUS
)

def dispatch_meta(model, review_file, meta_file, role):
    own_review = open(f"{OUTDIR}/{review_file}").read()
    # Strip metadata header from their original review
    lines = own_review.split('\n')
    start = 0
    for i, line in enumerate(lines):
        if line.strip() == '-->':
            start = i + 1
            break
    own_review_clean = '\n'.join(lines[start:]).strip()
    # Write context to file to avoid shell escaping issues
    ctx_file = f"{OUTDIR}/ctx-{role}.md"
    with open(ctx_file, 'w') as f:
        f.write(ADVERSARIAL_PROMPT + "\n\n## Your Original Review\n" + own_review_clean)
    cmd = [sys.executable, SCRIPT,
        "-m", model,
        "-p", "Review the consensus below as a hostile auditor. Find the most dangerous factual error, or say NO SPECIFIC ERROR FOUND.",
        "-c", ctx_file,
        "-o", f"{OUTDIR}/{meta_file}"]
    start = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - start
    return role, model, elapsed, r.returncode

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = [pool.submit(dispatch_meta, m, rf, mf, r)
               for m, rf, mf, r in
               [("deepseek-v4-pro:cloud", "seat-1-reasoner.md", "meta-1-reasoner.md", "Reasoner"),
                ("kimi-k2.7-code:cloud", "seat-2-coder.md", "meta-2-coder.md", "Coder"),
                ("minimax-m3:cloud", "seat-3-third.md", "meta-3-third.md", "Third Seat")]]
    for fut in concurrent.futures.as_completed(futures):
        role, model, elapsed, rc = fut.result()
        print(f"{'✅' if rc == 0 else '❌'} {role} meta-review ({model}): {elapsed:.1f}s")
```

#### Step 3 — Read meta-reviews

```python
import os
meta_seats = [
    ("meta-1-reasoner.md", "Reasoner"),
    ("meta-2-coder.md",    "Coder"),
    ("meta-3-third.md",    "Third Seat"),
]
for meta_file, role in meta_seats:
    path = f"{OUTDIR}/{meta_file}"
    if os.path.exists(path):
        print(f"\n{'='*50}")
        print(f"{role} — Meta-Review")
        print(f"{'='*50}")
        print(open(path).read())
```

#### Step 4 — Final Synthesis (dispatch to GLM, not in main context)

This is the key step that makes the adversarial round worthwhile. Dispatch
the final synthesis to GLM — do not read the consensus + meta-reviews into
your main context. GLM reads all files from disk and produces the final answer.

```python
import subprocess, sys

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"
OUTDIR = "/tmp/advisors"

final_prompt = (
    "You are the final synthesizer. Read the consensus and all meta-reviews, "
    f"then produce the final answer. Files:\n"
    f"- {OUTDIR}/consensus.md (the round 1 consensus)\n"
    f"- {OUTDIR}/meta-1-reasoner.md (DeepSeek adversarial meta-review)\n"
    f"- {OUTDIR}/meta-2-coder.md (Kimi adversarial meta-review)\n"
    f"- {OUTDIR}/meta-3-third.md (MiniMax adversarial meta-review)\n\n"
    "Apply this decision tree to each meta-review:\n"
    "- NO SPECIFIC ERROR FOUND → consensus stands, confidence increases\n"
    "- Specific factual error, verifiable → correct the consensus\n"
    "- Specific factual error, but wrong → note and dismiss (false positive)\n"
    "- Generic critique → discard (the prompt said no generic criticism)\n"
    "- Meta-reviewers disagree → note the split, lean toward consensus\n\n"
    "Write: final answer, corrections applied, confidence level, open questions.\n"
    "Do NOT rubber-stamp the consensus — if a meta-review found a real error, "
    "the final answer MUST differ from the consensus on that point."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "glm-5.2:cloud",
    "-p", final_prompt,
    "-t", "file",
    "-o", f"{OUTDIR}/final.md"
], timeout=120)
```

**Critical:** The final synthesis MUST differ from the consensus if any
meta-review found a verified error. If all meta-reviews say "NO SPECIFIC
ERROR FOUND," the final answer matches the consensus with higher confidence.
The value of Pattern 5 is entirely in this step — if you skip it, the
adversarial round was wasted tokens.

Read only `final.md` (small, ~1-2K chars) into your context to report to the user.

#### Step 5 — Report to user

```
## 🏛️ Adversarial Meta-Review Complete — 3/3 seats, 2 rounds

### Round 1 (Independent Review)
| Seat | Model | Time | Position |
|---|---|---|---|
| Reasoner | deepseek-v4-pro | 17.0s | DuckDB |
| Coder | kimi-k2.7-code | 12.3s | DuckDB |
| Third Seat | minimax-m3 | 27.7s | DuckDB |

**Consensus:** DuckDB, unanimous (3/3)

### Round 2 (Adversarial Meta-Review)
| Seat | Finding |
|---|---|
| Reasoner | NO SPECIFIC ERROR FOUND |
| Coder | Flagged: consensus says "both handle 50M rows" — SQLite degrades on aggregates at scale |
| Qwen | NO SPECIFIC ERROR FOUND |

### Final
**DuckDB, high confidence.** Correction applied: SQLite can store 50M rows but
has documented performance degradation on aggregate queries at that scale.
This strengthens the DuckDB recommendation.

### Cost Analysis

| Pattern | Calls | Wall time | Cloud cost | Use case |
|---|---|---|---|---|
| Pattern 1 (basic) | 3-4 | ~30s | 3× | Most decisions |
| Pattern 5 (adversarial) | 6-7 | ~60-90s | 6× | High-stakes, irreversible |

### Design Rationale

Based on DeepSeek V4 Pro review (2026-06-28), incorporating YAGNI and KISS:

1. **No local draft** — anchoring bias outweighs the benefit. Cloud models
   review the raw question, not a weak model's framing of it.
2. **Same panel both rounds** — each reviewer sees consensus + their own
   original review. They can catch synthesis misrepresentation.
3. **Hostile auditor prompt** — forces specific factual claims or "no error
   found." Prevents manufactured critiques that look impressive but add no signal.
4. **Fixed 2 rounds, no loop** — LLMs share training data; Delphi-style
   convergence loops show diminishing returns by round 2. Two adversarial
   rounds > four convergence rounds for LLMs.
5. **GLM does synthesis (Step 4)** — dispatch synthesis to GLM via
   `prompt_model.py`, not in the controller's main context. GLM is a
   generalist, not a panel member, so no self-bias. Reading 10K+ chars of
   reviews into the main context pollutes the running conversation —
   dispatch out and read only the small synthesis file (~1-2K chars) back.
6. **Opt-in, not default** — Pattern 1 is sufficient 90% of the time. This
   pattern is for the 10% where being wrong is expensive.
7. **DeepSeek + Kimi + MiniMax panel** — reasoner + code-focused + third cloud seat.
   MiniMax replaces Qwen as the third seat for a different training lineage
   while staying on cloud (no local-model latency issues in agent loops).

<a id="pattern-6"></a>
## Pattern 6: 4-Round Deliberation (Parallel → Consolidate → Parallel → Final)

The user's preferred rhythm for multi-model review of design/architecture
decisions. Two parallel rounds with a consolidation step in between — divergent
thinking, then convergent thinking.

### When to Use

| Use it | Don't use it |
|---|---|
| Design docs, architecture decisions, plans | Simple yes/no questions |
| Multi-version plans needing independent review per version | Single-version reviews (use Pattern 1) |
| High-stakes decisions where adversarial review adds value | Quick lookups (use Pattern 4) |

### Rhythm

```
Round 1: PARALLEL (divergent)
  N models, same question, independent answers
  → Each model approaches fresh, no anchoring bias

Round 2: CONSOLIDATE
  Synthesize findings: agreements, disagreements, gaps
  → Controller does this (you're a model)

Round 3: PARALLEL (convergent)
  Same panel reviews the synthesis
  → Hostile-auditor framing: "find the specific factual error"
  → Each model sees synthesis + their own original review

Round 4: FINAL SYNTHESIS
  Incorporate corrections from Round 3
  → Produce final answer with confidence level
```

### Why This Beats Sequential Chains

Sequential review chains (A → B → C) have anchoring bias — B fixates on A's
framing, C fixates on B's. The 4-round pattern gives each model an independent
first look (Round 1), then a targeted second look at the synthesis (Round 3).
Two parallel rounds > four sequential rounds for LLM-based review.

### Process

#### Round 1 — Parallel Divergent

Same as Pattern 1 (Advisors). Dispatch N models with the same question.
Each gets the raw question — no draft, no prior answer.

#### Round 2 — Consolidate (dispatch to GLM)

Dispatch the consolidation to GLM — do not read all N responses into your
main context. GLM reads the files from disk and writes the synthesis:

```python
import subprocess, sys

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"
OUTDIR = "/tmp/advisors"

review_files = " ".join(f"- {OUTDIR}/{fname}" for _, fname, _ in seats)
consolidate_prompt = (
    f"Read these review files and synthesize a consensus: {review_files}. "
    "Produce: agreements, disagreements, gaps, preliminary recommendation. "
    "Do NOT split the difference — pick the strongest answer and justify it."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "glm-5.2:cloud",
    "-p", consolidate_prompt,
    "-t", "file",
    "-o", f"{OUTDIR}/consensus.md"
], timeout=120)
```

#### Round 3 — Parallel Convergent

Dispatch the same panel with the hostile-auditor prompt from Pattern 5.
Each model sees the synthesis + their own original review. The prompt:

```
You are a hostile auditor. Identify the single specific factual claim in
this synthesis that is most likely to be incorrect. Quote the exact sentence.
Explain why it's wrong using concrete counterexamples. If you cannot find a
specific factual error, say "NO SPECIFIC ERROR FOUND" and do not generate
generic criticism.
```

#### Round 4 — Final Synthesis (dispatch to GLM)

Same as Pattern 5 Step 4 — dispatch to GLM, not in main context. GLM reads
`consensus.md` + all meta-review files and produces the final answer:

```python
final_prompt = (
    "You are the final synthesizer. Read the consensus and all meta-reviews, "
    f"then produce the final answer. Files:\n"
    f"- {OUTDIR}/consensus.md\n"
    f"- {OUTDIR}/meta-1-reasoner.md\n"
    f"- {OUTDIR}/meta-2-coder.md\n"
    f"- {OUTDIR}/meta-3-qwen.md\n\n"
    "Decision tree: NO ERROR → keep, verified error → correct, "
    "false positive → dismiss, generic → discard.\n"
    "Write: final answer, corrections, confidence, open questions."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "glm-5.2:cloud",
    "-p", final_prompt,
    "-t", "file",
    "-o", f"{OUTDIR}/final.md"
], timeout=120)
```

### Real Run

See `references/real-run-orchestrator-plan-review-2026-06-28.md` for a 3-round
example that approximates this pattern (the user formalized it mid-session).

<a id="pattern-7"></a>
## Pattern 7: Iterative Plan Refinement

Apply Pattern 1 (Advisors) iteratively across multiple plan versions. Each round
narrows scope: broad review → targeted verification → new feature review.

### When to Use

| Use it | Don't use it |
|---|---|
| Design docs evolving through feedback | Single-version reviews (use Pattern 1) |
| Multi-version plans needing independent review per version | Quick yes/no questions (use Pattern 4) |
| v1 has known issues, v2 needs verification before adding features | Stable plans after round 1 (stop — don't over-review) |

### Rhythm: Full → Targeted → Full

```
write plan v1
  → dispatch 3-seat panel (broad review)
  → read reviews, patch plan → v2
  → dispatch 1-seat targeted review (did fixes hold?)
  → read review, patch plan → v2.1
  → add new features → v3
  → dispatch 3-seat panel (review new features)
  → read reviews → converge on recommendation
```

**Round 1 (broad):** Full 3-seat panel for wide coverage. Find all issues.
**Round 2 (targeted):** Single seat (DeepSeek) to verify specific fixes. Cheaper
and faster than re-running the full panel. Only use when the changes are
incremental fixes, not new features.
**Round 3 (features):** Back to full panel for new feature review.

### Split-Recommendation Synthesis

When all seats independently recommend the same structural change (e.g., "split
into serial and parallel phases"), it's a strong signal. Act on it immediately —
don't re-review the recommendation.

| Signal | Action |
|---|---|
| All seats recommend same split | Apply the split immediately |
| 2/3 recommend split, 1/3 disagrees | Read dissenter's reasoning; if weak, apply split |
| 1/3 recommends split | Note it but don't act — not enough consensus |
| Split recommended but details differ | Take the most detailed recommendation as template |

### Real Run

See `references/real-run-orchestrator-plan-review-2026-06-28.md` for a 3-round
example: orchestrator state machine design went from v1 (7 states, undefined
stagnation) to v3-serial (implementation-ready) across 7 advisor calls.

### When to Stop

Over-reviewing is real — each round has diminishing returns. Stop when:

| Signal | Action |
|---|---|
| Round finds no new issues | Stop — the plan is stable |
| Round only finds style/nitpick issues | Stop — substantive review is done |
| 2+ rounds with no structural changes | Stop — you're polishing, not improving |
| Panel unanimously approves | Stop — consensus reached |
| 3 rounds completed | Hard stop — review what's left and decide |

**Rule of thumb:** 2-3 rounds is almost always enough. If you're still finding
major issues in round 3, the problem is the plan's foundation, not the review
depth. Go back to the design, don't add a 4th review round.

<a id="pattern-8"></a>
## Pattern 8: Advisors as Fixers (Apply Patches, Not Just Recommend)

When advisors have `-t file,terminal` toolsets, they can APPLY patches directly
to the codebase — not just recommend changes. This is a hybrid pattern: some
seats fix, some recommend. The controller verifies all patches and runs the full
test suite after.

See `references/advisors-as-fixers-2026-07-05.md` for the full pattern, real-run
example (devloop test-quality improvement), and pitfalls.

<a id="pattern-9"></a>
## Pattern 9: Plan → Review → Implement (User's Preferred Workflow)

When the user asks to "plan it out, get advisor feedback, then implement,"
follow this 3-phase workflow. This is a composition of Pattern 1 (advisors
review) + Pattern 8 (advisors fix) but the user explicitly wants it as a
named, repeatable workflow.

### When to Use

| Use it | Don't use it |
|---|---|
| User says "plan → review → implement" | Trivial one-line fixes |
| Multi-file changes with architectural risk | Single-file edits with no design decisions |
| Changes to a system with known fragility (devloop, gateway, SDLC) | Greenfield features with no existing code to break |
| User wants advisor sign-off before code changes | User says "just fix it" |

### Process

#### Phase 1 — Write the Plan

Write a concrete, actionable plan to a file. Include:
- Problem statement (what's broken, why now)
- Per-item plan with exact file paths and line references
- Implementation order with rationale
- Concerns and risks for each item
- What the plan does NOT address (scope boundary)

Save to `/tmp/advisors/<name>-plan.md`.

#### Phase 2 — Advisor Review (Pattern 1)

1. Write a review prompt that asks advisors to verify claims against actual source code
2. Show the dispatch plan table (seats, models, toolsets, est. time)
3. Dispatch 2-3 seats in parallel via `terminal(background=true, notify_on_complete=true)`
4. When both land, dispatch GLM synthesis via `subprocess.run()` (foreground, not background)
5. Read only the synthesis file into context, report to user

**Critical:** The review prompt MUST include: "Before identifying issues, verify
each claim against the actual source files. If a file path is mentioned, read it."

#### Phase 3 — Implement (Pattern 8)

1. Dispatch the strongest code-focused model (Kimi) as a fixer with `-t file,terminal`
2. The fixer reads the plan + advisor feedback, applies patches, runs tests
3. Controller verifies: check git diff is real, run full test suite independently
4. If tests pass, commit with THESIS/LEARNINGS/REFERENCES
5. Report: what was fixed, commit SHA, test count

### Real Run

See `references/plan-review-implement-devloop-2026-07-05.md` for a real example:
devloop learnings system (N1/N2/N3 plan), 2-seat advisor review (DeepSeek + Kimi),
GLM synthesis dispatched.

#### Phase 4 — Quality Review (Post-Implementation)

After implementation is committed, dispatch a 2-3 seat advisor panel to
quality-review the changes. This is Pattern 1 applied to a specific commit.
The advisors read the diff, verify claims against source code, and flag bugs
the controller missed.

**When to use:**

| Use it | Don't use it |
|---|---|
| Multi-file changes with architectural risk | Trivial one-line fixes |
| Changes to a system with known fragility | Single-file edits with no design decisions |
| User explicitly asks for quality review | User says "done, move on" |

**Process:**
1. Dispatch 2-3 seats in parallel with `-t file,terminal` to review the commit
2. When both land, dispatch GLM synthesis via `subprocess.run()` (foreground)
3. Read only the synthesis file into context, report to user
4. If bugs found: fix them, add tests, commit, push
5. If clean: report "no bugs found, can ship"

**Real example (2026-07-05):** After implementing N1+N2+N3 (commit `4da32ee`),
a 2-seat quality review (DeepSeek + Kimi, GLM synthesis) found one real bug:
`AVOID:` double-prefix at `dispatch.py:451/490`. Fixed in commit `f511f95`
(448 tests, +1 new test). Without this phase, the bug would have shipped.

### Pitfalls

- **Don't skip Phase 2.** The user explicitly wants advisor review before
  implementation. Even if the plan looks obvious, dispatch the review.
- **Don't skip Phase 4 for non-trivial changes.** The quality review found a
  real bug (AVOID: double-prefix) that both the controller and the
  implementation-phase advisors missed. A 2-seat quality review costs ~4
  minutes and catches bugs that would otherwise ship.
- **Verify patches independently.** The fixer model may claim "all tests pass"
  but the controller must run the suite itself. Advisors can hallucinate success.
- **Use foreground subprocess.run() for synthesis, not background terminal().**
  The synthesis model reads files from disk and writes a result — this is a
  single-turn operation that takes 30-90s. Background + polling wastes tool calls.
