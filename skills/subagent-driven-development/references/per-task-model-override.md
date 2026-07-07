# Per-Task Model Override — Implementation Reference

> ⚠️ **REALITY CHECK (2026-06-27): Despite the code and 23 passing tests below, per-task `model` overrides do NOT work in practice.** A live test dispatched `delegate_task(goal="...", model="deepseek-v4-pro:cloud")` and the subagent actually ran on `qwen3-coder-next:q4_K_M` (the `delegation.model` from config.yaml). The per-task model was silently ignored. **Use `prompt_model.py` from the `advisors` skill instead** for per-call model selection — it runs `hermes chat -q` as a subprocess with actual per-call model diversity. See the `advisors` skill and the `dev` skill for role-based development with verified model diversity.
>
> The code below is retained for reference — it may work in some configurations or future versions, but do not rely on it without verifying the subagent's actual model in the result message header.

## What

`delegate_task` accepts an optional `model` parameter at both the top level (single-task mode) and inside each task dict (batch mode). This lets the orchestrator route different subagent tasks to different models without changing config.

## Resolution Order

```
Per-task model → delegation.model (config) → parent_agent.model (inherit)
```

Empty string `""` and whitespace-only strings (`"   "`) are treated as unset — falls through to the next level. The `.strip()` normalization happens in the child-building loop.

## Code Changes (Hermes v0.15.1)

**File:** `tools/delegate_tool.py`

1. **Schema** — added `"model": {"type": "string"}` to both top-level `properties` and `tasks.items.properties` in `DELEGATE_TASK_SCHEMA`
2. **Dynamic schema** — `_build_dynamic_schema_overrides()` inherits the field automatically (no change needed)
3. **Function signature** — added `model: Optional[str] = None` to `delegate_task()`
4. **Handler lambda** — wired `model=args.get("model")` in the registry handler
5. **Single-task mode** — top-level `model` flows into the task list: `tasks = [{"goal": goal, "context": context, "model": model}]`
6. **Per-task routing** — in the child-building loop: `task_model = (t.get("model") or "").strip()` → `creds["model"] = task_model or creds.get("model")`
7. **Dynamic descriptions** — `_build_top_level_description()` and `_build_tasks_param_description()` both mention the `model` parameter so the LLM knows it exists

## Kimi's 3 Revisions (post-code-review)

After the initial implementation, an independent code review (Kimi) identified 3 issues, all addressed:

| # | Issue | Fix |
|---|-------|-----|
| 1 | Whitespace-only model strings (`"   "`) not normalized | `.strip()` in the child-building loop: `(t.get("model") or "").strip()` |
| 2 | Dynamic schema descriptions don't mention model override | Added model override text to both `_build_top_level_description()` and `_build_tasks_param_description()` |
| 3 | Model-only override with no provider — credential inheritance unclear | Verified: parent credentials (provider, base_url, api_key) are inherited when only model is overridden |

## 🐛 Bug Found: Background Mode Ignores Model Override

Kimi's second review (coverage analysis) found a live bug: the async/background dispatch path (`dispatch_async_delegation`) was passing `creds["model"]` instead of the per-task override. The child was built correctly with the override model, but the dispatch call used the config default.

**Fix (line 2313):**
```python
# Before (bug):
model=creds["model"],

# After:
model=str(_t.get("model") or "").strip() or creds["model"],
```

The `_t` variable (from `_i, _t, child = children[0]`) is already in scope in the `n_tasks == 1` block, so no new variable needed. Pyright's "possibly unbound" warning on `task_model` is avoided by reading from `_t` directly.

## 🐛 Bug Found: Non-String Model Values Crash

Deepseek's coverage analysis found that non-string model values (`True`, `123`, `["model"]`) would crash with `AttributeError` on `.strip()`. The expression `(t.get("model") or "").strip()` calls `.strip()` on whatever `t.get("model")` returns — if it's a truthy non-string like `True`, Python calls `True.strip()` which doesn't exist.

