# LLM-Efficient Docstring Convention

Established Jun 2026 during the ask skill refactor. Applied to `routing.py` and
`model_utils.py` (17 public functions, 10 NOTE / 5 PERF / 4 RACE breadcrumbs).

## Structured Docstring Format

Every public function gets a docstring with these sections:

```
def func_name(arg1: type, arg2: type) -> ReturnType:
    """One-line summary of what the function does.

    Args:
        arg1: Description.
        arg2: Description.
    Returns:
        What the function returns.
    Side Effects: None — pure function, no I/O.
    Dependencies: MODULE_LEVEL_CONSTANT, external_file_path.

    # NOTE: Non-obvious behavior or edge case.
    # PERF: Performance consideration.
    # RACE: Thread-safety or concurrency concern.
    """
```

### Section Rules

- **Args** — required if the function takes parameters (skip for zero-arg functions)
- **Returns** — always include, even if `None`
- **Side Effects** — always include. Be explicit: "None — pure function" or "Reads X from disk (no writes)"
- **Dependencies** — always include. List module-level constants, external files, or other functions this depends on
- **Breadcrumbs** — inline `# NOTE:`, `# PERF:`, `# RACE:` tags for non-obvious behavior

### Breadcrumb Tags

| Tag | When to use |
|-----|------------|
| `# NOTE:` | Non-obvious behavior, edge cases, "when X happens, Y wins" |
| `# PERF:` | Performance considerations, O(n) analysis, caching behavior |
| `# RACE:` | Thread-safety, concurrency, lru_cache + mutable state |

### Why This Format

LLMs read docstrings as structured context. The `Args`/`Returns`/`Side Effects`/`Dependencies`
pattern gives the model a complete mental model of the function without needing to read
the implementation. Breadcrumb tags surface non-obvious behavior that would otherwise
require reading the full function body.

This is more LLM-efficient than:
- Narrative docstrings ("This function does X, and then Y, and also Z...")
- Missing Side Effects (model assumes pure function, misses I/O)
- Missing Dependencies (model can't trace what the function reads)
- Comments buried in the body (model may not reach them in a partial read)
