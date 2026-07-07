# Quality Review — 2026-06-27

## Current State

| Metric | Value |
|--------|-------|
| Commits | 15 (dc186e1 → 5285efa) |
| Files | 7 source + 2 test + 3 docs |
| Total lines | ~3,200 (source) + ~1,300 (tests) |
| Test functions | 118 (94 ask + 24 routing) |
| Public functions with docstrings | 17/17 (routing+model_utils) |
| Breadcrumbs (NOTE/PERF/RACE) | 21 total across 3 files |

## Issues Found: 21 total

### 🔴 Architecture (1 issue — CRITICAL)

**A1: ask.py is a 630-line Frankenstein — imports from model_utils AND reimplements the same functions**

ask.py imports `dispatch_single as _dispatch_agent`, `clean_output as _clean_output`, `build_prompt as _build_prompt` from model_utils.py, but ALSO defines its own copies of:
- `resolve_alias_for_ask()` (wraps model_utils.resolve_alias)
- `is_known_model()` (reimplements, uses local ALIASES dict)
- `get_reasoning_effort()` (full reimplementation — NOT imported)
- `set_reasoning_effort()` (full reimplementation — NOT imported)
- `clean_output()` (full reimplementation — NOT using imported `_clean_output`)
- `build_prompt()` (full reimplementation — NOT using imported `_build_prompt`)
- `save_session()` (full reimplementation)
- `get_session()` (full reimplementation)
- `dispatch_single()` (new version — calls imported `_dispatch_agent`)
- `dispatch_comparison()` (full reimplementation)

**Root cause:** ask.py was built first, then model_utils.py was extracted. The subagent that rewrote ask.py added imports from model_utils but didn't remove the old local implementations. The result is TWO copies of most functions — tests mock the ask.py versions, but the actual code paths are ambiguous.

**Impact:**
- Tests mock `ask.get_reasoning_effort` and `ask.set_reasoning_effort` but these are DEAD CODE — never called. The imported versions from model_utils are used instead.
- `resolve_alias_for_ask()` defined but never called (dead code).
- Local `ALIASES` dict duplicates model_utils `ALIASES` dict — any new alias must be added in BOTH places.
- Local `THINKING_LEVELS`, `DEFAULT_PROVIDER`, `DEFAULT_TIMEOUT`, `SESSIONS_FILE`, `HERMES_BIN`, `BITWARDEN_PREFIX` all duplicate constants from model_utils.py.

### 🟡 Duplications (8 issues)

| # | Issue | Impact |
|---|-------|--------|
| D1 | ask.py defines 10 functions that also exist in model_utils.py | Confusing — which version is called? |
| D2 | ask.py:is_known_model() — full reimplementation | Uses local ALIASES, not model_utils ALIASES |
| D3 | ask.py:get_reasoning_effort() — full reimplementation | Dead code — never called |
| D4 | ask.py:set_reasoning_effort() — full reimplementation | Dead code — never called |
| D5 | ask.py:clean_output() — full reimplementation | Shadowing — tests mock this but code uses imported version |
| D6 | ask.py:build_prompt() — full reimplementation | Same shadowing issue |
| D7 | ask.py:save_session() — full reimplementation | Same shadowing issue |
| D8 | triage.py:_needs_no_think() duplicated in model_utils.py:needs_no_think() | Documented but not resolved — risk of drift |

### 🟡 Dead Code (8 issues)

| # | Issue | Fix |
|---|-------|-----|
| DC1 | improvement-plan references deleted prompt_model.py (2 lines) | Update doc |
| DC2 | model_utils.py docstring references deleted prompt_model.py (3 lines) | Update docstring |
| DC3 | ask.py:resolve_alias_for_ask() — defined but never called | Delete |
| DC4 | ask.py:get_reasoning_effort() — defined but never called | Delete (use imported) |
| DC5 | ask.py:set_reasoning_effort() — defined but never called | Delete (use imported) |
| DC6-8 | ask.py:clean_output/build_prompt/save_session — defined locally, tests mock these, but code uses imported versions | Delete local copies, update tests |

