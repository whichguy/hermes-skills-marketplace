# Ad-Hoc Verification Pattern

After creating or modifying code via subagents (or directly), run a focused
structural verification before claiming the work is done. This catches
mechanical errors (missing files, wrong model assignments, broken section
parsers) that subagents and the controller both miss.

## Pattern

```python
import tempfile, subprocess, sys, os

# 1. Write verification script to /tmp with hermes-verify- prefix
tmpdir = tempfile.gettempdir()
script_path = os.path.join(tmpdir, "hermes-verify-<descriptive-name>.py")
with open(script_path, "w") as f:
    f.write(verification_script_content)

# 2. Run it
result = subprocess.run(
    [sys.executable, script_path],
    capture_output=True, text=True, timeout=30
)
print(result.stdout)

# 3. Report pass/fail count
# 4. Clean up
os.remove(script_path)
```

## When to Use

- After creating a new skill (check file structure, frontmatter, model assignments)
- After multi-subagent code changes (check file consistency, no orphaned imports)
- After any workflow where 3+ files were created/modified by subagents
- Before telling the user "done" on any non-trivial artifact

## What to Verify

Structural checks only — not runtime behavior:

- File existence at expected paths
- YAML/JSON/Toml parseability
- Python syntax validity (`py_compile`)
- Required fields present in frontmatter/config
- Model-to-stage mapping consistency (if multi-model)
- No stale path references (e.g., `/tmp/pipeline/` → `<pipeline_dir>`)
- Prohibited tool mentions (e.g., `execute_code` in subagent prompts)
- Design doc reflects review fixes

## Pitfall: Section Parsers and Code Blocks

When a verification script parses markdown sections by searching for `\n## `
headers, it will falsely match headers that appear **inside code blocks**
(like the goal template in a stage prompt). The fix: enumerate known section
markers explicitly instead of using a generic pattern.

**Broken (matches headers inside code blocks):**
```python
next_section = content.find("\n## ", idx + len(section_marker))
```

**Fixed (only matches known top-level sections):**
```python
next_section = -1
for s in ["## Stage 1:", "## Stage 2:", "## Stage 3:", ...]:
    si = content.find("\n" + s, idx + len(section_marker))
    if si != -1 and (next_section == -1 or si < next_section):
        next_section = si
```

This bug manifested in the `multi-model-dev-pipeline` skill verification:
Stage 6's `execute_code` prohibition was inside a code block after `## Commands
Used`, which the parser treated as a new section boundary. The prohibition text
was in the wrong "section" and the check falsely failed.

## Anti-Patterns

- **Don't** leave the verification script on disk — always clean up
- **Don't** write the script to the project directory — use `/tmp`
- **Don't** skip verification because "it looks right" — structural checks
  catch things humans and LLMs both miss
- **Don't** verify runtime behavior in these scripts — that's what live
  pipeline tests are for (Phase 2)
