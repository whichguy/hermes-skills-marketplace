# Fuzzy Alias Resolution — Implementation Notes

Added Jun 2026. Two-tier model name resolution for the `ask` command.

## Architecture

```
User types "ask minimax-3 ..."
         │
         ▼
  resolve_alias_fuzzy("minimax-3")
         │
    ┌────▼────┐
    │ Tier 1  │  Exact match in ALIASES dict (case-insensitive)
    │ ~0ms    │  Also: full model names with ":" pass through
    └────┬────┘
         │ no match
    ┌────▼────┐
    │ Tier 2  │  LLM fuzzy fallback via raw Ollama API
    │ ~0.5s   │  Model: qwen3.6:35b-a3b (fast, local, free)
    └────┬────┘
         │
    ┌────▼────┐
    │ Verify  │  LLM output checked against known alias list
    │         │  Prevents hallucinated model names
    └────┬────┘
         │
    ┌────▼────┐
    │  Cache  │  Thread-safe dict with lock
    │         │  Subsequent lookups: ~0ms
    └─────────┘
```

## Key Design Decisions

### 1. Hallucination guard
The LLM returns a raw alias name (e.g., `"minimax-m3"`). This is verified
against the known alias list before accepting. If the LLM returns a name
not in the list, it's treated as no match → original name passes through.

### 2. Thread-safe cache
`_fuzzy_cache: dict[str, str | None]` with `threading.Lock()`. Cache stores
the resolved alias (or `None` for no-match). Cache is per-process, not
persistent — resets on restart.

### 3. Fast local model
Uses `qwen3.6:35b-a3b` via raw Ollama API (not `hermes chat`). This is the
same model used by `triage.py`. ~0.5s wall time.

### 4. Prompt design
```
/no_think
You are a model name resolver. Map the user's input to the closest
matching alias from the list below. Match by brand, family, version,
or abbreviation. Return ONLY the alias name, nothing else. If no
match, return NONE.

Known aliases:
- minimax
- deepseek
- kimi
...

User input: minimax-3
```

Key prompt features:
- `/no_think` prefix — disables chain-of-thought for speed
- `temperature: 0.0` — deterministic
- `num_predict: 50` — short output, no rambling
- `"Return ONLY the alias name"` — structured output without JSON

### 5. Graceful failure
If Ollama is down, the API call fails, or the LLM returns no match:
- `_fuzzy_resolve_raw()` catches exceptions and returns `None`
- `resolve_alias_fuzzy()` returns `(original_name, False)`
- The original name passes through to Hermes, which rejects it with
  a clear "unknown model" error

## API

```python
# Public API
resolved, was_fuzzy = resolve_alias_fuzzy("minimax-3")
# → ("minimax-m3:cloud", True)

resolved, was_fuzzy = resolve_alias_fuzzy("deepseek")
# → ("deepseek-v4-pro:cloud", False)  # exact match, no LLM

resolved, was_fuzzy = resolve_alias_fuzzy("totally-unknown")
# → ("totally-unknown", False)  # no match, passthrough

# Internal
alias = _fuzzy_resolve_raw("minimax-3", ["minimax", "deepseek", ...])
# → "minimax-m3" or None

prompt = _build_fuzzy_prompt("minimax-3", ["minimax", "deepseek", ...])
# → "/no_think\nYou are a model name resolver..."
```

## Integration Points

### ask.py CLI
- `--models` flag: each comma-separated entry goes through `resolve_alias_fuzzy()`
- Positional parsing: if no models recognized in first words, tries fuzzy on first word
- `was_fuzzy` flag used for logging/debugging

### model_utils.py
- `resolve_alias_fuzzy()` — two-tier public API
- `_fuzzy_resolve_raw()` — raw Ollama API call
- `_build_fuzzy_prompt()` — prompt construction
- `_fuzzy_cache` — thread-safe cache dict

## Test Coverage

14 tests in `TestFuzzyAliasResolution` + `TestFuzzyPromptBuilding`:
- Exact match (no LLM call)
- Full model passthrough (no LLM call)
- Case-insensitive exact match
- LLM fuzzy match → correct resolution
- LLM no match → original passthrough
- LLM network error → original passthrough
- Cache hit → no second LLM call
- Prompt contains user input, all aliases, `/no_think`, `NONE` instruction

All mock tests (no Ollama needed). Live fuzzy tests in `test_ask.py::TestLiveFuzzyResolution`.
