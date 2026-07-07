# Quality Review Round 3 — Advisors Skill v3.4 (2026-07-05)

## Context

After fixing 10 bugs from the v3.4 self-review (rounds 1-2), a 2-seat quality
review was dispatched to verify the final state before committing. The review
was interrupted twice by gateway restarts, requiring 3 dispatch attempts.

## Dispatch Attempts

| Attempt | Method | Result |
|---|---|---|
| 1 | `terminal(background=true)` via `dispatch_advisors.py` | Killed by gateway restart — no seat output |
| 2 | Same, re-dispatched | Killed by gateway restart — no seat output |
| 3 | Same, re-dispatched | Both seats completed (DeepSeek 289.7s, Kimi 110.8s) |

**Key learning:** The brief file (114KB, 3 source files) survived all restarts
on disk. Re-dispatch was a single command — no need to re-write the brief.

## Panel

| Seat | Model | Elapsed | Output | Verdict |
|---|---|---|---|---|
| Reasoner | deepseek-v4-pro:cloud | 289.7s | 6.2K chars | Non-blocking — 3 doc bugs + 6 test gaps |
| Coder | kimi-k2.7-code:cloud | 110.8s | 5.5K chars | **Block commit** — 1 HIGH crash bug |
| Synthesis | glm-5.2:cloud | 27.5s | 5.7K chars | Agreed with Coder — crash bug blocks |

## Bugs Found (8 total)

### Blocking (3)

| # | Bug | Fix |
|---|---|---|
| 1 | `subprocess.TimeoutExpired` crashes entire panel | `try/except` in `dispatch_seat()` → returns failed tuple |
| 2 | `seats=[]` → `ThreadPoolExecutor(max_workers=0)` crash | Explicit `ValueError("No seats to dispatch")` guard |
| 3 | SKILL.md stale 5K threshold + synthesizer contradiction | Updated to decision table reference; `deepseek` → `glm-5.2:cloud` |

### Non-blocking (5)

| # | Fix |
|---|---|
| 4 | `as_completed()` defensive timeout (`timeout + 30`) |
| 5 | Role name sanitization (`/`, `\`, `:`, `..` → `-`/`_`) |
| 6 | `cli_synthesize` brief existence check |
| 7 | `parse_seats("  ,  ")` → returns defaults (post-parse empty check) |
| 8 | Removed unused `patch` import; fixed "3 seats" → "2 seats" comment |

## Tests

- 43/43 passing after fixes (was 41, +2 new: whitespace-only parse_seats, empty seats guard)
- Lint clean

## Learnings Captured in SKILL.md

1. **Gateway restarts kill the dispatch process, not seat subprocesses** — updated pitfall
2. **CLI uses subcommands** — `--brief` is not a top-level flag
3. **parse_seats whitespace-only** — post-parse empty check needed
4. **Test count** — updated from 41 → 43 in two locations