**Fix (lines 2225 and 2313):**
```python
# Before (crash on non-string):
task_model = (t.get("model") or "").strip() or creds["model"]

# After (safe):
task_model = str(t.get("model") or "").strip() or creds["model"]
```

The `str()` coercion handles any type. Falsy non-strings (`0`, `False`) fall through to the config default because `str(0 or "")` = `str("")` = `""` which is falsy after `.strip()`. Truthy non-strings (`True`, `123`) become their string representation (`"True"`, `"123"`) which will fail at model resolution but won't crash the tool.

## Test Suite

**File:** `tests/tools/test_delegate.py`

Class `TestPerTaskModelOverride` with 23 tests (163 total, zero regressions):

| Test | What it verifies |
|------|-----------------|
| `test_schema_exposes_model_param` | Schema includes `model` in both top-level and per-task |
| `test_top_level_model_override_single_task` | Single-task: model kwarg reaches AIAgent |
| `test_per_task_model_overrides_delegation_config` | Per-task model beats delegation config |
| `test_no_per_task_model_falls_back_to_delegation_config` | Absent model → delegation config default |
| `test_empty_model_string_treated_as_unset` | `""` → falls through to config |
| `test_whitespace_only_model_string_treated_as_unset` | `"   "` → falls through to config (Kimi fix 1) |
| `test_batch_mixed_models` | 3 tasks: explicit kimi, explicit deepseek, default → all correct |
| `test_model_only_no_provider_inherits_parent_credentials` | Model-only override inherits parent provider + base_url (Kimi fix 3) |
| `test_top_level_model_ignored_when_tasks_array_provided` | Top-level model is ignored in batch mode; per-task or config used |
| `test_none_model_value_treated_as_unset` | Explicit `None` model value falls back to delegation config |
| `test_model_override_falls_back_to_parent_when_config_empty` | No config model, no per-task model → inherits parent model |
| `test_strips_whitespace_from_model_name` | Leading/trailing whitespace stripped before use |
| `test_schema_model_description_mentions_override` | Dynamic descriptions advertise the model override feature |
| `test_background_model_override_passes_to_async_dispatch` | Background dispatch receives per-task model, not config default (bug fix) |
| `test_orchestrator_role_preserves_per_task_model` | Orchestrator role doesn't drop the model override |
| `test_acp_transport_preserves_per_task_model` | ACP transport doesn't drop the model override |
| `test_toolset_intersection_preserves_per_task_model` | Toolset intersection doesn't drop the model override |
| `test_result_metadata_reports_overridden_model` | Result metadata includes the overridden model name |
| `test_non_string_model_value_degrades_safely` | `True`/`0` model values coerced safely, no crash (bug fix) |
| `test_per_task_model_with_delegation_provider_uses_resolved_credentials` | Cross-provider: model overridden but provider credentials preserved |
| `test_per_task_model_preserves_parent_fallback_chain` | Fallback chain survives model override |
| `test_json_string_tasks_with_per_task_model` | JSON-string tasks array with model fields parsed correctly |
| `test_background_with_multiple_tasks_and_model_returns_error` | Batch + background + model → still rejected with error |

## Pitfalls

- **Provider mismatch:** Model override changes only the model name, not the provider. If `delegation.provider` is `openrouter` but you specify `deepseek-v4-pro:cloud` (a custom provider model), the subagent will fail. Verify provider-model compatibility.
- **Credentials:** The subagent uses the delegation provider's credentials. If the model requires a different API key, it won't work.
- **Not a full routing layer:** This is a simple string override, not a model router. It doesn't validate model availability, check provider compatibility, or handle fallback chains.
- **Whitespace in model strings:** The LLM may pass `"   "` or `"  deepseek-v4-pro:cloud  "` — `.strip()` handles both. If you modify the child-building loop, preserve the `.strip()` call.
