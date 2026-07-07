# Shared Error Taxonomy — Gap Identified 2026-07-05

Cross-skill review of 7 autonomous-ai-agents skills found no shared error
taxonomy. Each skill defines its own exit codes and failure semantics:

| Skill | Exit Codes | Failure Semantics |
|---|---|---|
| advisors | 0=success, 1=error, 2=timeout | Subprocess-level; no agent-level error codes |
| delegate-progress-protocol | N/A (protocol, not script) | 5× estimate hard cutoff; gateway restart detection |
| investigator | N/A (orchestrator) | Ollama unreachable → exit 2; max_assumes cap |
| next-best-questions | N/A (ranker) | Model call failures → fallback to FINDABLE |
| relentless-solve | 10=GUARD-HALT | Durable resumption; dead-set prevents retry |
| task-decomposer | N/A (oneshot) | Malformed plan → retry with violations echoed (3 strikes) |
| method-explorer | N/A (driver) | Dead-set records exhausted methods; GUARD-HALT for sim |

## Recommendation

Consider a common `ERROR_CODES.md` reference shared across the category:

```
0  = SUCCESS
1  = GENERAL_ERROR
2  = TIMEOUT
3  = OOM / RESOURCE_EXHAUSTED
4  = MODEL_UNAVAILABLE
5  = MALFORMED_OUTPUT (plan.json, schema violation)
6  = EXHAUSTED (all methods tried, none worked)
7  = GUARD_HALT (human decision needed)
8  = STALE_IMPORT (shared constant removed from dependency)
9  = ARG_TOO_LONG (OS ARG_MAX exceeded)
10 = GATEWAY_RESTART (transient, retryable)
```

This would let drivers (relentless-solve, method-explorer) handle failures
from sub-skills uniformly without per-skill error-code translation.
