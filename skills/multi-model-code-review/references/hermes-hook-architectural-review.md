# Architectural Review Checklist — Hermes Gateway Hooks

Checklist for reviewing monkey-patched gateway hooks (like `suggestion-stripper/handler.py`).
Covers the five dimensions that most commonly hide bugs in this class of code.

## 1. Regex Code-Span Protection

When a hook uses regex to protect code spans (inline backticks, fenced blocks) from
false-positive marker matching, verify these edge cases:

| Edge case | Pattern to test | Expected |
|-----------|----------------|----------|
| Simple inline | `` `SUGGESTION:{...}` `` | Protected (marker hidden) |
| Nested backticks | `` `` `SUGGESTION:` `` `` | **Common failure** — inner backtick terminates span early |
| Empty inline span | ``` `` SUGGESTION: `` ``` | `[^`]+` requires ≥1 char; empty spans unprotected |
| Unclosed fence to EOF | ```` ```\nSUGGESTION:\n```` (no closing fence) | **Common failure** — `[\s\S]*?` needs closing delimiter |
| Alternate fence syntax | `~~~\nSUGGESTION:\n~~~` | Tilde fences not matched by backtick-only regex |
| Back-to-back spans | `` `a``b` `` | Should parse as two separate spans |

**Remediation pattern:** Use a stateful parser or at minimum add `~~~` support and
an EOF-anchored fallback for unclosed fences. For empty inline spans, use `[^`]*`
instead of `[^`]+`.

## 2. Flag Lifecycle

For any per-turn boolean guard (e.g., `_suggestion_buttons_sent`):

- [ ] **Reset point:** Is the flag cleared at the start of every turn? Verify the
  turn-boundary detection (`_hermes_turn_began` pattern) fires before any
  `finalize=True` path.
- [ ] **Set point:** Is the flag set only when the guarded action actually executes?
  Not on extraction, not on detection — only on dispatch.
- [ ] **Guard check:** Does every path that could re-enter check the flag before
  acting? (Multiple `finalize=True` calls from the stream consumer are common.)
- [ ] **Stale-flag risk:** If the consumer object is reused across turns without
  clearing `_hermes_turn_began`, the flag stays stale. Add a warning log if the
  turn-began guard is already `True` when a new turn boundary is expected.

## 3. Platform Detection

- [ ] **Enum source:** Verify the `Platform` enum is imported from the canonical
  location (`gateway.config`), not a stale copy.
- [ ] **Attribute path:** Confirm `self.adapter.platform` is set in
  `BasePlatformAdapter.__init__` and matches the enum values used in comparisons.
- [ ] **String vs enum:** Ensure comparisons use `==` against enum members, not
  string literals (e.g., `_Platform.SLACK`, not `"slack"`).
- [ ] **Fallback behavior:** What happens on unrecognized platforms? The code
  should degrade gracefully (skip button rendering) rather than crash.

## 4. Async Safety of Mutable State

For closure-captured mutable dicts (e.g., `_suggestion_prompts`):

- [ ] **Single-loop assumption:** Is all access confined to one asyncio event loop?
  Python-telegram-bot adapters are single-loop by design — this is usually safe.
- [ ] **Write-then-read ordering:** Are writes (populating the dict) guaranteed to
  happen before reads (callback handler lookups)? In the suggestion-stripper case,
  the button message is sent before the user can click it, so this holds.
- [ ] **No cross-thread access:** If multiple threads or event loops could touch
  the adapter, this pattern breaks. Verify the adapter's threading model.
- [ ] **Expiry handling:** What happens when the dict is cleared (gateway restart)?
  The callback handler should detect missing keys and show an "expired" message
  rather than crashing.

## 5. Regression Risk Assessment

| Risk | Mitigation |
|------|-----------|
| False-positive marker strip inside code blocks | Harden regex; add tests for all edge cases above |
| Duplicate button sends if consumer reused across turns | `_hermes_turn_began` guard; monitor |
| Callback prefix collision (`sg:` namespace) | Verify no other handler uses the same prefix |
| Duplicated code-span logic between extraction and protection helpers | Refactor to share one protection function |
| Missing unit tests for regex and flag lifecycle | Add `test_suggestion_parser.py` with parametrized cases |

## Quick Audit Script

```python
import re

def audit_code_span_protection(cases):
    """Run the hook's actual protection regex against test cases."""
    for name, text, expect_protected in cases:
        prot = re.sub(r'```[\s\S]*?```', '\x00C\x00', text)
        prot = re.sub(r'`[^`]+`', '\x00C\x00', prot)
        has_marker = "SUGGESTION:" in prot
        status = "OK" if has_marker == (not expect_protected) else "FAIL"
        print(f"{status}: {name}")
```
