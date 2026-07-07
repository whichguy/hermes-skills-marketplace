# Three-Model Review Pipeline

## User's Preferred Workflow

For development work involving code changes, dispatch subagents in this specific model-to-role mapping:

| Model | Role | When |
|---|---|---|
| **DeepSeek V4 Pro** (`deepseek-v4-pro:cloud`) | Plan review + test coverage audit | After writing a plan or test file — verify against real codebase, catch import errors, abstract method breaks, scope gaps |
| **Kimi** (`kimi-k2.7-code:cloud`) | Code review + debug + auto-fix | After code is written — find bugs, quality issues, security problems, and fix them directly |
| **Qwen coder** (local `qwen3-coder-next:q4_K_M`) | Code production | Write the actual implementation code, apply fixes identified by reviewers |

## Dispatch Pattern

> ⚠️ **Per-task `model` overrides on `delegate_task` do NOT work reliably** (verified 2026-06-27). All subagents inherit `delegation.model` from config.yaml regardless of the per-task `model` field. **Use `prompt_model.py` from the `advisors` skill instead** for per-call model selection — it runs `hermes chat -q` as a subprocess with actual per-call model diversity. See the `advisors` skill and the `dev` skill for role-based development with verified model diversity.

### Phase 1: Parallel Review (DeepSeek + Kimi)

After writing a plan and code, dispatch both reviewers simultaneously using `prompt_model.py`:

```python
import subprocess, concurrent.futures, sys

SCRIPT = "/opt/data/skills/autonomous-ai-agents/advisors/scripts/prompt_model.py"

seats = [
    ("deepseek-v4-pro:cloud", "/tmp/review-plan.md", "Plan Review"),
    ("kimi-k2.7-code:cloud", "/tmp/review-code.md", "Code Review"),
]

def dispatch(model, outfile, role):
    cmd = [sys.executable, SCRIPT, "-m", model,
        "-p", "Review the plan and test coverage" if "Plan" in role else "Review code quality, find bugs, and auto-fix",
        "-t", "file,terminal", "--max-turns", "8", "-o", outfile]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return role, model, r.returncode

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(dispatch, m, f, r) for m, f, r in seats]
    for fut in concurrent.futures.as_completed(futures):
        role, model, rc = fut.result()
        print(f"{'✅' if rc == 0 else '❌'} {role} ({model})")
```

### Phase 3: Re-verify

After fixes are applied, re-run the test suite and re-dispatch reviewers if needed.

## Pitfalls

- **Don't skip the parallel dispatch** — DeepSeek and Kimi review different things (plan architecture vs code quality). Running them sequentially doubles wall-clock time for no benefit.
- **Don't have Qwen fix while reviews are running** — wait for both reviews to land so fixes are comprehensive, not piecemeal.
- **Kimi auto-fixes are best-effort** — the Qwen coder phase should verify and complete any fixes Kimi couldn't apply.
- **DeepSeek reviews the PLAN, not the code** — give it the plan file and test file, not the implementation. It catches architectural issues the code reviewer misses.
