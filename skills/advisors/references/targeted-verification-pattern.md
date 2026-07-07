# Targeted Verification Pattern

## When to Use

After an advisor panel reviews a plan and identifies concerns, dispatch a single
code-focused model (Kimi) to verify those specific concerns against live source
code. This is cheaper and faster than re-running the full panel, and it catches
false positives before they become implementation bugs.

| Use it | Don't use it |
|---|---|
| Plan has been reviewed, specific concerns identified | Plan hasn't been reviewed yet (use Pattern 1 first) |
| Concerns are code-level (line references, call sites, dedup logic) | Concerns are architectural (use full panel) |
| You need verification before implementing | The concerns are trivial (just fix them) |

## Process

### Step 1 — Frame the verification prompt

List the specific concerns as numbered items. For each, state what the plan
claims and what to verify. Request a structured output format:

```
Verify these 3 specific concerns against the ACTUAL source files:

1. SECOND StreamConsumerConfig CALL SITE: The plan only mentions passing flags
   at run.py:17527. But there may be a second call site around run.py:16194.
   Read gateway/run.py around lines 16140-16220 and 17460-17560 to find ALL
   StreamConsumerConfig construction sites.

2. _last_sent_text DEDUP BUG: In _send_or_edit() (stream_consumer.py:1571),
   there's a check: 'if text == self._last_sent_text: return True'. In unified
   mode, _send_or_edit() replaces the incoming text with _build_unified_content()
   at the top. But _last_sent_text is set from the OLD text at line 1663.
   Determine: does the dedup check compare PRE-unified or POST-unified text?

3. ALL progress_queue.put() SITES: Find EVERY site in run.py where
   progress_queue.put() is called. List each with line number. Determine which
   need the unified branch and which are internal markers.

For each finding, state: CONFIRMED (the issue exists), FALSE POSITIVE (the plan
is correct), or NEW ISSUE (something the plan missed). Read the actual files —
do not guess.
```

### Step 2 — Dispatch with file+terminal access

The model needs to read the plan file AND the source files. Use `-t file,terminal`:

```bash
python3 /opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py \
  -m kimi-k2.7-code:cloud \
  -p "Verify these 3 specific concerns against the ACTUAL source files..." \
  -t file,terminal \
  --timeout 300 \
  -o /tmp/advisors/<task>/kimi-verification.md
```

**Why Kimi:** Code-focused model, good at tracing call sites and dedup logic.
DeepSeek is better for architectural reasoning; Kimi is better for code-level
verification.

### Step 3 — Read findings and patch the plan

The output will have a structured format:

| Concern | Verdict |
|---|---|
| Second StreamConsumerConfig site | CONFIRMED — update both 16120 and 17412 |
| _last_sent_text dedup bug | FALSE POSITIVE — plan's top-level replacement is safe |
| All progress_queue.put sites | NEW ISSUE — 7 sites, blanket branch insufficient |

For each CONFIRMED or NEW ISSUE finding, patch the plan with the corrected
details. For FALSE POSITIVE findings, add a verification note to the plan
confirming the concern was checked and is safe.

### Step 4 — Report to user

Summarize the findings in a table, note what changed in the plan, and offer
next steps (implement, re-review, or route to Kanban).

## Why This Pattern

- **Cheaper than re-running the full panel** — one model call vs. 3-4
- **Faster** — 60-90s vs. 3-5 minutes for a full panel
- **Catches false positives** — advisors reason from context you provide; they
  don't have live access to the codebase. A finding that sounds plausible may
  be contradicted by code the advisor couldn't see.
- **Structured output** — CONFIRMED / FALSE POSITIVE / NEW ISSUE format makes
  it easy to act on findings without re-reading a long narrative review.

## Real Run

**Session:** 2026-07-06 — unified in-progress message feature plan review

1. Plan written at `/opt/data/projects/unified-messaging/implementation-plan.md`
2. Advisor panel (DeepSeek + Kimi) reviewed the plan → recommended direct implementation
3. User asked Kimi to verify 3 specific concerns against live source
4. Kimi dispatched with `-t file,terminal`, read plan + source files
5. Findings: 1 CONFIRMED (second call site), 1 FALSE POSITIVE (dedup safe), 1 NEW ISSUE (7 put sites, blanket branch insufficient)
6. Plan patched with all 3 findings
7. Gateway restart killed first dispatch → re-dispatched (recovery pattern from SKILL.md)

**Key takeaway:** The targeted verification found a real issue (second
StreamConsumerConfig call site) that the full advisor panel missed, and
confirmed a concern was a false positive (dedup bug). Without this step,
the implementation would have been broken on the proxy code path.
