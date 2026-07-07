# Rich Journaling Advisor Review — 2026-07-05

3-seat panel (DeepSeek V4 Pro, Kimi K2.7 Code, MiniMax M3) + GLM-5.2 synthesis.
Full reviews at `/tmp/advisors-learnings/seat-*.md`, synthesis at `synthesis.md`.

## Consensus (all 3 seats agree)

### P0 — Critical

1. **Project outer loop never writes rich fields** — `project.py:268-272` calls `state.append_learning` with only the mechanical `lesson` field. No `learnings_text`, `references`, or `failure_conditions`. The project loop's rich-field reading code at `project.py:226-249` is dead code in production.

2. **Mechanical fallback drops the journal** — `dispatch.py:435` calls `_mechanical_learnings_fallback` with only `raw_commits`, silently dropping the `learnings_journal` (including all failure conditions).

### P1 — Important

3. **Failure-condition extraction over-captures** — broad keywords (`"rejected"`, `"failed"`, `"wrong"`, `"never"`) promote positive observations into AVOID: patterns. Should require explicit `AVOID:` prefix.

4. **Double-doubling of AVOID: lines** — the project fold emits the same AVOID: line twice (once from `learnings_text`, once from `failure_conditions` array).

5. **Status metrics leak into `lesson` field** — rebuilds count and file counts are telemetry, not educational content.

6. **"Latest wins" is prompt-only** — the mechanical fallback has no dedup, no supersession, no chronological ordering.

### P2 — Nice to have

7. Add `ts` field to bridge journal entries
8. Add dedup hint to consolidator prompt
9. Fix stale filename: `git_learnings.txt` → `git_learnings_consolidated.txt`
10. Show `failure_conditions` in `_render_report`
11. Coordinate truncation caps (200/300/500/1000/2000)
12. Centralize `_WRITE_SAFE` / `_WRITE_SAFE_ROOT` path constant
13. Add test coverage for project-loop entry shape

## Confidence

**HIGH** in findings (all 3 seats independently verified against source).
**MODERATE** in implementation — bridge path works, project outer-loop path is structurally broken.

## Bottom Line

The design is right, the propagation is broken. The bridge path (single-run devloop) correctly journals rich design content, but the project outer loop never writes rich fields — making its rich-field reading code dead code. The mechanical fallback also drops the journal entirely.

## Source Files Reviewed

- `devloop_bridge.py` — `_append_run_learning`, `_extract_commit_section`, `_extract_failure_conditions`, `_build_rich_commit_message`
- `dispatch.py` — `_git_history_learnings`, consolidator prompt, journal reader
- `project.py` — `_default_lesson`, lessons folding
- `test_bridge.py` — 11 new tests
