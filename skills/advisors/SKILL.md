---
name: advisors
description: >
  Prompt any Hermes model via `hermes chat -q` and write the output to a file.
  Single primitive (prompt-model) that composes into larger patterns:
  multi-model consensus (advisors), iterative refinement, A/B comparison,
  sequential review chains. Each call is a full Hermes agent with tools,
  skills, and multi-turn reasoning. No delegate_task, no gateway-restart risk.
version: 3.2.0
author: agent
metadata:
  hermes:
    tags: [multi-model, consensus, ensemble, reasoning, parallel, primitive]
    related_skills: [multi-model-dev-pipeline, multi-model-code-review, subagent-driven-development]
    config:
    - key: advisors.enabled
      description: Enable the advisors skill
      default: true
      prompt: Enable advisors skill?
    category: autonomous-ai-agents
---

# Advisors — Prompt Any Model, Compose Patterns

## Overview

One primitive — **prompt-model** — prompts a Hermes model via `hermes chat -q`
and writes the output to a file. Each call is a full agent with tools, skills,
and multi-turn reasoning. The controller (you) orchestrates this primitive into
whatever pattern the task needs.

```
prompt-model:  prompt + model → file on disk

advisors:     N× prompt-model in parallel → read files → synthesize
adversarial:  advisors + hostile-auditor meta-review round (opt-in, high-stakes)
deliberation: parallel → consolidate → parallel adversarial → final synthesis
iterative:    advisors applied across plan versions (broad → targeted → features)
review-chain: prompt-model A → read → prompt-model B → read → prompt-model C
A/B:          same prompt, two models → diff the output files
```

