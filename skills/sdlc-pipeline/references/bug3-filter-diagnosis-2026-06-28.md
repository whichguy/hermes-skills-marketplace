# BUG3 Filter Diagnosis — 2026-06-28

## Problem

The `_emit_preview()` function in `sdlc_state.py` shows model output previews
(150 chars). When the coder model (qwen3-coder-next) hits its `max_turns` limit,
it emits "⚠️ Reached maximum iterations (8). Requesting summary..." in its
output. This warning text appeared in the orchestrator's progress display,
making it look like the orchestrator itself hit a limit.

## First Fix (Terminator Matching) — Failed

The first fix tried to strip the warning prefix and preserve content on the
same line using terminator matching:

```python
for terminator in ['...  ', '... ', '. ', '— ', ' ']:
    end_idx = after_warning.find(terminator, len('reached maximum iterations'))
    if end_idx >= 0:
        remaining = after_warning[end_idx + len(terminator):].strip()
        if remaining and not remaining.startswith((')', '.', '—')):
            lines[0] = remaining
            break
```

### Residue Problems

| Problem | Input | Residue in Output | Root Cause |
|---------|-------|-------------------|------------|
| P1 | `Reached maximum iterations — stopping` | `"stopping"` | "— " matched but "stopping" is warning residue, not content |
| P2 | `⚠️ Reached maximum iterations (8). Requesting summary...` | `"Requesting summary..."` | ". " matched at "(8). " but remaining text is warning sentence 2 |
| P3 | Same as P2, warning-only | `"Requesting summary..."` | All that remained after stripping sentence 1 |

**Root cause:** The warning has multiple parts:
1. Sentence 1: "Reached maximum iterations (8)."
2. Sentence 2: "Requesting summary..."
3. Then actual content follows

The terminator approach could only strip one part at a time. It couldn't
distinguish warning residue from actual content.

## Second Fix (Drop Entire First Line) — Working

```python
stripped = content.lstrip()
lines = stripped.split('\n')
if lines and 'reached maximum iterations' in lines[0].lower():
    lines = lines[1:]
filtered = '\n'.join(lines)
```

**Tradeoff:** Content on the same line as the warning (e.g., "I created files")
is lost. This is acceptable because:
- The preview is just a 150-char glimpse, not the actual output
- The actual code/files are already written to disk by the coder
- The lost text is a brief summary, not the code itself

**Verification:** 12/12 ad-hoc checks pass, all 8 input variants handled
correctly, no residue, no false positives.

## Test Cases

| Variant | Input | Expected | Result |
|---------|-------|----------|--------|
| V1 | `⚠️ Reached maximum iterations (8). Requesting summary... I created files.` | Warning filtered | ✅ (content lost, acceptable) |
| V2 | `⚠️ Reached maximum iterations\nNow let me show you the code.` | "Now let me show" | ✅ |
| V3 | `Reached maximum iterations — stopping\nHere is the fix.` | "Here is the fix" | ✅ |
| V4 | `Created binary_search.py with two-pointer approach` | Unchanged | ✅ |
| V5 | `""` (empty) | Empty | ✅ |
| V6 | `⚠️ Reached maximum iterations (8). Requesting summary...\n\`\`\`python\n...` | Code preserved | ✅ |
| V7 | `⚠️ Reached maximum iterations. Requesting summary...` | Empty | ✅ |
| V8 | `Reached maximum iterations. I created the file now.` | Warning filtered | ✅ (content lost, acceptable) |

## Lesson

When filtering model-internal noise from output, prefer simple approaches
(drop the entire line) over complex ones (parse and strip). The complex
approach creates residue problems that are harder to debug than the
original issue. The tradeoff (losing content on the same line) is almost
always acceptable for preview text.
