# Learnings Review Pattern — 2026-07-05

A variant of Pattern 1 (Advisors) where the question is "review these observations
against the skill that governs this class of work." Used to extract durable lessons
from a session's failures and successes, then have advisors review those observations
against the relevant skill for actionable feedback.

## When to Use

After a session where:
- A skill was used and hit issues not covered by its pitfalls
- Multiple rounds of a tool/engine failed in the same way
- You discovered a new technique, fix, or workaround
- The user asked "what did we learn?" or "any key learnings?"

This catches:
- Observations that contradict the skill's documented approach
- Missing pitfalls the skill should warn about
- Patterns the skill should recommend
- Overlaps with other skills

## Process

### Step 1 — Write observations to a file

Capture the raw observations — what happened, what failed, what worked,
what surprised you. Be specific: include exact error messages, round counts,
file paths, and what you tried. This is the "primary source" the advisors
will review.

```bash
cat > /tmp/learnings-<topic>.md << 'EOF'
# Learnings: <topic>

## What happened
...

## What failed
...

## What worked
...

## Surprises
...

## Files to review
- /path/to/skill/SKILL.md
- /path/to/skill/references/*.md
EOF
```

### Step 2 — Dispatch advisors against the skill

Use the default 3-seat panel (DeepSeek + Kimi + Qwen). Each advisor reads the
observations file AND the skill files, then recommends changes. Use
`terminal(background=true, notify_on_complete=true)` for long reviews (>4 min).

```bash
# Per-seat dispatch
python3 prompt_model.py -m deepseek-v4-pro:cloud \
    -p "Review these observations against the skill. Read /tmp/learnings-review.md
        and all files it references. Recommend: what to add to SKILL.md (pitfalls,
        patterns, triggers), what reference files to create, what's already covered.
        Be specific — quote exact sections from both files." \
    -c /tmp/learnings-review.md -t file --timeout 600 \
    -o /tmp/learnings-1-reasoner.md
```

### Step 3 — Synthesize (dispatch to GLM, not in main context)

Same as Pattern 1 Step 4 — dispatch synthesis to GLM. Do NOT read all review
files into your main context.

```python
synthesis_prompt = (
    "Read these advisor reviews of session learnings and produce a consensus: "
    "/tmp/learnings-1-reasoner.md "
    "/tmp/learnings-2-coder.md "
    "/tmp/learnings-3-local.md. "
    "Produce: agreements, disagreements, priority ranking, risks, and "
    "recommended action plan for updating the skill."
)

subprocess.run([sys.executable, SCRIPT,
    "-m", "glm-5.2:cloud",
    "-p", synthesis_prompt,
    "-t", "file",
    "-o", "/tmp/learnings-synthesis.md"
], timeout=120, cwd="/opt/data/skills/productivity/ask/scripts")
```

### Step 4 — Apply findings

Read the synthesis and update the skill:
1. Add new pitfalls for issues the skill didn't cover
2. Add new references for session-specific detail
3. Patch incorrect guidance
4. Add new patterns to the skill's SKILL.md

## Real Run

See the `calendar-quick-add` devloop session (2026-07-05):
- 5 devloop rounds, all blocked on test rendering (designer ignored ANSWERS)
- Observations written to `/tmp/advisors-devloop/learnings-review.md`
- 3-seat panel dispatched: DeepSeek (272s, 12.5KB), Kimi (74s, 11.9KB), Qwen (336s, 12.7KB)
- GLM synthesis: 138s, 10.4KB consensus with P0-P5 action plan
- Resulted in: 4 new pitfalls added to devloop SKILL.md, consensus reference file created,
  `_lit()` datetime bug documented, broken DI branches flagged as landmines
