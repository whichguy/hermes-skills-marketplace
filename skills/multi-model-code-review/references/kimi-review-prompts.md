# Kimi Review Prompt Templates

Effective prompt patterns for Kimi code reviews, refined across multiple sessions.

## Round 1: Initial Review (broad)

```
Review the code changes in <file>. Run `git diff` to see what changed.
Focus on:
1. Correctness — does the logic work as intended?
2. Edge cases — what breaks with empty input, long input, concurrent calls?
3. Security — any injection risks, path traversal, unsafe deserialization?
4. Backward compatibility — does this break existing callers?
5. Architectural fit — is this the right layer for this fix?

For each finding, classify as:
- BLOCKING: must fix before deploy
- SHOULD FIX: important but not blocking
- NICE TO HAVE: improvement, not urgent

Read the full file (not just the diff) to understand context.
```

## Round 2: Re-Review (confirmation + edge cases)

```
Re-review the code after fixes were applied. Verify:
1. Are all Round 1 BLOCKING issues fully resolved?
2. Are all Round 1 SHOULD FIX issues fully resolved?
3. Did any fix introduce new issues?
4. Are there edge cases the fixes missed?

Classify findings same as Round 1. Be specific about what changed.
```

## Round 3: Final Sign-off

```
Final review. The code has been through 2 rounds of review + fixes.
Your job: give a PRODUCTION-READY or NOT READY verdict.
If NOT READY, list exactly what must change.
If PRODUCTION-READY, confirm:
- All prior findings resolved
- No regressions
- No new issues introduced
```

## Architectural-Layer Check (include in every review)

```
Check: is this fix at the right architectural layer?
- Hook-layer workaround for a gateway-level problem → SHOULD FIX (move upstream)
- Config workaround for a code bug → SHOULD FIX (fix the code)
- Adapter-level fix for a platform-agnostic issue → SHOULD FIX (move to base class)
```

## Pitfalls

- Don't ask Kimi to "run tests" — it may try to use `execute_code` which is blocked in subagents. Say "use terminal() to run pytest".
- Don't ask Kimi to "fix the code" in the same review pass — keep review read-only, apply fixes separately.
- Always include the file path and `git diff` instruction so Kimi can see exactly what changed.
