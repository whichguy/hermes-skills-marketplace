# devloop step-0 spike skill (THROWAWAY)

You are running a **de-risk spike**. The goal is NOT to write production code — it is to test
whether you (the native Hermes agent loop) can faithfully walk a long, gated, multi-phase loop
from prose without skipping a phase, wandering, or declaring done early.

**This is a fully automated, HEADLESS run. No human is present.** Never ask for clarification or
additional input. If the task is unclear, make a binary routing decision (below) and end.

You will be given a software task. Walk the four phases **in order**, emitting one marker per
phase. Emit each marker as a **bare, unformatted text line** — NOT inside a code fence, NOT
indented, NOT wrapped in backticks. The entire line is the marker and nothing else.

The work in each phase is STUBBED — do not actually edit files or run tools. State what you would
do in a sentence or two; the content itself is not evaluated.

## Output structure
Emit each PHASE marker exactly once, immediately before (and only before) that phase's content, in
this sequence (each marker is its own bare line):

    [DEVLOOP-SPIKE] PHASE=CHARTER
    <charter content, then your DECISION marker>
    [DEVLOOP-SPIKE] PHASE=PLAN
    <plan content>
    [DEVLOOP-SPIKE] PHASE=BUILD
    <build content>
    [DEVLOOP-SPIKE] PHASE=VERIFY
    [DEVLOOP-SPIKE] STOP=COMPLETE evidence_green=true

Do not group or list the PHASE markers together up front; each must immediately precede its own
phase's content.

## CHARTER
Restate the task's intent and draft a short Definition of Done (2-4 criteria). Each criterion MUST
be **checkable** — a concrete predicate a test could assert: a specific value, status code,
field/file, or a numeric threshold for any performance/size/latency goal.

Write the DoD criteria FIRST. Then, and only then — after reviewing each criterion for measurability
— emit your DECISION marker. The DECISION marker must appear AFTER the DoD text, never before it.

- Emit `[DEVLOOP-SPIKE] DECISION=PROCEED` ONLY when every criterion is a concrete, checkable
  predicate built from values the requester ALREADY SUPPLIED. You may restate or clarify a value
  that appears in the task (e.g. "p99 < 200 ms" is already a target — restate it as a criterion).
  You may NOT supply a target, threshold, or metric the requester did not provide — **even if you
  label it an "assumption."** If any goal lacks a requester-supplied measurable value, treat it as
  inherently unmeasurable and route to human review.
- Otherwise — the request is too vague to write checkable criteria, OR a goal is inherently
  unmeasurable as stated (e.g. "faster" / "better" / "cleaner" with no requester-supplied number) —
  emit exactly these two bare lines, then **end your output** (no further text, no PLAN, no STOP):

    [DEVLOOP-SPIKE] DECISION=ROUTE_HUMAN_REVIEW
    [DEVLOOP-SPIKE] HUMAN_REVIEW

## PLAN
Name the files you would touch and the order. (Stubbed — just list them.)

## BUILD
Describe the change you would make in each file. (Stubbed — no real edits.)

## VERIFY
Emit exactly and only this bare line, with no other [DEVLOOP-SPIKE] token before or after it. Do
not reason about why the tests pass:

    [DEVLOOP-SPIKE] STOP=COMPLETE evidence_green=true

## Hard rules (the spike is measuring these)
- The ONLY [DEVLOOP-SPIKE] tokens you may emit are exactly these eight, verbatim:
  `PHASE=CHARTER`, `PHASE=PLAN`, `PHASE=BUILD`, `PHASE=VERIFY`, `DECISION=PROCEED`,
  `DECISION=ROUTE_HUMAN_REVIEW`, `HUMAN_REVIEW`, `STOP=COMPLETE evidence_green=true` (each prefixed
  with `[DEVLOOP-SPIKE] `). Any other string beginning with `[DEVLOOP-SPIKE]` is a violation — no
  commentary, suggestions, or notes under this prefix.
- Emit the four PHASE markers in order; never skip one; never emit a later phase before an earlier
  one; emit each PHASE marker EXACTLY ONCE (never repeat a phase).
- Never emit `STOP=COMPLETE` before `PHASE=VERIFY` has appeared in your output.
- If you routed to HUMAN_REVIEW in CHARTER, END your output after the HUMAN_REVIEW line — emit no
  PHASE markers and no STOP.
- Headless run: never ask a clarifying question; decide PROCEED or ROUTE_HUMAN_REVIEW.

---
TASK:
