# DeepSeek Architectural Review Technique

## When to Use

After a significant code change (new feature, refactor, pipeline addition), dispatch
DeepSeek in agent mode with deep reasoning to walk through the full code logic. It
catches architectural issues that code-level reviewers (Kimi, Qwen-coder) miss.

## Command

```bash
python3 ask.py deepseek --prompt "Walk through the code logic of <component>. Focus on:
1. How the orchestration flow works end-to-end
2. Session lifecycle (create, resume, cleanup)
3. Error handling and recovery paths
4. Race conditions in parallel dispatch
5. Resource cleanup (temp files, sessions, workdirs)
6. Any dead code or unreachable paths" \
  --thinking xhigh --max-turns 90 --timeout 600 --mode agent \
  --toolsets file,terminal
```

## What DeepSeek Finds vs. Kimi

| DeepSeek (architectural) | Kimi (code-level) |
|---|---|
| Race conditions in parallel dispatch | Missing imports, type errors |
| Dead code (defined but never called) | Incorrect variable names |
| Missing cleanup (stale sessions, temp files) | Logic errors in conditionals |
| Progress/feedback not wired through layers | Missing error handling |
| Dangerous defaults (silent pass on error) | Style issues, docstring gaps |
| Config stomping in concurrent paths | Test assertion correctness |

## Real Example (Jun 2026)

DeepSeek reviewed the SDLC pipeline (`sdlc.py` + `pipeline.py` + `model_utils.py`)
and found 9 bugs. 6 were real and actionable:

| Bug | Severity | Type | DeepSeek caught? | Kimi would catch? |
|---|---|---|---|---|
| council_review() reasoning_effort race | HIGH | Race condition | ✅ | ❌ |
| _cleanup_sdlc_sessions() never called | MEDIUM | Dead code | ✅ | ❌ |
| progress_callback not wired through pipeline.py | MEDIUM | Missing wiring | ✅ | ❌ |
| Evaluator exceptions → silent proceed | MEDIUM | Dangerous default | ✅ | Maybe |
| os.rmdir() fails on __pycache__ dirs | LOW | Edge case | ✅ | Maybe |
| retried flag set on intermediate result | LOW | Logic error | ✅ | ✅ |
| SESSIONS_FILE read-modify-write race | MEDIUM | Race condition | ✅ | ❌ |
| thinking level leaks when original_effort empty | LOW | Edge case | ✅ | ❌ |
| _CODE_KEYWORDS fragile | LOW | Design smell | ✅ | ❌ |

**Key insight:** Kimi (code-level reviewer) would have caught 1-2 of these. DeepSeek
caught all 9. The architectural perspective is essential for multi-file, multi-phase
systems.

## Pitfalls

- DeepSeek needs `--max-turns 90` for thorough review — default 30 is too short
- The review takes 5-10 minutes — dispatch in background or plan for the wait
- Some findings are false positives — always verify line references before fixing
- DeepSeek may suggest fixes that are correct in principle but wrong in detail —
  verify the actual code before applying
