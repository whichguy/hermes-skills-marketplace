# devloop — local setup

## Coder model (required for the IMPLEMENT phase)

The IMPLEMENT phase needs a model with enough context for tool-heavy agentic prompts
(the `file,terminal` tool schemas + system prompt + the request). Two gotchas learned the hard way:

- **`qwen3-coder-next:cloud` is broken upstream** — Ollama's cloud serves it with a ~0-token
  context (a 256k model card, but it errors on even a 6-word prompt). Re-pull does not fix it.
  It was removed; re-pull only if Ollama fixes it.
- **`qwen3-coder-next` (qwen3next arch) needs ≥ 64k context for reliable tool use.** The bare local
  `q4_K_M` has no `num_ctx` set, so its default is too small and tool calls fail with
  "needs at least 64,000 tokens for reliable tool use."

Fix: create a local coder with a fixed 64k context from the working local weights:

```bash
ollama create qwen3-coder-next:devloop -f setup/qwen3-coder-next-devloop.Modelfile
```

## Runtime requirement: pytest

The test-designer writes **pytest** tests and the loop runs them, so `sys.executable -m pytest`
MUST work in the devloop runtime. If pytest is missing, `testgen.collect_test_map` raises (the
runner routes to HUMAN_REVIEW with a clear reason) — a missing dependency is never mistaken for a
coverage failure. The container has it via `uv` — run devloop under `uv run --with pytest python3 …`
(or install pytest into the runtime venv). Learned the hard way: running the v1 e2e under plain
`python3` (no pytest) made every criterion look uncovered.

## Models devloop uses (all overridable via env)

| Role | Default | Env | Notes |
|---|---|---|---|
| planner (CHARTER) | `glm-5.2:cloud` | `DEVLOOP_PLANNER` | |
| **coder** (IMPLEMENT, per-iteration) | `kimi-k2.7-code:cloud` | `DEVLOOP_CODER` | fast cloud — the bottleneck role |
| **designer** (writes tests, once) | `deepseek-v4-pro:cloud` | `DEVLOOP_DESIGNER` | local `qwen3-coder-next:devloop` (64k) is an override |
| judge A | `glm-5.2:cloud` | `DEVLOOP_JUDGE_A` | |
| judge B | `minimax-m3:cloud` | `DEVLOOP_JUDGE_B` | |

**Distinctness is enforced** (`dispatch.assert_distinct_models`): coder, designer, judge A, judge B
must all be different models — no model writes both the tests and the code, or grades its own work.
A collision raises at the start of a run.

Run dispatch where `HERMES_BIN` exists (the container) — file writes only land under the Hermes
write-safe root (`/opt/data`), so target dirs must live there.

## Lint gate (post-IMPLEMENT syntactic check)

After the coder writes files, the loop runs language-appropriate linters on **exactly the files it
changed** (`dispatch` reports `changed_paths`; `lint.lint_paths` runs them). A confirmed linter
failure feeds the errors back to the coder and forces a rebuild — it can never let syntactically
broken code COMPLETE. A missing linter or an unmapped file type is **skipped, never failed**, so a
tool not being installed can't fail-close a correct build.

Wired today (`lint.py`, registry `LINTERS = {ext: [builders]}`):

| Language | Linter | Notes |
|---|---|---|
| `.py` | `compile()` syntax check | stdlib, always present, no `.pyc` side effects |
| `.py` | `ruff check --select E9,F82x` | **only if `ruff` is installed**; ERROR rules only (syntax + undefined names), never style — so nits don't cause false rebuilds |

To cover more languages, add an entry to `LINTERS` (e.g. `".js": [eslint_builder]`); a builder
returns the argv or `None` when its tool is absent.
