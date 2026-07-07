# Advisors as Fixers — Pattern 8 (2026-07-05)

A new pattern emerged during the devloop test-quality improvement session:
advisors that not only review but also APPLY patches to the codebase.

## The Pattern

```
1. Controller writes a comprehensive briefing document (context + source files)
2. Dispatch 3-seat panel in parallel with -t file,terminal toolsets
3. Each seat reviews the briefing AND can apply patches directly
4. Controller reads completed seats, verifies patches, runs tests
5. Controller synthesizes and applies remaining improvements
```

## When to Use

| Use it | Don't use it |
|--------|-------------|
| Codebase improvements where the fix is mechanical | Pure analysis/recommendation tasks |
| Multiple independent fixes that don't conflict | Single-file changes (just do it yourself) |
| Advisors have file+terminal toolsets | Advisors are read-only (no -t flag) |

## Real Run: devloop Test Quality (2026-07-05)

3-seat panel (DeepSeek, Kimi, Minimax) reviewed the full devloop codebase
and produced complementary improvements:

| Seat | Model | Applied Patches? | Contribution |
|------|-------|:---:|-------------|
| Kimi | kimi-k2.7-code:cloud | ✅ Yes | Created `test_quality_lint.py` + 8 tests + loop wiring + designer prompt |
| DeepSeek | deepseek-v4-pro:cloud | ❌ No | Recommended 9 render output regression tests (controller applied) |
| Minimax | minimax-m3:cloud | ❌ No | Recommended judge_reason text extension (controller applied) |

**Key insight:** Kimi was the only seat with `-t file,terminal` toolsets that
actually applied patches. The other two seats produced recommendations that the
controller applied. This is a hybrid pattern — some seats fix, some recommend.

## Pitfalls

### Advisors may apply patches that break tests

Kimi's patches created `test_quality_lint.py` and modified `loop.py`, but the
test file expected a different API than what existed. The controller had to
fix 3 test assertions after the fact. Always run the full test suite after
advisor-applied patches.

### Advisors may not know about uncommitted changes

Kimi's quality gate was added to `loop.py` as an uncommitted change. The
devloop validation run used the committed version (from git HEAD), which
didn't have the gate. Always commit advisor patches before validating.

### Advisors need file+terminal toolsets to apply patches

Without `-t file,terminal`, advisors can only recommend changes. The controller
must apply them. This is fine for most patterns — the controller should verify
before applying anyway.

## Controller Verification Checklist (MANDATORY after fixer patches)

Fixers are self-reporting — a fixer that claims "445 passed" may have run
a different command or missed a test. The controller MUST verify independently:

1. **Check patches landed:** `git diff --stat` to confirm files were modified
2. **Read the actual diffs:** `git diff <file>` for each changed file — verify
   the fix matches what was requested, not just that something changed
3. **Run the full test suite:** `pytest tests/ -x -q` (or equivalent) — do NOT
   trust the fixer's self-reported test count
4. **Run the specific new tests:** `pytest tests/ -k "new_test_name" -v` to
   confirm the new tests actually exercise the fix
5. **Commit with THESIS/LEARNINGS/REFERENCES:** Include what was fixed, which
   advisor found it, and the test progression (N → M tests)
6. **Push:** `git push origin main`

### Real Run: devloop P9+P1a+P1b+P6+dedup (2026-07-05)

Kimi (kimi-k2.7-code:cloud) applied 5 fixes identified by the advisor panel
(DeepSeek + Kimi review round). Controller verification:

| Step | Result |
|------|--------|
| `git diff --stat` | 3 files, +171/-1 lines |
| `git diff project.py` | P9 fix: direct runner path synthesizes rich fields via `devloop_bridge._build_rich_commit_message` |
| `git diff devloop_bridge.py` | P6: two-journal documentation block |
| `git diff tests/test_project.py` | P1a, P1b, dedup test — 3 new tests |
| `pytest tests/ -x -q` | 445 passed (was 442) |
| `pytest tests/test_project.py -k "rich_lesson or dedup" -v` | 3/3 new tests pass |
| Commit | `4d0c6f1` — THESIS/LEARNINGS/REFERENCES |
| Push | `main → main` on GitHub |

**Key insight:** The fixer reported "445 passed in 21.22s" but used `uv run
--with pytest python3 -m pytest`. The controller ran `uv run --with pytest
python3 -m pytest` independently and got 445 passed in 31.43s — same count,
different timing (expected variance). Always run the suite yourself.

## Synthesis

After all seats complete:
1. Read each seat's output file
2. Verify any patches they applied using the checklist above
3. Apply remaining recommendations yourself
4. Run full test suite
5. Commit with THESIS/LEARNINGS/REFERENCES

## Batch by Effort Level (2026-07-06 refinement)

When the improvement plan has fixes at multiple effort levels (S/M/L), batch
all same-effort items in a single pass. Jim's instruction "Batch all S-effort
fixes" is a recurring pattern — it minimizes context-switching and verification
overhead.

**Workflow:**
1. Read all source files needed for the batch in parallel (one turn)
2. Apply all patches in sequence (one turn per file, or batch if independent)
3. Run the full test suite once at the end (not after each fix)
4. Commit all fixes as a single commit with THESIS/LEARNINGS/REFERENCES

**Real run (2026-07-06):** 7 S-effort fixes applied in one pass — 2×P0, 5×P1.
All source files read in parallel first, patches applied sequentially, mock
tests (11/11) and sync dry-run verified at the end. Single commit `c5d0235`.

**When NOT to batch:**
- Fixes that depend on each other (apply in dependency order)
- Fixes that touch the same function (risk of merge conflicts)
- M/L-effort items that need design review between each