**Why this architecture:** `delegate_task` cannot select different models per
subagent — all inherit `delegation.model` from config.yaml. Running `hermes
chat -q` as a subprocess gives per-call model selection. Each call is a full
agent (like Claude Code's spawned agents). Output goes to a file you can read,
diff, archive, or feed into the next call.

## The Primitive: prompt-model

### Location

```
/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py
```

### Usage

```bash
# Basic — output to stdout
python3 prompt_model.py -m deepseek-v4-pro:cloud -p "What is ACID compliance?"

# Write to file
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review this architecture" \
    --context "$(cat design.md)" \
    -o /tmp/seat-1.md

# With tools and skills
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -p "Find security issues in auth.py" \
    -t file,web,terminal \
    -s github-code-review \
    -o /tmp/review-kimi.md

# Pipe context via stdin
cat design.md | python3 prompt_model.py -m glm-5.2:cloud \
    -p "Review this design" -o /tmp/review-glm.md
```

### Arguments

| Flag | Required | Description |
|---|---|---|
| `-m` / `--model` | Yes | Model name (e.g., `deepseek-v4-pro:cloud`) |
| `-p` / `--prompt` | Yes | The prompt text |
| `--context` | No | Context appended after prompt |
| `-c` / `--context-file` | No | Read context from file (overrides `--context`) |
| `-o` / `--output` | No | Output file path (default: stdout) |
| `-t` / `--toolsets` | No | Comma-separated toolsets (e.g., `file,web,terminal`) |
| `-s` / `--skills` | No | Comma-separated skills to preload |
| `--provider` | No | Provider name (default: `ollama-glm`) |
| `--max-turns` | No | Max agent turns (default: Hermes config `agent.max_turns`) |
| `--timeout` | No | Timeout in seconds (default: 300) |
| `--english-only` | No | Force English output (auto-added for known non-English models) |

### Output

- **With `-o`:** Response written to file. Progress printed to stderr:
  `✅ deepseek-v4-pro:cloud → /tmp/seat-1.md (6.7s, 2341 chars)`
- **Without `-o`:** Response printed to stdout.
- **Exit codes:** 0 = success, 1 = error, 2 = timeout.

### Non-English models

The script auto-appends "respond in English only" for known non-English models
(`glm-5.2:cloud`, `glm-5.2`). Use `--english-only` to force it for other models.

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
| Local Lens | `qwen3.6:35b-a3b` | Local 35B MoE, different training lineage, zero API cost |

**Synthesizer:** `deepseek-v4-pro:cloud` — or do it yourself (you're a model).

### Process

#### Step 1 — Frame the question

Write a clear, self-contained prompt. **Identical for all seats.** Include all
context the models need — files, constraints, requirements.

#### Step 2 — Show the dispatch plan

```
## 🏛️ Advisors Dispatch Plan

**Question:** [one-line summary]

| # | Seat | Model | Toolsets | Est. time |
|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | file, web | ~30s |
| 2 | Coder | kimi-k2.7-code:cloud | file, web | ~30s |
| 3 | Generalist | glm-5.2:cloud | file, web | ~20s |

**Synthesis:** deepseek-v4-pro:cloud (or controller)
```

#### Step 3 — Dispatch parallel prompt-model calls

Use `execute_code` with `concurrent.futures` to run N calls in parallel:

```python
import subprocess, concurrent.futures, time, sys, os

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"
OUTDIR = "/tmp/advisors"
os.makedirs(OUTDIR, exist_ok=True)

seats = [
    ("deepseek-v4-pro:cloud", "seat-1-reasoner.md", "Reasoner"),
    ("kimi-k2.7-code:cloud", "seat-2-coder.md", "Coder"),
    ("qwen3.6:35b-a3b", "seat-3-local.md", "Local Lens"),
]

QUESTION = "Should we use PostgreSQL or MongoDB? ACID required, ~100K rows."
CONTEXT = open("/opt/data/wiki/design.md").read()
TOOLSETS = "file,web"

def dispatch(model, outfile, role):
    cmd = [sys.executable, SCRIPT,
        "-m", model, "-p", QUESTION,
        "--context", CONTEXT,
        "-t", TOOLSETS,
        "-o", f"{OUTDIR}/{outfile}"]
    start = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - start
    return role, model, elapsed, r.returncode, r.stderr.strip()

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = [pool.submit(dispatch, m, f, r) for m, f, r in seats]
    for fut in concurrent.futures.as_completed(futures):
        role, model, elapsed, rc, err = fut.result()
        print(f"{'✅' if rc == 0 else '❌'} {role} ({model}): {elapsed:.1f}s")
```

#### Step 4 — Read the output files and synthesize

**You are the synthesizer.** Read all N output files and reason about them
directly — find agreements, disagreements, pick the strongest answer. This is
better than coding synthesis in Python because you can apply judgment.

```python
import os
for _, fname, role in seats:
    path = f"/tmp/advisors/{fname}"
    if os.path.exists(path):
        print(f"\n{'='*50}")
        print(f"{role}")
        print(f"{'='*50}")
        print(open(path).read()[:500])
```

Or dispatch one more `prompt-model` call with all responses for a structured
synthesis:

```python
responses = []
for _, fname, role in seats:
    path = f"/tmp/advisors/{fname}"
    if os.path.exists(path):
        responses.append(f"### {role}\n{open(path).read()}")

synthesis_prompt = (
    "You are a consensus synthesizer. Review these advisor responses and produce "
    "a final answer.\n\n"
    f"QUESTION: {QUESTION}\n\n"
    + "\n\n".join(responses) +
    "\n\nSynthesize: agreements, disagreements, final answer, confidence, caveats. "
    "Do NOT split the difference — pick the strongest answer and justify it."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "deepseek-v4-pro:cloud",
    "-p", synthesis_prompt,
    "-o", "/tmp/advisors/synthesis.md"
], timeout=120)
```

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

## Pattern 4: Single Model Query

Just ask one model something — no panel needed. This is the primitive itself
(see [The Primitive: prompt-model](#the-primitive-prompt-model) above) with no
composition. Use this when one model is enough and you don't need cross-model
consensus:

```bash
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review this function for edge cases" \
    --context "$(cat auth.py)" \
    -t file \
    -o /tmp/review.md
```

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
The panel is: DeepSeek (Reasoner) + Kimi (Coder) + Qwen (Local Lens).

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
                ("qwen3.6:35b-a3b", "seat-3-qwen.md", "meta-3-qwen.md", "Qwen")]]
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
    ("meta-3-qwen.md",     "Qwen"),
]
for meta_file, role in meta_seats:
    path = f"{OUTDIR}/{meta_file}"
    if os.path.exists(path):
        print(f"\n{'='*50}")
        print(f"{role} — Meta-Review")
        print(f"{'='*50}")
        print(open(path).read())
```

#### Step 4 — Final Synthesis (incorporate adversarial findings)

This is the key step that makes the adversarial round worthwhile. Read the
consensus + all meta-reviews and produce the final answer.

**You are the final synthesizer.** Apply this decision tree to each meta-review:

| Meta-review finding | Action | Confidence impact |
|---|---|---|
| "NO SPECIFIC ERROR FOUND" | Consensus stands as-is | ↑ increases confidence |
| Specific factual error flagged, verifiable | **Correct the consensus** — quote the error, cite the correction | ↑ if corrected cleanly, ↓ if correction is debatable |
| Specific factual error flagged, but wrong | Note the flag, explain why it's not actually an error, keep consensus | → neutral (false positive) |
| Generic critique ("could be more comprehensive") | **Discard** — the prompt said no generic criticism | → neutral (noise) |
| Meta-reviewers disagree on whether an error exists | Note the split. Lean toward consensus unless the flagged error is concrete and verifiable. | ↓ slightly (signals uncertainty) |

Write the final synthesis to `/tmp/advisors/final.md`:

```python
# After reading all meta-reviews, write final synthesis
final = """## Final Answer

[Your recommendation, incorporating corrections from the adversarial round]

### Round 1 Consensus
[Summary of the 3-model consensus from round 1]

### Round 2 Adversarial Findings
[For each seat: what they flagged or NO SPECIFIC ERROR FOUND]

### Corrections Applied
[List any corrections made based on verified factual errors]

### Confidence
[High / Medium / Low — and why, based on the adversarial round]

### Open Questions
[Remaining unknowns after both rounds]
"""
with open(f"{OUTDIR}/final.md", 'w') as f:
    f.write(final)
```

**Critical:** Do not just rubber-stamp the consensus. If a meta-review flags a
real error, the final answer MUST differ from the consensus on that point. If
all meta-reviews say "NO SPECIFIC ERROR FOUND," the final answer matches the
consensus with higher confidence. The value of Pattern 5 is entirely in this
step — if you skip it, the adversarial round was wasted tokens.

#### Step 5 — Report to user

```
## 🏛️ Adversarial Meta-Review Complete — 3/3 seats, 2 rounds

### Round 1 (Independent Review)
| Seat | Model | Time | Position |
|---|---|---|---|
| Reasoner | deepseek-v4-pro | 17.0s | DuckDB |
| Coder | kimi-k2.7-code | 12.3s | DuckDB |
| Qwen | qwen3.6:35b-a3b | 27.7s | DuckDB |

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
5. **Controller does final synthesis (Step 4)** — the orchestrating model reads
   meta-reviews, applies the decision tree, and produces the final answer. No
   4th model needed (avoids the "consensus model as panel member" bias pitfall).
   This step is mandatory — skipping it wastes the adversarial round.
6. **Opt-in, not default** — Pattern 1 is sufficient 90% of the time. This
   pattern is for the 10% where being wrong is expensive.
7. **DeepSeek + Kimi + Qwen panel** — reasoner + code-focused + local lens.
   Qwen replaces GLM as the third seat for a different training lineage and
   zero API cost.

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

#### Round 2 — Consolidate

You (the controller) read all N responses and synthesize:
- Agreements (all models agree)
- Disagreements (models differ — note which and why)
- Gaps (something no model addressed)
- Preliminary recommendation

Write the synthesis to a file for Round 3.

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

#### Round 4 — Final Synthesis

Apply the decision tree from Pattern 5 Step 4:
- "NO ERROR" → consensus stands, confidence ↑
- Verified error → correct it
- False positive → dismiss
- Generic critique → discard

### Real Run

See `references/real-run-orchestrator-plan-review-2026-06-28.md` for a 3-round
example that approximates this pattern (the user formalized it mid-session).

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

## Pitfalls

### Config deference: do not override Hermes config defaults

The `--max-turns` flag defaults to `None` in `prompt_model.py`, which means
Hermes config `agent.max_turns` (currently 120) is the source of truth. Do
NOT hardcode `--max-turns` in advisor dispatches unless the user explicitly
requests a specific value. The same applies to `--timeout` — only override
when there's a domain-specific reason (e.g., `execute_code` 5-min cap).

This is the same principle as the `ask` skill's config-deference rule: skills
should NOT impose their own limits when Hermes already has a config key for it.

### Non-English models (glm-5.2:cloud)

The script auto-appends "respond in English only" for known non-English models.
To add a new one, add it to `NON_ENGLISH_MODELS` in `prompt_model.py`.

### Seat timeout

Default 300s per call. If a seat exceeds it, the subprocess is killed and
returns exit code 2. Proceed with completed seats — a 2-seat result is useful.

### Model unavailable

If a model is down, `hermes chat` returns an error. The script writes the error
to stderr and exits with code 1. Check the file exists before reading.

### Token limits

The default `--max-turns` is `None`, which means Hermes config `agent.max_turns`
is the source of truth (currently 120). Do not override `--max-turns` in
advisor dispatches unless the user explicitly requests a specific value.
The Hermes config already sets a sensible limit — hardcoding a lower value
in the advisors skill silently caps every call.

### Concurrent subprocess limits

Each call spawns a `hermes chat` process. With 5 parallel seats, that's 5
processes. Watch system resources on constrained hardware.

### execute_code interruption kills all subprocesses

When the advisors dispatch runs inside `execute_code` with `concurrent.futures`,
a user interruption (Ctrl+C, "Operation interrupted") kills the entire
`execute_code` process — including all in-flight `prompt_model.py` subprocesses.
Only seats that already completed survive; any mid-flight seat is lost.

**Symptoms:** You see "Operation interrupted" in the output, and only 1-2 of
3+ seats have output files. The remaining seats never wrote their files.

**Recovery:**
1. Read the output files that DID complete — partial results are still useful
2. Re-dispatch only the missing seats (not the full panel)
3. For the re-dispatch, use individual `terminal()` calls instead of
   `execute_code` with `concurrent.futures` — individual calls survive
   interruption better because each is a separate tool invocation

**Prevention:** For high-stakes panels where losing seats is costly, dispatch
each seat as a separate `terminal(background=true)` call with
`notify_on_complete=true`. This is slower (sequential tool calls) but each
seat is independently tracked and survives interruption. Reserve
`execute_code` + `concurrent.futures` for panels where partial results are
acceptable.

### execute_code has a 5-minute hard timeout — use terminal(background=true) for long dispatches

`execute_code` has a 5-minute (300s) hard timeout. A 15-turn advisor agent reviewing
multiple source files and writing an updated plan can take 3-8 minutes — well within
the `--timeout 600` you'd set on `prompt_model.py`, but exceeding `execute_code`'s cap.
The subprocess is killed mid-review and the output file is never written.

**Symptoms:** `execute_code` returns with a timeout error after exactly 5 minutes.
The advisor's output file doesn't exist or is empty. The advisor was mid-turn when killed.

**Fix:** Use `terminal(background=true, timeout=600, notify_on_complete=true)` instead
of `execute_code` for any advisor dispatch expected to take >4 minutes:

```python
# BEFORE (fails for long reviews):
execute_code(code=f"""
import subprocess, sys
subprocess.run([sys.executable, SCRIPT, "-m", "deepseek-v4-pro:cloud",
    "-p", "Review the plan...", "-t", "file,terminal",
    "--timeout", "600",
    "-o", "/tmp/review.md"], timeout=600)
""")

# AFTER (works for any duration):
terminal(
    command='python3 /opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py '
            '-m deepseek-v4-pro:cloud '
            '-p "Review the plan at /path/to/plan.md against source files. '
            'Update the plan with any fixes found." '
            '-t file,terminal --timeout 600 '
            '-o /tmp/review.md',
    background=True,
    notify_on_complete=True,
    timeout=600
)
```

**Threshold:** Use `terminal(background=true)` for any advisor dispatch with
`--timeout >= 300`. For quick dispatches (`--timeout <= 120`),
`execute_code` is fine. The `--max-turns` threshold no longer applies
because we don't override it — Hermes config is the source of truth.

### Local models may time out in agent loops

Local models (qwen3.6:35b-a3b, qwen3-coder-next:q4_K_M) are fast for single
inference but slow for multi-turn agent loops. Each tool call adds 0.5-3s of
model latency. A 5-turn agent loop on a local model can take 2-5 minutes vs
30-60s on cloud models. For time-sensitive panels, skip the local seat
entirely rather than overriding `--max-turns`. If the user explicitly requests
a lower turn limit for a local seat, pass `--max-turns` only for that seat.

### Stale imports when shared constants are removed from model_utils.py

`prompt_model.py` imports constants from `model_utils.py` (e.g., `DEFAULT_MAX_TURNS`).
When those constants are removed from `model_utils.py` during a config-deference
cleanup (replacing hardcoded defaults with `None` to let Hermes config win),
`prompt_model.py` breaks with `ImportError: cannot import name 'DEFAULT_MAX_TURNS'`.
This is the same class of bug that affected `ask.py` — any consumer of
`model_utils.py` that imports shared constants is vulnerable.

**Symptoms:** `prompt_model.py` exits immediately with code 1 before the agent
loop starts. The error is in the import block, not in agent reasoning. All
seats fail with the same error in under 1 second.

**Recovery:**
1. Remove the stale import from `prompt_model.py`
2. Change the argparse default from the removed constant to `None`
3. Update the help text to say "Hermes config agent.max_turns" instead of the old constant name
4. Verify: `python3 -c "import py_compile; py_compile.compile('prompt_model.py', doraise=True)"`
5. Verify downstream consumers still import correctly: `from model_utils import dispatch_single`

**Prevention:** After removing any constant from `model_utils.py`, grep all
consumers:
```bash
grep -rn "DEFAULT_MAX_TURNS\|OLD_CONSTANT_NAME" /opt/data/skills/
```
This includes `prompt_model.py`, `ask.py`, `pipeline.py`, `sdlc.py`, and any
other script that imports from `model_utils.py`. The `ask` skill's "Default
Changes Must Audit All Entry Points" pitfall covers the same pattern.

### prompt_model.py must run from ask/scripts/ directory

`prompt_model.py` imports from `model_utils.py` which lives in
`/opt/data/skills/productivity/ask/scripts/`. The script's `sys.path` setup
adds that directory, but only relative to the script's own location. When
called from a different working directory via `subprocess.run()`, the import
may fail if `sys.path` resolution doesn't find `model_utils.py`.

**Symptoms:** `ImportError: cannot import name 'dispatch_single' from
'model_utils'` or similar. The subprocess exits with code 1 immediately.

**Fix:** Always set `cwd` to the ask scripts directory when calling
`prompt_model.py`:

```python
ASK_SCRIPTS_DIR = "/opt/data/skills/productivity/ask/scripts"
subprocess.run(cmd, cwd=ASK_SCRIPTS_DIR, ...)
```

Or add both possible paths to `sys.path` in the dispatch function:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/opt/data/skills/productivity/ask/scripts")
```

The `execute_code` dispatch pattern in this skill already includes the
`cwd=ASK_SCRIPTS_DIR` fix. Use it as the template.

### Backticks and special characters in prompts break shell commands

When the prompt contains backticks (`` ` ``), dollar signs (`$`), or other
shell-special characters, the shell interprets them before `prompt_model.py`
ever sees the argument. Backticks trigger command substitution, consuming
subsequent arguments and causing cryptic errors like:

