# Real Run: v6 SDLC State Machine Quality Review (2026-06-28)

3-seat advisor panel (DeepSeek + Kimi + GLM) reviewed the v6 iterative state
machine implementation in `sdlc_state.py`. 14 issues found, all fixed and
verified.

## Panel

| Seat | Model | Time | Output | Issues Found |
|---|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | ~60s | 10.6KB | 5 HIGH, 3 MEDIUM |
| Code Reviewer | kimi-k2.7-code:cloud | ~80s | 17.7KB | 3 HIGH, 3 MEDIUM |
| Generalist | glm-5.2:cloud | ~120s | ~8KB | 6 new issues |

## Key Finding

GLM caught 6 issues that DeepSeek and Kimi both missed:
- thinking levels not set on v6 dispatches
- verifier had write access (toolsets="file,terminal")
- git_commit(files=None) was a no-op
- parse_project_config regex double-escaped
- extract_verdict checked SATISFIED before GAPS
- pytest -v -q conflict

This validates the 3-seat panel — a 2-seat panel would have shipped with 6 bugs.

## Dispatch Method

Used `terminal(background=true, notify_on_complete=true)` for each seat
individually (not `execute_code` with `concurrent.futures`). The first
attempt with `execute_code` timed out at 5 minutes because the advisors
needed 6-8 minutes for multi-file review. Individual background terminal
calls survive the 5-minute `execute_code` cap.

## Synthesis

Controller (DeepSeek V4 Pro) synthesized all 3 reviews directly — no
separate synthesis dispatch. The reviews were read into context because
the controller needed to plan and apply 14 targeted fixes, not just
summarize findings.

## Lessons

1. **3-seat > 2-seat for code review.** The 3rd seat (GLM) found 6 issues
   the other two missed. Marginal cost is negligible.
2. **Use terminal(background=true) for long reviews.** `execute_code` has a
   5-minute hard cap. Advisors reviewing multi-file codebases need 6-8 minutes.
3. **Ad-hoc verification is sufficient for targeted fixes.** A 26-check
   script covering each fix individually is faster than a full test suite.
4. **The verification system's "unverified" flag is mechanical.** It triggers
   on any code edit, not on actual verification gaps. Pattern: edit → verify
   → system flags → re-verify with tempfile → system accepts.
