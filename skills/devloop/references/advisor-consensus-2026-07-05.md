# Advisor Consensus — Devloop Test Rendering Fixes (2026-07-05)

5-advisor review (DeepSeek×2, Kimi×2, Qwen×1) of the 4-file patch set
(dispatch.py, render.py, loop.py, runner.py) applied during the
calendar-quick-add build session. Synthesis by GLM-5.2.

## Universal Agreement (all 5 advisors)

1. **Root cause is correct:** test DESIGN is the bottleneck, not implementation.
   The charter/decomposition phase works well.
2. **ANSWERS plumbing** (runner.py + dispatch.py): CORRECT, should land.
3. **DI/call_args prompt guidance** (dispatch.py): CORRECT, should land.
4. **Loop.py verdicts to redesign:** CORRECT, safe.
5. **Raw escape hatch is the right strategy** for complex patterns (DI, datetime,
   call_args). Structured mode can't cleanly express these.

## Disputed

### Dispute 1: Comma join — `"".join` vs `", ".join`
- Kimi: Claims `"".join(parts)` is WRONG — breaks existing tests.
- DeepSeek: Claims `"".join` is CORRECT — parts elements already contain leading
  commas.
- **Verdict:** DeepSeek is right. Verified in render.py:91-98. `parts[0] =
  mock.patch("m.now"`, `parts[1] = , return_value=42`, `parts[2] = ) as _m0`.
  `", ".join` would produce double commas. 9 passing tests confirm.

### Dispute 2: render.py DI branches
- Qwen: Claims both branches WORK and should be promoted.
- DeepSeek: Claims both branches are BROKEN dead code.
- Kimi: Claims render.py is fine, all tests pass.
- **Verdict:** DeepSeek is right. Both branches produce invalid Python. The 9
  tests pass because NO test exercises either branch. They are landmines.

### Dispute 3: Normal mock path assert_called_with/assert_call_arg support
- DeepSeek: Claims normal path is INCOMPLETE.
- **Verdict:** DeepSeek was wrong. Lines 165-179 DO handle both. The normal
  mock path IS complete.

### Dispute 4: Structured dep_inject vs raw mode
- Qwen: Promote dep_inject as preferred.
- DeepSeek + Kimi: Raw mode is cleaner; structured DI extensions are broken.
- **Verdict:** DeepSeek + Kimi are right. dep_inject branch is broken (never
  patches), so promoting it would steer the designer toward a non-functional path.

## Priority Action Plan

| Priority | Item | Severity |
|----------|------|----------|
| P0 | Remove broken DI branches from render.py | HIGH — landmines |
| P1 | Fix `_lit()` for datetime/date types | MEDIUM-HIGH — string comparison bug |
| P2 | Verify judge_verdicts shape in dod_oracle.py | MEDIUM — redesign may be blind |
| P3 | Add regression test for ANSWERS plumbing | LOW-MEDIUM |
| P4 | Update misleading loop.py comment | LOW |
| P5 | Move user_answers from closure to charter dict | LOW-MEDIUM |

## Risks That Remain

| Risk | Severity | Source |
|------|----------|--------|
| dep_inject/inject_as_callable branches produce invalid Python if triggered | HIGH | DeepSeek; confirmed by code read |
| _lit() datetime→string comparison | MEDIUM-HIGH | Qwen, DeepSeek |
| Judge verdicts may lack judge_a/judge_b text → redesign still blind | MEDIUM | Kimi |
| Closure-based user_answers fragile to refactoring | LOW-MEDIUM | DeepSeek |
| Prompt over-use of raw mode for simple cases | LOW | DeepSeek, Kimi |
| No regression test for ANSWERS plumbing | LOW-MEDIUM | Kimi |
| Misleading loop.py comment | LOW | Qwen |