```
prompt_model.py: error: the following arguments are required: -p/--prompt
```

This happens because the backtick-substituted text ate the `-p` flag. The
subprocess exits with code 2 before Python even starts.

**Symptoms:** Exit code 2, "the following arguments are required" error,
immediate failure (0s elapsed). The command looks correct but the shell
mangled it.

**Fix:** Always use `--context-file` (`-c`) for prompts containing backticks,
code blocks, shell commands, or any special characters:

```bash
# BEFORE (fails — backticks trigger shell command substitution):
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -p "Run: cd /path && uv run pytest tests/ -v -k 'not live' 2>&1 | tail -20"

# AFTER (safe — prompt goes through a file, not the shell):
echo "Run: cd /path && uv run pytest tests/ -v -k 'not live' 2>&1 | tail -20" > /tmp/prompt.txt
python3 prompt_model.py -m kimi-k2.7-code:cloud \
    -c /tmp/prompt.txt -o /tmp/result.md
```

**Rule of thumb:** If the prompt contains backticks, `$()`, `&&`, `|`, `>`,
`<`, or `;`, use `--context-file`. The only safe characters for inline `-p`
are alphanumerics, spaces, and basic punctuation.

### Argument list too long (OSError: Errno 7)

When passing large context via `--context` on the command line, the OS may
reject the argument list if it exceeds `ARG_MAX` (typically 128KB-2MB on
Linux). This manifests as `OSError: [Errno 7] Argument list too long`.