### 🟡 Inconsistencies (1 issue)

| # | Issue | Fix |
|---|-------|-----|
| I1 | routing.py:cached_classify() uses timeout=10 but triage DEFAULT_TIMEOUT=30 | Change to timeout=30 |

### 🟡 Missing (3 issues)

| # | Issue | Fix |
|---|-------|-----|
| M1 | ask.py has 0 breadcrumbs (NOTE/PERF/RACE) | Add breadcrumbs |
| M2 | No tests for _run_raw_mode() | Add test coverage |
| M3 | No tests for _run_agent_mode() | Add test coverage |

---

## Improvement Proposal — Phase 6

### Phase 6A: De-duplicate ask.py (CRITICAL — do first)

**Goal:** Remove ~200 lines of dead/duplicated code from ask.py. Make it a thin CLI wrapper over model_utils.py.

**Tasks:**
1. Delete local reimplementations: `get_reasoning_effort()`, `set_reasoning_effort()`, `clean_output()`, `build_prompt()`, `save_session()`, `get_session()`, `resolve_alias_for_ask()`
2. Remove duplicated constants: `ALIASES`, `THINKING_LEVELS`, `DEFAULT_PROVIDER`, `DEFAULT_TIMEOUT`, `DEFAULT_TOOLSETS`, `BITWARDEN_PREFIX`, `SESSIONS_FILE`, `HERMES_BIN`
3. Import everything from model_utils.py (ask.py becomes ~200 lines, down from 630)
4. Update tests: mock `model_utils.get_reasoning_effort` etc. instead of `ask.get_reasoning_effort`
5. Keep `dispatch_single()` and `dispatch_comparison()` in ask.py — these are ask-specific wrappers that add `--mode raw` support
6. Fix routing.py cached_classify timeout 10→30

**Risk:** Medium — tests currently mock ask.py functions. Need to update mock targets.
**Estimated time:** 1-2 hours

### Phase 6B: Test coverage for new modes (MEDIUM)

**Goal:** Cover `_run_raw_mode()` and `_run_agent_mode()` — currently untested.

**Tasks:**
1. Add tests for _run_raw_mode: mock urllib.request, verify direct API call path
2. Add tests for _run_agent_mode: mock _dispatch_agent, verify agent dispatch path
3. Add tests for --clean-sessions flag
4. Add tests for --mode flag selection logic

**Risk:** Low — additive only
**Estimated time:** 30-60 min

### Phase 6C: Breadcrumbs + docs for ask.py (LOW)

**Goal:** Add LLM-efficient documentation to ask.py (currently has 0 breadcrumbs).

**Tasks:**
1. Add `# NOTE:` / `# PERF:` / `# RACE:` breadcrumbs to ask.py functions
2. Add structured docstrings to _run_raw_mode, _run_agent_mode, main()
3. Update model_utils.py docstring to remove prompt_model.py references
4. Update improvement-plan to mark prompt_model.py as deleted

**Risk:** None — documentation only
**Estimated time:** 30 min

### Phase 6D: Resolve triage/model_utils duplication (LOW — defer)

**Goal:** Address the _needs_no_think() / needs_no_think() duplication.

**Recommendation:** Keep current state. Triage is designed to be standalone (no imports beyond stdlib). The duplication is intentional and documented with a cross-reference comment (commit 5285efa). If compat changes, both copies must be updated.

### Priority Order

1. **6A** (de-duplicate ask.py) — highest impact, removes 200+ lines of confusing dead code
2. **6B** (test coverage) — safety net for 6A changes
3. **6C** (breadcrumbs + docs) — polish, low risk
4. **6D** (triage duplication) — defer, documented

### Summary Table

| Phase | Tasks | Lines Changed | Risk | Time |
|-------|-------|---------------|------|------|
| 6A | De-duplicate ask.py | -200 | Medium | 1-2h |
| 6B | Test _run_raw/agent_mode | +100 | Low | 30-60m |
| 6C | Breadcrumbs + docs | +50 | None | 30m |
| 6D | Triage duplication | 0 (defer) | N/A | N/A |