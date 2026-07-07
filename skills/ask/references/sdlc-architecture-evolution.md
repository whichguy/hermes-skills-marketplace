# SDLC Architecture Evolution

## P8: Prompt Engineering Fixes (Jun 2026)
- 16 fixes across triage.py, model_utils.py, pipeline.py
- Root cause: debugger role injection caused model to return output instead of code
- Key fix: role directive prepended before user content (not appended)
- Triage prompt rewritten: removed "Category:" prefix, added code extraction instructions
- 261 non-live + 5/5 live E2E tests pass

## P9: SDLC Expansion — Cascading Debugger (Jun 2026)
- debug_code → qwen3-coder-next:q4_K_M (primary) → kimi-k2.7-code:cloud (fallback)
- Aliases: debugger→qwen-coder, debugger-fallback→kimi, test-planner→deepseek
- build_code routes to test-first SDLC pipeline (sdlc.py)
- 277 non-live tests pass

## P10: Multi-Suite Testing + Council Review (Jun 2026)
- 3 test suites: unit (15s), integration (30s), e2e (60s)
- design_test_suites() uses DeepSeek with # SUITE: markers
- run_test_suites() runs in order, stops on first failure
- council_review() uses DeepSeek (thinking=high) for P0/P1 improvement items
- DEBUG_SDLC=true env var retains interim files
- 296 non-live tests pass, 59 SDLC-specific tests pass

## P11: Live E2E Testing Infrastructure (Jun 2026)
- 10 live E2E tests in test_pipeline_e2e.py (RUN_LIVE_PIPELINE=1 gated)
- P12-A through P12-E: 5 live tests covering minimal build, full SDLC, debug cascade, run_pipeline path
- Live tests use real models (qwen-coder, deepseek, kimi, GLM) via Ollama
- P12-C: full 9-phase pipeline passes in 327s (palindrome checker)
- P12-D: debug cascade standalone passes in 62s
- P12-E: run_pipeline() path timed out at 600s (pipeline_timeout too short)

## P12: Live E2E Results & Bug Discovery (Jun 2026)
- 7 findings from live testing (see sdlc-plan-2026-06-27.md P14 bug table)
- F1: toolsets='web' + max_turns=5 causes tool-call attempts in text-output phases
- F2: extract_python_code() leniency returns prose/API errors as "code"
- F3: implement_failed not reported when extraction returns None
- F4: extract_python_code() takes first block, not largest (multi-block responses)
- F5: AI-generated tests may have wrong expected values (test oracle problem)
- F6: tech_docs() returns None due to model non-determinism
- F7: pipeline_timeout=300s too short for full SDLC (needs 900s)

## P13: Edge Case Testing (Jun 2026)
- P13-H: 9 edge-case tests for extract_python_code() — multiple blocks, prose, API errors, invalid syntax, mixed valid/invalid
- Test class: TestExtractPythonCode

## P14: Pipeline Hardening (Jun 2026)
All 8 hardening items completed:

| Item | Description | Tests |
|------|-------------|-------|
| P14-A | 4 bug fixes (toolsets, extraction, silent-success, multi-block) | — |
| P14-A-2 | ast.parse() syntax verification for extraction | 9 (P13-H) |
| P14-C | CI-runnable regression tests for each P14-A fix | 7 (TestP14ARegressions) |
| P14-D | Simplify re-verification — re-run tests, revert if broken | 1 |
| P14-E | Council quorum model — success/partial/failed status | 2 (updated) |
| P14-F | Pipeline timeout — 900s default, elapsed tracking | 1 |
| P14-G | Debug cascade gets full context — suite name + stdout + stderr | 1 |
| P14-H | Aggressive linting for code AND tests — ruff + autopep8 | 16 (9 initial + 7 aggressive) |

## Current Pipeline Flow (11 phases)
```
Phase 1:   plan (GLM)
Phase 2:   design_test_suites (DeepSeek, 3 suites: unit/integration/e2e)
Phase 3:   implement (Qwen-coder)
Phase 3.5: lint_code (aggressive auto-fix: ruff check --fix --unsafe-fixes → ruff format → autopep8 --aggressive --aggressive → ast.parse re-verify)
Phase 3.6: lint_test_suites (lint each test suite individually, auto-fix, return fixed_suites)
Phase 4:   run_test_suites (fail-fast, uses fixed code + fixed tests)
Phase 5:   debug_cascade (qwen-coder→kimi, full context: suite name + stdout + stderr)
Phase 6:   tech_docs pass 1 (qwen-coder, thinking=low)
Phase 7:   simplify_code → re-verify tests → revert if broken
Phase 8:   tech_docs pass 2 (qwen-coder, thinking=low)
Phase 9:   council_review (3-model: DeepSeek + Kimi + GLM, thinking=high, quorum: success/partial/failed)
```

## Key Files
- `scripts/sdlc.py` — Test-first pipeline orchestration (11 phases)
- `scripts/model_utils.py` — Aliases, dispatch_single(), session management
- `scripts/pipeline.py` — Triage→routing→SDLC dispatch
- `scripts/routing.py` — Category→pipeline routing table
- `tests/test_sdlc.py` — 123 mock tests (10 test classes + P13-H + P14-C + P14-D/F/G/H)
- `tests/test_pipeline_e2e.py` — 10 live E2E tests (RUN_LIVE_PIPELINE=1 gated)
- `references/sdlc-plan-2026-06-27.md` — Full implementation plan with bug table, acceptance criteria

## Commit History (P12-P14)
| Commit | Phase | Tests |
|--------|-------|-------|
| `7719385` | P12 + P14-A | 98 |
| `9761060` | P14-A-2 + P14-C | 104 |
| `e07f79b` | P14-H (initial) | 113 |
| `d3245ee` | P14-H (aggressive + tests) | 120 |
| `aec75c6` | P14-D/E/F/G | 123 |