**Symptoms:** The subprocess.run() call fails immediately with OSError before
the Python script even starts. The error message includes the full command
path.

**Fix:** Use `--context-file` instead of `--context` for large context:

```python
# BEFORE (fails with large context):
subprocess.run([sys.executable, SCRIPT, "-m", model, "-p", prompt,
    "--context", large_context_string, ...])

# AFTER (works regardless of size):
import tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
    f.write(large_context_string)
    ctx_path = f.name
subprocess.run([sys.executable, SCRIPT, "-m", model, "-p", prompt,
    "-c", ctx_path, ...])
```

Or for the simplest case, just let the model read files from disk — pass a
short prompt that says "read the plan at /path/to/plan.md" and give the model
`-t file` toolsets. The model reads the file itself rather than receiving it
as context. This is the preferred approach for very large context (100K+ chars).

**Threshold:** ~100KB of context is the danger zone. Below 50KB, `--context`
is fine. Between 50-100KB, test it. Above 100KB, always use `--context-file`
or file-reading approach.

### Gateway restarts are safe

Subprocesses are independent of the gateway process. A gateway restart during
a run does NOT affect running calls. This is the key advantage over
`delegate_task`.

### Session ID goes to stderr in quiet mode

When `hermes chat -q` runs in quiet mode, the session ID is printed to
**stderr**, not stdout. If you're capturing output with `subprocess.run` and
only reading `stdout`, you'll miss the session ID. Always capture both:

