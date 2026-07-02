# Completeness Checklist

Before marking a feature complete, verify:

1. **Is it wired from every entry point that should use it?**
   - CLI (argparse flags present and forwarded?)
   - Library import (re-exported if consumers expect it from a specific module?)
   - Programmatic callers (pipeline.py, sdlc_state.py, controller agent?)
   - Cron jobs (if applicable)

2. **Is there dead code from the previous approach that should be removed?**
   - Old duplicate functions that the new pattern replaces
   - Old imports that are now unused
   - Reference docs that describe the old pattern

3. **Does the module docstring reflect the new reality?**
   - New flags documented in usage examples?
   - New functions listed in the API surface?
   - Interaction contract updated if behavior changed?

4. **Are there tests that exercise the new path?**
   - Not just the happy path — test the new parameter/flag/behavior
   - Mock at the right level (model_utils.dispatch_single, not ask.dispatch_single,
    unless the feature is ask-specific)
   - If the feature changes prompts, test that the prompt contains the new content

5. **If it writes files, is there a cleanup path?**
   - Tests create temp files — do they clean them up?
   - Error recovery — if the feature fails midway, are partial files left behind?
   - Cron jobs — do they accumulate files that need periodic cleanup?

## Pattern This Prevents

Three times in one session (2026-06-28) we found things built but never wired:
- `sdlc_control.py` — 136 lines written, tested, never imported by any file (deleted)
- `progress_callback` in ask.py — existed in model_utils.py but not forwarded through
  ask.py's entry points (fixed)
- `dispatch_comparison` — duplicated in ask.py without the callback forwarding
  that model_utils.py already had (consolidated)

The pattern: we build the engine but forget the ignition. This checklist catches that
before declaring done.