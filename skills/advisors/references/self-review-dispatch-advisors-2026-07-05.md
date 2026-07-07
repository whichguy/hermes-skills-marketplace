# Self-Review: dispatch_advisors.py (2026-07-05)

## Context

Used `dispatch_advisors.py` itself to quality-review the v3.4 advisors skill changes.
This is the "eat your own dogfood" meta-pattern — the file-referenced dispatch
helper reviewed itself.

## Dispatch

- **Brief:** 29K chars on disk at `/tmp/advisors-qr/brief.md`
- **Seats:** DeepSeek (Reasoner, 165.9s, 9.6K chars) + Kimi (Coder, 92.5s, 10.8K chars)
- **Synthesis:** GLM-5.2 (35.4s, 9.3K chars)
- **Controller context impact:** Only the 9.3K synthesis entered context. The 29K
  brief + 20K of seat outputs stayed on disk. This validated the architecture.

## Bugs Found (10 confirmed)

### Crash-class (3)

1. **`parse_seats(None)` crashes** — `--seats` defaults to `None`, `parse_seats`
   calls `.split(",")` on it → `AttributeError`. Both seats flagged it.
   **Fix:** None guard at top of `parse_seats` returning `DEFAULT_SEATS`.

2. **`parse_seats` model:role heuristic mangles local model tags** — the old
   heuristic checked if the part before `:` contained `.` or `-` to decide
   model vs role. But `qwen3.6:35b-a3b` splits into `("qwen3.6", "35b-a3b")`
   because `qwen3.6` contains `.`. This is a silent misdispatch.
   **Fix:** Replaced heuristic with known-provider-suffix allowlist
   (`cloud`, `local`, `mlx`, `ollama`). If the last `:`-segment is a known
   provider, the full string is the model name. For explicit roles, use
   pipe syntax: `model|Role` (e.g., `deepseek-v4-pro:cloud|Reasoner`).

3. **Relative `outdir` breaks under subprocess `cwd`** — `dispatch()` runs
   `subprocess.run(cmd, cwd=ASK_SCRIPTS_DIR)`, so relative brief paths resolve
   against the wrong directory. DeepSeek missed this; Kimi caught it.
   **Fix:** `self.outdir = os.path.abspath(outdir)` in `__init__`.

### High (1)

4. **`dispatch()` results in finish order, not input order** —
   `concurrent.futures.as_completed()` returns futures in completion order.
   `read_seat(0)` returned the fastest finisher, not the first listed seat.
   **Fix:** Track index in `dispatch_seat()`, sort results by index before
   returning.

### Medium (3)

5. **`synthesize()` runs with zero successful seats** — dispatches GLM with
   an empty file list.
   **Fix:** Short-circuit + warn if no seat files exist.

6. **`cli_synthesize` reconstructs fake metadata from filenames** — role
   becomes the filename, model field is blank.
   **Fix:** `dispatch()` now writes a `seats.json` manifest. `cli_synthesize`
   reads it instead of scanning filenames.

7. **No brief-file existence check in `dispatch()`** — crashes with a
   cryptic subprocess error if brief is missing.
   **Fix:** `FileNotFoundError` guard at entry.

### Low (3)

8. **Missing `extra_context_files` silently skipped** — no warning.
   **Fix:** Warning to stderr.

9. **Unused `import json`** — now used for `seats.json` manifest.

10. **`dispatch()` docstring says 4-tuple, returns 5-tuple** —
    `(role, model, elapsed, returncode, outfile)`.
    **Fix:** Updated docstring.

## SKILL.md Issues Found (2)

1. **Synthesizer contradiction** — dispatch plan table said
   `deepseek-v4-pro:cloud`, code examples use `glm-5.2:cloud`.
   **Fix:** Corrected to GLM.

2. **Stale `cwd=ASK_SCRIPTS_DIR` pitfall** — claimed imports would fail
   without specific cwd. But `prompt_model.py` uses `__file__`-relative
   `sys.path`, so imports work regardless of cwd.
   **Fix:** Rewrote pitfall to reflect reality.

## Lessons

### The file-referenced architecture works

The self-review validated the core architecture: 29K brief + 20K seat outputs
stayed on disk. Only the 9.3K synthesis entered the controller's context. The
dispatch_advisors.py helper made the pattern easy to use — 3 method calls
(prepare_brief → dispatch → synthesize) vs the old manual concurrent.futures
boilerplate.

### 2-seat panels catch real bugs that tests miss

The functional tests (10/10 passing) didn't catch any of the 3 crash-class
bugs. The advisor panel caught them by reasoning about edge cases the tests
didn't cover. Kimi caught the relative-outdir bug that DeepSeek missed —
different training lineages catch different things.

### parse_seats is a trap

The model:role disambiguation problem is inherent in CLI argument parsing.
The pipe syntax (`model|Role`) is the clean solution — it avoids the ambiguity
entirely. The provider allowlist handles the common case (cloud/local models)
without special syntax, but local model tags with non-standard suffixes need
pipe syntax.

### seats.json manifest > filename scanning

The `cli_synthesize` command originally reconstructed seat metadata by scanning
filenames (`seat-1-reasoner.md` → role="seat-1-reasoner", model=""). Writing a
`seats.json` manifest during `dispatch()` is cleaner and preserves full metadata
(role, model, outfile, returncode) without parsing filenames.