```python
r = subprocess.run(cmd, capture_output=True, text=True)
# Session ID is in r.stderr, not r.stdout
```

This matters for the `ask` skill's session memory feature — it reads the
session ID from stderr to enable conversational follow-up queries.

### Consensus model as a panel member

If the synthesis model also answered independently, it's biased toward its own
answer. Use a different model for synthesis, or note the self-bias.

### File-reading review tasks need `-t file,terminal`

When dispatching an advisor to review source code and update a plan file
in-place (the SDLC plan review pattern), the advisor needs `-t file,terminal`
toolsets. Without file access, the advisor can only read context passed via
`--context` or `--context-file`, which may hit the OS argument size limit for
large codebases. With `-t file,terminal`, the advisor reads source files from
disk and writes the updated plan back — no context-size limit.

```bash
# Plan review pattern: advisor reads source + writes updated plan
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review the plan at /path/to/plan.md against source files in /path/to/src/.
         Update the plan with any fixes found." \
    -t file,terminal \
    --timeout 600 \
    -o /tmp/review-output.md
```

This pattern was used for all 4 review passes in the SDLC plan design session
(2026-06-28). The advisor reads 3+ source files (model_utils.py 897 lines,
sdlc.py 1317 lines, pipeline.py) plus the plan itself, then writes the updated
plan back to disk. Without `-t file`, the context would need to be passed via
`--context-file` which is fragile for multi-file reviews.

