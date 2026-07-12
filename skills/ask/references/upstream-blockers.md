# Upstream blockers affecting the `ask` skill

Two hermes-platform limitations the ask skill currently works around. Each has a
**removal trigger**: when upstream fixes it, delete the noted workaround. Tracked
here (not an external issue tracker) so the workarounds don't calcify silently.
Both were confirmed 2026-07-11.

## 1. hermes-core crashes when dispatched from a `0700` cwd

**Symptom.** `hermes chat` dispatched with `cwd=` a directory it cannot fully
introspect dies with an uncaught `PermissionError` in
`/opt/hermes/agent/prompt_builder.py` (`_find_git_root` / `_load_hermes_md`) while
building the system prompt — before the model is ever called.

**Trigger in this skill.** `gate_driver.py`'s durable-gate mode uses
resumable-script, whose `journal_store` locks each state directory to mode `0700`.
An earlier `_live_models` passed `cwd=state_dir` into the model dispatch → **every**
live `--auto-answer` gate run crashed, not just one test case.

**A/B repro (confirmed).** Identical `hermes chat` invocation: crashes on a `0700`
cwd, succeeds on `0755`.

**Workaround (in place).** `gate_driver._live_models` does not pass a `cwd` — the
model's tools have no need to operate inside the durable state store. Locked in by
the `TestLiveModelsWiring` regression test (asserts no cwd / no state-dir path
reaches `dispatch_single`).

**Removal trigger.** When hermes-core's prompt builder tolerates an unreadable/`0700`
cwd (catches the `PermissionError` and degrades gracefully), the cwd-avoidance is no
longer load-bearing — though dispatching from a state store is still poor hygiene, so
keep it. The regression test stays regardless.

**Also recorded** in the `hermes-repo-sharp-edges` auto-memory (trap #4).

## 2. `hermes chat` has no per-call `--reasoning-effort` flag

**Symptom.** Reasoning effort is a global config key (`agent.reasoning_effort`), not a
per-invocation flag. Two concurrent dispatches at different `--thinking` levels would
race on that global.

**Trigger in this skill.** Comparison mode (`ask deepseek kimi … --thinking low`)
must set → dispatch → restore the global per model, so it **serializes** when a
thinking level is set instead of running the models in parallel (`model_utils.py`
`dispatch_comparison`, the `if thinking:` branch, ~lines 1007–1022). The parallel
path is only safe when no thinking level is set.

**Workaround (in place).** Serialize comparison dispatches whenever `thinking` is
set; warn on stderr. Verified absent upstream 2026-07-11 (blocked-upstream).

**Removal trigger.** When `hermes chat` gains a per-call `--reasoning-effort`
(or `-e`) flag, `dispatch_single` can pass it directly, the global set/restore dance
(and its `try/finally`) is unnecessary, and `dispatch_comparison` can run the
thinking path in parallel like the no-thinking path. Remove the serialization branch
and its stderr warning. The comparison-mode TODO in `SKILL.md` is annotated with the
same trigger.

---

### Side note — not a blocker (settled 2026-07-11)

The plan's Open Unknown about the investigator's "stale entrypoint path
(`/opt/data/hermes-agent/…` vs `/opt/data/skills/…`)" was investigated: `/opt/data/
hermes-agent` is the **upstream source repo** (its own git repo, per the top-level
README), carrying a second copy of the skills tree; the **deployed** investigator at
`/opt/data/skills/autonomous-ai-agents/investigator/` imports and runs cleanly. The
stale reference was a wrong-repo path, **not** a defect in this customization layer —
no fix needed here. Invoke via `/opt/data/skills/...`, never `/opt/data/hermes-agent/...`.
