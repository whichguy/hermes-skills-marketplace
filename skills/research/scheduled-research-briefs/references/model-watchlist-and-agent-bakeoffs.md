# Model Watchlists and Agent Bakeoffs

Session-derived notes for scheduled research briefs that compare Hermes-supported models (for example current OpenAI/Codex default vs Claude/Fable candidates) or track whether a new model is producing materially different agent outcomes.

## When this applies

Use this reference when the user asks to:

- Compare Claude/Fable/OpenAI/Codex for Hermes or agent workflows.
- Add a model to a recurring research/watchlist brief.
- Decide whether a new model should become the Hermes default.
- Research whether people are seeing materially different outcomes from a new model.

## Evidence hierarchy

Prefer evidence in this order:

1. Direct same-prompt bakeoff in the user's Hermes environment, with model IDs/provider paths and actual outputs.
2. Provider docs/API metadata: context window, max output, tool support, structured outputs, image/file support, pricing, aliases.
3. Independent reproducible benchmark repos or public eval harnesses with prompts/results.
4. High-quality production case studies from credible users/teams.
5. GitHub ecosystem signals: repos, READMEs, update recency, stars/forks, license, issue activity.
6. Social/community anecdotes, clearly labeled as early/noisy.

Do not treat marketing claims, low-star demo repos, or a burst of new projects as proof that a model should replace the default.

## Recommended output shape

For a Hermes model comparison, produce:

- **Short answer:** switch / do not switch / test as specialist.
- **What was verified:** current provider/model config, accessible credentials/provider paths, and whether a live bakeoff was actually possible.
- **Model facts:** model ID, aliases, context, output cap, tool/structured-output support, modalities, pricing.
- **Outcome evidence:** distinguish direct local results from external reports and anecdotes.
- **Fit by task class:** routine chat/alerts, scheduled briefs, code review, large-context synthesis, personal-agent planning.
- **Recommendation:** default, specialist, monitor, or reject.
- **Next bakeoff:** 2–4 concrete representative tasks and success criteria.

## Direct bakeoff pattern

If credentials/provider access are available, run the same prompts against each model and compare:

- task completion quality
- tool-call discipline and safety
- factual grounding/citations
- latency
- input/output token cost
- user correction burden
- formatting quality for the delivery channel

If credentials are not available, say clearly that the result is a research/config review, not a live benchmark. Do not invent plausible-looking model outputs.

## Scheduling guidance

When adding a model to a recurring research brief:

- Keep it report-only unless the user explicitly approves configuration changes.
- Track whether there are **material Hermes/agent outcome reports**, not just benchmark hype.
- Include provider compatibility and permission/security implications.
- Recommend default-model changes only after direct bakeoff evidence or repeated strong external evidence.

## Example posture for a new agentic model

A newly released model with very large context, tool support, and claims around autonomous coding/knowledge work should usually be:

- **Monitor** if evidence is mostly marketing/demo activity.
- **Test as specialist** if provider access exists and the task class matches its strengths.
- **Not default yet** unless it wins representative local bakeoffs on quality, cost, latency, and safety.