## What Changed (v2 → v3)

| Dimension | v2 (advisors.py) | v3 (prompt_model.py + pattern) |
|---|---|---|
| Script | 414-line monolith | 150-line primitive |
| Synthesis | Coded in Python | Controller does it (it's a model) |
| Output | JSON (ephemeral) | Files (inspectable, diffable, archivable) |
| Patterns | Council only | 7 patterns documented |
| Composability | No | Yes — primitive + controller orchestration |

## Consumers

### ask
`ask` (`skills/productivity/ask/`) is the interactive wrapper — the user says
"ask deepseek What is ACID?" and gets an inline reply with a model badge. It
uses `hermes chat -q` directly (same mechanism as `prompt_model.py`) but adds
alias resolution, session memory, comparison mode, and conversational UX. Use
`ask` for interactive use; use `prompt_model.py` for programmatic orchestration.

### sdlc.py council_review()
`sdlc.py` (`skills/productivity/ask/scripts/sdlc.py`) uses the advisors pattern
for its `council_review()` phase. It dispatches the same review prompt to 3
models in parallel (DeepSeek + Kimi + GLM, all thinking=high) via
`dispatch_single()`, then merges their responses with per-seat headers. The
`COUNCIL_PANEL` constant defines the 3-seat panel. This replaced the old
single-model (DeepSeek-only) council in P11 (Jun 2026).

### dev
`dev` (`skills/software-development/dev/`) wraps `prompt_model.py` with role
aliases (planner → GLM, coder → Qwen, qa-tester → Qwen, code-debugger → Kimi)
and a pipeline mode. It's the primary consumer of this primitive for software
development work. Use `dev` when you need role-based development; use
`prompt_model.py` directly when you need custom model selection or patterns
not covered by `dev`.

### multi-model-dev-pipeline

> ⚠️ **DEPRECATED — do not use for new work.**
> That skill uses `delegate_task` with `model=` (which doesn't work — all
> subagents inherit `delegation.model` from config.yaml). This skill uses
> `prompt_model.py` instead, which actually selects different models per call.
>
> **Migration:** Use `dev.py pipeline` for full dev pipelines, or compose
> `prompt_model.py` calls manually for custom workflows. The stage prompts
> and model rationale in `multi-model-dev-pipeline/references/` are still
> useful reference material.

## Quick Reference

```
# Primitive
python3 prompt_model.py -m <model> -p <prompt> [--context ...] -o <file>

# Pattern 1: Advisors (3 parallel + synthesis) — most decisions
1. Show dispatch plan
2. Dispatch N prompt-model calls in parallel (execute_code + concurrent.futures)
3. Read output files
4. Synthesize yourself OR dispatch one more prompt-model with all responses
5. Report: agreements, disagreements, final answer, caveats

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
1. Run Pattern 1 above, save consensus to file
2. Dispatch same panel with hostile-auditor prompt: "find the specific factual
   error in this consensus, or say NO SPECIFIC ERROR FOUND"
3. Read meta-reviews
4. Final synthesis: apply decision tree (NO ERROR → keep, verified error → correct,
   false positive → dismiss, generic → discard). Write final.md. MUST differ
   from consensus if real errors found.
5. Report both rounds: round 1 positions + round 2 findings + corrections + confidence

# Pattern 6: 4-Round Deliberation (design/architecture decisions)
1. Round 1: Parallel divergent — N models, same question, independent answers
2. Round 2: Consolidate — synthesize agreements, disagreements, gaps
3. Round 3: Parallel convergent — same panel, hostile-auditor framing on synthesis
4. Round 4: Final synthesis — incorporate corrections, produce final answer

# Pattern 7: Iterative Plan Refinement — multi-version review
1. Write plan v1 → dispatch broad 3-seat panel → patch → v2
2. Dispatch 1-seat targeted review (did fixes hold?) → patch → v2.1
3. Add new features → v3 → dispatch full panel → converge
4. Stop when: no new issues, or 3 rounds max (see "When to Stop")
```

## References

- `scripts/prompt_model.py` — The primitive
- `references/` — Real-run logs (historical, from council v1 and advisors v2)
- `references/real-run-v6-state-machine-design-2026-06-28.md` — **Pattern 7 in action:** 3-round iterative plan refinement for the v6 SDLC state machine (45-iteration scaling). 7 advisor calls across 3 rounds (broad → targeted → features). Key learnings: split recommendation is a strong signal, targeted verification saves cost, integrate don't build standalone, 45 iterations changes everything.
- `references/adversarial-self-review-2026-06-28.md` — Live test: Pattern 5 reviewing the skill that defines Pattern 5. Validates the adversarial round catches real controller synthesis errors.