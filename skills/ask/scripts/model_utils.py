#!/usr/bin/env python3
"""model_utils — Shared dispatch library for multi-model skills.

# Architecture
This is the SINGLE source of truth for model dispatch in the skill ecosystem.
All other scripts (ask.py, dev.py) import from here or call
this as a subprocess. Do not duplicate dispatch logic elsewhere.

# Data Flow
    Caller → dispatch_single() → hermes chat -q (subprocess) → clean_output() → dict
                ↓                        ↓
          build_prompt()           hermes config set
          (context + lang)         (thinking level, if specified)

# Key Decisions
- Uses subprocess (not HTTP) to call hermes chat — gets full agent loop (tools, skills)
- Thinking levels mutate global config (agent.reasoning_effort) — restored in finally
- Comparison mode serializes when --thinking is set (race condition on global config)
- Session registry is a JSON file at ~/.hermes/ask-sessions.json (no DB, no locking)
- Triage.py does NOT use this — it calls Ollama API directly (63x faster, no agent loop)

# Import Graph
    model_utils.py (this file)
        ↑ imported by
    ask.py (interactive CLI + aliases + sessions + comparison)
    dev.py (calls model_utils.py via subprocess)

# Usage
    # As a library:
    from model_utils import dispatch_single, resolve_alias
    r = dispatch_single("deepseek-v4-pro:cloud", "What is ACID?", "")
    print(r["content"])

    # As a CLI (same interface as model_utils CLI):
    python3 model_utils.py -m deepseek -p "What is ACID?" -o /tmp/out.md
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import unicodedata
from typing import Optional, Callable, Literal, TypedDict

# ── Dispatch event types ─────────────────────────────────────────────────────
class DispatchEvent(TypedDict, total=False):
    """Typed dictionary for dispatch events emitted via progress_callback.
    
    Fields:
        event: One of 'dispatch_start' | 'dispatch_end' | 'fallback' |
            'triage_done' | 'routing_decision' | 'dispatch_retry' |
            'devloop_start' | 'devloop_end' | 'auto_answer'.
        model: The full model name being dispatched.
        role: Optional role label.
        thinking: Optional reasoning effort level.
        timestamp: Unix timestamp when event was emitted (dispatch_start only).
        elapsed: Time in seconds (dispatch_end only).
        success: Whether dispatch succeeded (dispatch_end only).
        chars: Output character count (dispatch_end only).
        error: Error message if any (dispatch_end only).
        notice: Fallback notice emitted by Hermes (fallback only).
        category: Triage category (triage_done only).
        confidence: Triage confidence (triage_done only).
        skill: Routed skill name (routing_decision only).
        toolsets: Routed toolset list (routing_decision only).
        attempt: One-based failed dispatch attempt number (dispatch_retry only).
        reason: Truncated retry reason (dispatch_retry only).
        pipeline_mode: Devloop pipeline mode (devloop_start/devloop_end only).
        terminal: Optional devloop terminal outcome (devloop_end only).
        question: Clarifying question text (auto_answer only).
        answer: Generated answer (auto_answer only).
        round: One-based automatic answer round (auto_answer only).
        seam: 'gate' or 'freetext' (auto_answer only).
    """
    event: str
    model: str
    role: Optional[str]
    thinking: Optional[str]
    timestamp: float
    elapsed: float
    success: bool
    chars: int
    error: Optional[str]
    notice: Optional[str]
    category: str
    confidence: str
    skill: Optional[str]
    toolsets: Optional[str]
    attempt: int
    reason: str
    pipeline_mode: str
    terminal: Optional[str]
    question: str
    answer: str
    round: int
    seam: Literal["gate", "freetext"]

# ── Safe callback helper ────────────────────────────────────────────────────

def _safe_callback(cb, event_dict):
    """Invoke a progress callback, swallowing exceptions so the pipeline never crashes."""
    if cb:
        try:
            cb(event_dict)
        except Exception as e:
            print(f"Warning: progress_callback raised: {e}", file=sys.stderr)


def _make_stderr_event_callback() -> Callable:
    """Create a progress callback that writes JSONL events to stderr."""
    def _emit(event: dict):
        print(json.dumps(event, default=str), file=sys.stderr, flush=True)
    return _emit


# ── Constants ──────────────────────────────────────────────────────────────
# These are module-level so they can be patched in tests via mock.patch.

HERMES_BIN = os.environ.get("HERMES_BIN", "/opt/hermes/bin/hermes")
DEFAULT_PROVIDER = "ollama-glm"
DEFAULT_TIMEOUT = 3600  # 60 minutes — local models need more time
DEFAULT_TOOLSETS = "file,web"
DEFAULT_MAX_TURNS: Optional[int] = None  # None = defer to Hermes config (agent.max_turns)
BITWARDEN_PREFIX = "Bitwarden Secrets Manager"
SESSIONS_FILE = os.path.expanduser("~/.hermes/ask-sessions.json")
SESSION_TTL = 3600  # 1 hour in seconds — sessions older than this are expired


# ── Auto-answer helpers ────────────────────────────────────────────────────

def answer_fp(text) -> str:
    """Return a stable answer-artifact fingerprint.

    Faithfully ported from
    ``skills/autonomous-ai-agents/investigator/scripts/answerer.py`` so the
    ask skill can use the artifact-beats-stdout capture pattern without a
    cross-skill import cycle.
    """
    if text is None:
        normalized = "\0none"
    else:
        source = str(text)
        if source.isascii():
            normalized = re.sub(r"[^a-z0-9]+", " ", source.lower()).strip()
        else:
            folded = unicodedata.normalize("NFKC", source).casefold()
            normalized = " ".join(
                "".join(ch if ch.isalnum() else " " for ch in folded).split()
            )
        if not normalized:
            normalized = "\0empty:" + unicodedata.normalize("NFKC", source).casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def answer_artifact_path(run_dir, qtext) -> str:
    """Return the absolute per-question artifact path.

    This is the artifact-beats-stdout path ported from
    ``skills/autonomous-ai-agents/investigator/scripts/answerer.py``.
    """
    return os.path.abspath(os.path.join(run_dir, f"answer-{answer_fp(qtext)}.json"))


def read_answer_artifact(path) -> Optional[str]:
    """Read a non-empty ``answer`` string from an agent-written JSON artifact.

    This is the artifact-beats-stdout reader ported from
    ``skills/autonomous-ai-agents/investigator/scripts/answerer.py``. Missing,
    malformed, and empty artifacts deliberately fall back to dispatcher stdout.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"[ask] warn: artifact invalid JSON at {path}: {exc}", file=sys.stderr,
                  flush=True)
            return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    answer = obj.get("answer") if isinstance(obj, dict) else None
    return answer.strip() if isinstance(answer, str) and answer.strip() else None


def answer_artifact_instruction(path) -> str:
    """Build the agent instruction for the artifact-beats-stdout capture path.

    Ported from ``skills/autonomous-ai-agents/investigator/scripts/answerer.py``.
    """
    return (f"\n\nWhen you have your final answer, ALSO write EXACTLY one JSON object to "
            f'{path}: {{"answer": "<your 1-3 sentence answer, or NOT_FOUND: <reason>>"}}. '
            "Write the file even for NOT_FOUND — then reply with the same answer.")


def is_question_shaped(content) -> bool:
    """Return whether a plain-text model reply is a likely clarifying question.

    This deliberately cheap heuristic avoids treating generated code as a question:
    it only accepts a stripped reply ending in ``?`` that contains no code fence.
    """
    return isinstance(content, str) and "```" not in content and content.strip().endswith("?")


def generate_auto_answer(question_text, *, options=None, context="", answer_model,
                         provider=DEFAULT_PROVIDER, timeout=DEFAULT_TIMEOUT, run_dir=None,
                         progress_callback=None) -> dict:
    """Ask a model to answer a clarifying question for the caller.

    Artifact capture intentionally beats dispatcher stdout. A timed-out or
    misclassified dispatcher result can still have a durable answer file written
    by the agent, so that artifact is authoritative when present. Enum validation
    is left to the seam which owns the corresponding gate contract.
    """
    question = str(question_text or "").strip()
    option_list = list(options or [])
    prompt = (
        "You are answering a clarifying question on behalf of the caller. "
        "Answer decisively and concisely; prefer the reversible/standard option.\n\n"
        f"Clarifying question:\n{question}"
    )
    if option_list:
        prompt += ("\n\nThe permitted enum options are listed verbatim below. "
                   "Reply with EXACTLY one of them, preserving its spelling, and nothing "
                   "else — no punctuation, quotes, explanation, or preamble such as Answer:.\n"
                   + "\n".join(f"- {option}" for option in option_list))
    if context:
        prompt += f"\n\nAdditional caller context:\n{context}"

    artifact = answer_artifact_path(run_dir, question) if run_dir else None
    if artifact:
        prompt += answer_artifact_instruction(artifact)

    try:
        result = dispatch_single(
            resolve_alias(answer_model), prompt, "", "", None, timeout, provider,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        return {"answer": None, "error": str(exc)}

    answer = read_answer_artifact(artifact) if artifact else None
    if answer is None:
        content = result.get("content")
        answer = content.strip() if isinstance(content, str) and content.strip() else None
    if answer is not None:
        return {"answer": answer, "error": None}
    return {"answer": None, "error": result.get("error") or "empty response"}

# Models that default to non-English output — auto-append "respond in English only"
NON_ENGLISH_MODELS = {"glm-5.2:cloud", "glm-5.2", "glm-5.1:cloud"}

# Models that need /no_think prefix to suppress chain-of-thought reasoning.
# Qwen3 models may generate inline reasoning as regular content even with think:false.
# The /no_think directive is a training-time instruction placed as the first line
# of the prompt. Qwen3 models that respect it will skip chain-of-thought entirely.
#
# Model compatibility (tested 2026-06-27):
#   qwen3.6:35b-a3b  ✅ Respects think:false, /no_think optional. 3 tokens, 0.6s.
#   qwen3:14b        ✅ Respects think:false + /no_think. 3 tokens, 3.8s.
#   qwen3:1.7b       ✅ Respects think:false. 3 tokens, fast.
#   qwen3-coder-next ✅ Respects think:false. 3 tokens, fast.
#   qwen3:4b         ❌ Ignores /no_think in ALL positions (system msg, first line,
#                     last line, same line). Always reasons inline. Parser fallback
#                     (last-line extraction) catches correct category but at 200+ tokens.
#                     DO NOT use qwen3:4b for triage.
def needs_no_think(model: str) -> bool:
    """Check if model needs /no_think directive to suppress chain-of-thought.

    Args:
        model: Full model name (e.g., "qwen3.6:35b-a3b").

    Returns:
        True if 'qwen' appears in model name (case-insensitive), False otherwise.

    Side Effects: None — pure function.

    Dependencies: None.

    # NOTE: The /no_think directive is prepended as the first line of the user
    #       prompt by build_prompt(). Qwen3 models that respect it skip
    #       chain-of-thought entirely. qwen3:4b ignores it in ALL positions.
    """
    return "qwen" in model.lower()

# ── Thinking / Reasoning levels ─────────────────────────────────────────────
# Maps to Hermes agent.reasoning_effort config setting.
# Valid levels: hermes_constants.VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
# "none" is our addition — maps to {"enabled": False} in Hermes.
# PERF: Setting reasoning_effort is a global config mutation (not per-call).
#       This means parallel calls with different thinking levels will race.
#       See dispatch_comparison() for the serialization workaround.
# NOTE: get_reasoning_effort() is cached via lru_cache to avoid re-reading
#       the config file on every call. Cache is invalidated implicitly when
#       set_reasoning_effort() is called (different return value → new cache entry).
THINKING_LEVELS = {
    "none":     "Disable reasoning entirely. Fastest, cheapest. Good for simple queries.",
    "minimal":  "Bare minimum reasoning. Quick responses with slight deliberation.",
    "low":      "Light reasoning. Good balance for most quick questions.",
    "medium":   "Moderate reasoning. Default for general-purpose tasks.",
    "high":     "Deep reasoning. Good for complex analysis, code review, architecture.",
    "xhigh":    "Maximum reasoning. For very hard problems, proofs, deep analysis.",
}

# ── Alias Registry ─────────────────────────────────────────────────────────
# Short names → full model IDs. Case-insensitive lookup via resolve_alias().
# To add a new model: add an entry here. No other code changes needed.
# Categories: reasoning, code, general, fast-local, dev-roles

ALIASES = {
    # Reasoning models
    "deepseek":       "deepseek-v4-pro:cloud",
    "deepseek-pro":   "deepseek-v4-pro:cloud",
    "deepseek-flash": "deepseek-v4-flash:cloud",
    "ds":             "deepseek-v4-pro:cloud",
    "dsp":            "deepseek-v4-pro:cloud",
    # Code models
    "kimi":           "kimi-k2.7-code:cloud",
    "kimi-k2":        "kimi-k2.7-code:cloud",
    "kimi-coder":     "kimi-k2.7-code:cloud",
    "qwen":           "qwen3.6:35b-a3b",
    "qwen-coder":     "qwen3-coder-next:q4_K_M",
    "qwen-local":     "qwen3.6:35b-a3b",
    # General models
    "glm":            "glm-5.2:cloud",
    "glm-5":          "glm-5.2:cloud",
    # Other useful models
    "phi":            "phi4-reasoning:plus",
    "phi-reasoning":  "phi4-reasoning:plus",
    "minimax":        "minimax-m3:cloud",
    "minimax-m3":     "minimax-m3:cloud",
    "mm":             "minimax-m3:cloud",
    "mm3":            "minimax-m3:cloud",
    "devstral":       "devstral-small-2:24b-cloud",
    "gpt-oss":        "gpt-oss:120b",
    "llama":          "llama4:scout",
    # Local standard — Qwen 3.6 35B MoE (114 tok/s, 4.4s wall, 5x faster than Gemma4)
    "fast":           "qwen3.6:35b-a3b",
    "local":          "qwen3.6:35b-a3b",
    "gemma":          "gemma4:12b-mlx-bf16",
    # Dev role aliases (from dev skill — map roles to best models)
    "planner":        "glm-5.2:cloud",
    "coder":          "qwen3-coder-next:q4_K_M",
    "qa-tester":      "qwen3-coder-next:q4_K_M",
    "qa":             "qwen3-coder-next:q4_K_M",
    # P9: Debugger cascade — qwen-coder is primary (fast, local), kimi is fallback (stronger, cloud)
    "debugger":       "qwen3-coder-next:q4_K_M",      # Primary debugger — fast, local
    "debugger-fallback": "kimi-k2.7-code:cloud",       # Fallback debugger — stronger, cloud
    "test-planner":   "deepseek-v4-pro:cloud",         # Test planning — strong structured output
    # Documentation specialist — strong instruction following for structured docs
    "tech-docs":      "qwen3-coder-next:q4_K_M",
    "docs":           "qwen3-coder-next:q4_K_M",
}


# ── Alias resolution ────────────────────────────────────────────────────────


def resolve_alias(name: str) -> str:
    """Resolve a short alias to a full model ID.

    Args:
        name: Alias (e.g., "deepseek") or full model name (e.g., "deepseek-v4-pro:cloud").
    Returns:
        Full model name. If name is not a known alias, returns it unchanged.
    Side Effects: None — pure function, reads static ALIASES dict.
    Dependencies: ALIASES module-level dict.
    """
    return ALIASES.get(name.lower(), name)


# ── Fuzzy alias resolution ───────────────────────────────────────────────────
# Two-tier: exact dict match (instant, free) → fast local LLM fuzzy match (fallback).
# The fuzzy fallback uses the raw Ollama API (~0.5s) to ask the fast model to map
# an unknown alias to the closest known model in the registry.

# Cache for fuzzy resolutions to avoid repeated LLM calls for the same input.
_fuzzy_cache: dict[str, str] = {}
_fuzzy_cache_lock = threading.Lock()

# The fast local model used for fuzzy resolution (~0.5s via raw Ollama API).
FUZZY_RESOLVER_MODEL = "qwen3.6:35b-a3b"
FUZZY_RESOLVER_TIMEOUT = 10  # seconds — fuzzy match should be fast or fail gracefully


def _build_fuzzy_prompt(user_input: str, known_aliases: list[str]) -> str:
    """Build the prompt for the fuzzy resolver LLM.

    Args:
        user_input: The unrecognized model string from the user.
        known_aliases: Sorted list of known alias names.
    Returns:
        Prompt string for the LLM.
    """
    aliases_formatted = "\n".join(f"  - {a}" for a in known_aliases)
    return (
        "/no_think\n"
        "You are a model name resolver. The user typed a model name that is not an exact match.\n"
        "Map it to the closest known alias from the list below.\n\n"
        f"User typed: \"{user_input}\"\n\n"
        f"Known aliases:\n{aliases_formatted}\n\n"
        "Rules:\n"
        "1. Return ONLY the closest alias from the list — nothing else.\n"
        "2. If no alias is a reasonable match, return exactly: NONE\n"
        "3. Match by brand name, model family, version number, or common abbreviation.\n"
        "4. Examples: 'minimax-v3' → 'minimax-m3', 'ds-pro' → 'deepseek-pro', 'qw' → 'qwen'\n"
        "5. Respond in English only.\n"
    )


def _fuzzy_resolve_raw(user_input: str, known_aliases: list[str]) -> Optional[str]:
    """Call the fast local model via raw Ollama API to fuzzy-match an alias.

    Args:
        user_input: The unrecognized model string.
        known_aliases: Sorted list of known alias names.
    Returns:
        Matched alias string, or None if no match / API error.
    Side Effects:
        - HTTP POST to Ollama API (~0.5s).
    Dependencies:
        - Ollama running at host.docker.internal:11434 (or OLLAMA_URL env var).
    """
    prompt = _build_fuzzy_prompt(user_input, known_aliases)
    ollama_url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434/api/chat")
    data = json.dumps({
        "model": FUZZY_RESOLVER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 50},
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            ollama_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=FUZZY_RESOLVER_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result["message"]["content"].strip()
    except Exception:
        return None  # Network error, timeout, Ollama down — fail gracefully

    # Clean up the response — extract just the alias name
    content = content.strip().strip('"').strip("'").strip(".")
    if content.upper() == "NONE":
        return None

    # Verify the LLM's answer is actually a known alias (prevent hallucination)
    if content.lower() in {a.lower() for a in known_aliases}:
        return content

    # LLM returned something not in the list — try case-insensitive match
    for a in known_aliases:
        if a.lower() == content.lower():
            return a

    return None  # Hallucinated response — reject


def resolve_alias_fuzzy(name: str) -> tuple[str, bool]:
    """Resolve an alias with exact match first, then LLM fuzzy fallback.

    Two-tier resolution:
    1. Exact match in ALIASES dict (instant, free, deterministic).
    2. If no exact match, ask the fast local LLM to fuzzy-match it (~0.5s).
    3. If the LLM also can't match, return the original name unchanged.

    Args:
        name: Alias or model name to resolve.
    Returns:
        Tuple of (resolved_model, was_fuzzy).
        - resolved_model: Full model name.
        - was_fuzzy: True if the LLM fuzzy resolver was used, False for exact match.
    Side Effects:
        - May cache the fuzzy result in _fuzzy_cache for future calls.
        - May call Ollama API if no exact match and not cached.
    Dependencies:
        - ALIASES dict for exact match.
        - Ollama API for fuzzy fallback (via _fuzzy_resolve_raw).
    """
    # Tier 1: Exact match (instant)
    exact = ALIASES.get(name.lower())
    if exact:
        return exact, False

    # Already a full model name (contains ':' and no spaces) — return as-is
    if ":" in name and " " not in name:
        return name, False

    # Tier 2: Check fuzzy cache
    with _fuzzy_cache_lock:
        if name.lower() in _fuzzy_cache:
            return _fuzzy_cache[name.lower()], True

    # Tier 3: LLM fuzzy resolution
    known = sorted(ALIASES.keys())
    matched = _fuzzy_resolve_raw(name, known)
    if matched:
        resolved = ALIASES[matched.lower()]
        with _fuzzy_cache_lock:
            _fuzzy_cache[name.lower()] = resolved
        return resolved, True

    # No match anywhere — return original name unchanged
    return name, False


def is_known_model(name: str) -> bool:
    """Check if a string is a known alias or a full model name.

    Used by ask.py's CLI parser to distinguish model aliases from prompt text.
    A "full model name" contains ':' and no spaces (e.g., "model:tag").

    Args:
        name: String to check.
    Returns:
        True if name is a registered alias or matches the "word:word" pattern.
    Side Effects: None — pure function, reads static ALIASES dict.
    Dependencies: ALIASES module-level dict.
    """
    if name.lower() in ALIASES:
        return True
    return ":" in name and " " not in name


# ── Thinking / Reasoning ────────────────────────────────────────────────────

_reasoning_effort_cache = None
_reasoning_effort_loaded = False
# NOTE: Thread lock for reasoning_effort cache. Prevents races when
#       dispatch_comparison() runs parallel threads that all call
#       get_reasoning_effort() simultaneously. The lock makes the
#       check-and-set atomic so only one thread reads the config file.
_reasoning_effort_lock = threading.Lock()


def _invalidate_reasoning_effort_cache():
    """Reset the reasoning_effort cache. Useful for tests."""
    global _reasoning_effort_cache, _reasoning_effort_loaded
    with _reasoning_effort_lock:
        _reasoning_effort_cache = None
        _reasoning_effort_loaded = False


def get_reasoning_effort() -> str:
    """Read the current agent.reasoning_effort from the Hermes config file.

    Parses config.yaml directly (no yaml dependency — uses line scanning).
    Looks for `reasoning_effort:` under the `agent:` section.

    Returns:
        Effort level string (e.g., "high", "none", "") or "" if not set/error.
    Side Effects:
        - Reads config file from disk (no writes).
        - Caches result in module-level variable to avoid re-reading on every call.
        - Cache is reset by _invalidate_reasoning_effort_cache() (called by set_reasoning_effort).
    Dependencies:
        - ~/.hermes/config.yaml (falls back to /opt/data/config.yaml).
        - System Python has no `yaml` module — uses manual regex/line parsing.
    # PERF: O(n) line scan on first call only — subsequent calls return cached value (~0ms).
    """
    global _reasoning_effort_cache, _reasoning_effort_loaded
    with _reasoning_effort_lock:
        if _reasoning_effort_loaded:
            return _reasoning_effort_cache
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_path):
        config_path = "/opt/data/config.yaml"
    try:
        with open(config_path) as f:
            in_agent = False
            for line in f:
                stripped = line.rstrip()
                if stripped.startswith("agent:"):
                    in_agent = True
                    continue
                # End of agent: section at next top-level key
                if in_agent and stripped and not stripped.startswith(" ") and not stripped.startswith("#"):
                    in_agent = False
                if in_agent and "reasoning_effort" in stripped and ":" in stripped:
                    val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    if val:
                        with _reasoning_effort_lock:
                            _reasoning_effort_cache = val.lower()
                            _reasoning_effort_loaded = True
                        return _reasoning_effort_cache
    except Exception:
        pass
    with _reasoning_effort_lock:
        _reasoning_effort_cache = ""
        _reasoning_effort_loaded = True
    return ""


def set_reasoning_effort(level: str) -> bool:
    """Set agent.reasoning_effort via `hermes config set` subprocess.

    Args:
        level: One of THINKING_LEVELS keys (none/minimal/low/medium/high/xhigh).
    Returns:
        True if hermes config set succeeded, False otherwise.
    Side Effects:
        MUTATES the global Hermes config file (agent.reasoning_effort).
        This affects ALL concurrent hermes processes — see RACE note in
        dispatch_comparison().
        INVALIDATES the get_reasoning_effort() cache so the next read
        picks up the new value.
    Dependencies: HERMES_BIN must be reachable.
    """
    global _reasoning_effort_loaded
    if level not in THINKING_LEVELS:
        return False
    try:
        result = subprocess.run(
            [HERMES_BIN, "config", "set", "agent.reasoning_effort", level],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            # Invalidate cache so next get_reasoning_effort() re-reads config
            _reasoning_effort_loaded = False
        return result.returncode == 0
    except Exception:
        return False


# ── Output cleaning ────────────────────────────────────────────────────────


def clean_output_full(raw: str) -> tuple[str, Optional[str], Optional[str]]:
    """Strip CLI noise from hermes chat output.

    Removes these line patterns:
    - "Bitwarden Secrets Manager ..." (secrets warning prefix)
    - "Warning: Unknown toolsets: ..." (toolset warnings)
    - "session_id: <id>" (extracted and returned separately)
    - Hermes fallback notices containing "Primary auth failed" or
      "Primary model failed" (first full notice line returned separately)

    Args:
        raw: Raw stdout or stderr from `hermes chat -q`.
    Returns:
        Tuple of (cleaned_content, session_id, fallback_notice). session_id and
        fallback_notice are None if not found. fallback_notice preserves the full
        original notice line, including any leading emoji.
    Side Effects: None — pure function, no I/O.

    # NOTE: When multiple session_id lines appear, the LAST one wins.
    #       Unicode/emoji content is preserved (no encoding changes).
    # NOTE: raw can be None when subprocess.run returns None for stdout/stderr
    #       in certain failure modes. Guard with (raw or "") to prevent crash.
    """
    raw = (raw or "").strip()
    lines = raw.split("\n") if raw else []
    kept = []
    session_id = None
    fallback_notice = None
    for line in lines:
        if line.startswith(BITWARDEN_PREFIX):
            continue
        if line.startswith("Warning: Unknown toolsets:"):
            continue
        sid_match = re.match(r'^session_id:\s*(\S+)', line)
        if sid_match:
            session_id = sid_match.group(1)
            continue
        if "Primary auth failed" in line or "Primary model failed" in line:
            if fallback_notice is None:
                fallback_notice = line
            continue
        kept.append(line)
    return "\n".join(kept).strip(), session_id, fallback_notice


def clean_output(raw: str) -> tuple[str, Optional[str]]:
    """Strip CLI noise from hermes chat output, returning content and session ID.

    This compatibility wrapper preserves the public two-tuple API. Fallback notices
    are stripped from content; callers needing the notice should use clean_output_full.
    """
    content, session_id, _ = clean_output_full(raw)
    return content, session_id


# ── API error detection ────────────────────────────────────────────────────

# Patterns that indicate the content is an API error, not a model response.
# Must match 2+ patterns to be confident (a single "429" could appear in code).
_API_ERROR_PATTERNS = [
    re.compile(r'API call failed', re.IGNORECASE),
    re.compile(r'HTTP \d{3}', re.IGNORECASE),
    re.compile(r'Error code: \d{3}', re.IGNORECASE),
    re.compile(r'retries? exhausted', re.IGNORECASE),
    re.compile(r'rate limit', re.IGNORECASE),
    re.compile(r'\b429\b'),
    re.compile(r'extra usage auto reload', re.IGNORECASE),
    re.compile(r'monthly max reached', re.IGNORECASE),
    re.compile(r'connection refused', re.IGNORECASE),
]


def is_api_error(text: str) -> bool:
    """Detect if a model response is actually an API error message, not code.

    hermes chat -q sometimes prints API errors to stdout (which becomes the
    'content' field in dispatch_single's return dict). This catches common
    error patterns so callers don't try to execute error messages as code.

    Args:
        text: The content string from dispatch_single's return dict.

    Returns:
        True if the text matches 2+ API error patterns.
        False for normal code/responses (even if they contain "429" as a number).

    Side Effects: None — pure function.
    """
    if not text or len(text) < 10:
        return False
    matches = sum(1 for p in _API_ERROR_PATTERNS if p.search(text))
    return matches >= 2


# ── Prompt building ────────────────────────────────────────────────────────


def build_prompt(prompt: str, context: str, model: str, english_only: bool = False) -> str:
    """Assemble the full prompt with context and English-language directive.

    Layout:
        [/no_think\n\n]             ← only for Qwen models (suppresses chain-of-thought)
        <prompt text>

        CONTEXT:
        <context text>

        respond in English only    ← only if model is non-English or english_only=True

    Args:
        prompt: The main prompt/question text.
        context: Optional context to append (file contents, previous output, etc.).
        model: Full model name — used to check NON_ENGLISH_MODELS and needs_no_think().
        english_only: Force English directive even for English models.
    Returns:
        Assembled prompt string.
    Side Effects: None — pure function.
    Dependencies: needs_no_think(), NON_ENGLISH_MODELS.
    """
    parts = []
    # Qwen3 models: prepend /no_think to suppress chain-of-thought reasoning.
    # This is a training-time directive that Qwen3 respects in the prompt.
    if needs_no_think(model):
        parts.append("/no_think\n\n")
    parts.append(prompt)
    if context:
        parts.append(f"\n\nCONTEXT:\n{context}")
    if english_only or model in NON_ENGLISH_MODELS:
        # P1-F: Qualify the English directive so models don't refuse non-English
        # variable names or string literals in code. The directive applies to
        # conversational output, not code identifiers.
        parts.append("\n\nrespond in English only (code identifiers and string literals may use other languages as needed)")
    return "".join(parts)


# ── Session management ────────────────────────────────────────────────────


def clean_expired_sessions() -> int:
    """Remove sessions older than SESSION_TTL from the registry.

    Args: None
    Returns:
        Count of expired sessions removed. 0 if file missing/corrupt or no expirations.
    Side Effects:
        Reads and writes SESSIONS_FILE. Removes expired entries in-place.
        Logically equivalent to compacting a log file — O(n) scan, O(1) extra space.

    PERF: O(n) scan of sessions on every save — acceptable for <100 sessions
    """
    if not os.path.exists(SESSIONS_FILE):
        return 0
    try:
        with open(SESSIONS_FILE) as f:
            registry = json.load(f)
    except (json.JSONDecodeError, IOError):
        # Corrupt file — nothing to clean
        return 0

    now = time.time()
    removed = 0
    expired_aliases = []
    for alias, info in registry.items():
        ts_str = info.get("timestamp", "")
        try:
            # Parse timestamp in format "%Y-%m-%d %H:%M:%S"
            ts = time.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            ts_epoch = time.mktime(ts)
            if now - ts_epoch > SESSION_TTL:
                expired_aliases.append(alias)
        except (ValueError, TypeError):
            # Invalid timestamp — treat as expired
            expired_aliases.append(alias)

    for alias in expired_aliases:
        del registry[alias]
        removed += 1

    if removed > 0:
        tmp_path = SESSIONS_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(registry, f, indent=2)
        os.replace(tmp_path, SESSIONS_FILE)

    return removed


def _remove_session(alias: str):
    """Remove a session entry from the registry (stale/invalid session cleanup).

    Args:
        alias: Alias key (case-insensitive, stored lowercase).
    Side Effects:
        Reads + writes SESSIONS_FILE. No-op if file or entry doesn't exist.
    Dependencies: SESSIONS_FILE (~/.hermes/ask-sessions.json).
    """
    if not os.path.exists(SESSIONS_FILE):
        return
    try:
        with open(SESSIONS_FILE) as f:
            registry = json.load(f)
        if alias.lower() in registry:
            del registry[alias.lower()]
            tmp_path = SESSIONS_FILE + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(registry, f, indent=2)
            os.replace(tmp_path, SESSIONS_FILE)
    except (json.JSONDecodeError, IOError):
        pass


def save_session(alias: str, model: str, session_id: str, prompt_preview: str):
    """Save a session ID to the JSON registry for later resumption.

    The registry is a flat JSON file at SESSIONS_FILE (~/.hermes/ask-sessions.json).
    Each alias maps to one session (latest wins — overwrites previous).

    Args:
        alias: Alias key (case-insensitive, stored lowercase).
        model: Full model name for this session.
        session_id: The session ID from hermes chat --pass-session-id.
        prompt_preview: First 200 chars of the prompt (truncated automatically).
    Side Effects:
        Reads + writes SESSIONS_FILE. Creates parent dir if missing.
        Uses atomic write (temp + rename) to prevent corruption from
        parallel saves.
    # RACE: Atomic rename prevents data corruption. Parallel reads may
    #       see the old or new file, but never a truncated one.
    """
    registry = {}
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE) as f:
                registry = json.load(f)
        except (json.JSONDecodeError, IOError):
            # Corrupt file — start fresh
            pass
    registry[alias.lower()] = {
        "model": model,
        "session_id": session_id,
        "prompt_preview": prompt_preview[:200],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
    # Atomic write: write to temp file, then rename (rename is atomic on POSIX).
    tmp_path = SESSIONS_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(registry, f, indent=2)
    os.replace(tmp_path, SESSIONS_FILE)


def get_session(alias: str) -> dict:
    """Look up a saved session by alias.

    Args:
        alias: Case-insensitive alias key.
    Returns:
        Dict with keys: model, session_id, prompt_preview, timestamp.
        Empty dict {} if file missing, alias not found, or JSON corrupt.
    Side Effects:
        - Reads SESSIONS_FILE from disk (no writes).
    Dependencies: SESSIONS_FILE (~/.hermes/ask-sessions.json).
    """
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE) as f:
            registry = json.load(f)
        return registry.get(alias.lower(), {})
    except (json.JSONDecodeError, IOError):
        return {}


# ── Dispatch ───────────────────────────────────────────────────────────────


def dispatch_single(model: str, prompt: str, context: str, toolsets: str,
                    max_turns: Optional[int], timeout: int, provider: str,
                    output_file: Optional[str] = None, resume_session: Optional[str] = None,
                    alias: Optional[str] = None, thinking: Optional[str] = None,
                    english_only: bool = False, role: Optional[str] = None,
                    progress_callback: Optional[Callable] = None,
                    cwd: Optional[str] = None) -> dict:
    """Dispatch a single model call via `hermes chat -q` subprocess.

    This is the CORE function of the entire skill ecosystem. Every model call
    goes through here (except triage, which uses direct Ollama API).

    The call runs a full Hermes agent: system prompt, tools, skills, multi-turn
    reasoning. This is NOT a raw API call — it's a full agent loop.

    Args:
        model: Full model name (e.g., "deepseek-v4-pro:cloud").
        prompt: The prompt text to send.
        context: Optional context appended to prompt via build_prompt().
        toolsets: Comma-separated toolsets (e.g., "file,web,terminal"). Empty = none.
        max_turns: Max tool-calling iterations for the agent. None = use Hermes
            config default (agent.max_turns), don't pass --max-turns flag.
        timeout: Subprocess timeout in seconds.
        provider: Hermes provider name (e.g., "ollama-glm").
        output_file: If set, write response to this file with metadata header.
        resume_session: If set, pass --resume <session_id> to hermes chat.
        alias: If set (and session_id captured), save session to registry.
        thinking: If set, set agent.reasoning_effort before call, restore after.
        role: If set, inject a role directive into the prompt context (P2).
              E.g., role='debugger' prepends "You are acting as a debugger."
              This is used because hermes chat has no --role CLI flag.
        cwd: If set, run the hermes chat subprocess with this working directory.
             This is critical for v6 orchestrator — the model's terminal/file
             tools will operate in this directory, so file writes go to the right place.

    Returns:
        Every return path returns a dict with keys content, session_id, elapsed,
        error, thinking, and fallback. content is None iff error is not None. The
        empty-output return path additionally carries returncode. Setup failures
        before the subprocess boundary (role/prompt construction and the
        set_reasoning_effort config mutation) raise rather than return a dict.

    Side Effects:
        - MUTATES global config if thinking is set (set → call → restore in finally).
        - WRITES to SESSIONS_FILE if alias + session_id captured.
        - WRITES to output_file if specified.

    # RACE: If thinking is set and multiple dispatch_single calls run in parallel,
    # they will race on agent.reasoning_effort. Use dispatch_comparison() which
    # serializes when thinking is set.
    """
    # P2: Inject role directive into context (hermes chat has no --role flag).
    # P1-D FIX: Role/persona is prepended to context (placed BEFORE the user prompt
    # in build_prompt's layout) so it has more priming power. Previously role was
    # appended to context which appears AFTER the prompt text.
    # E.g., role='debugger' → "You are acting as a debugger. Focus on finding
    # and fixing bugs, not writing new code."
    if role:
        role_directive = f"You are acting as a {role}."
        if role == 'debugger':
            role_directive += " Focus on finding and fixing bugs, not writing new code."
        # Prepend role to context so it appears before the user prompt
        context = (role_directive + "\n\n" + context) if context else role_directive

    full_prompt = build_prompt(prompt, context, model, english_only)

    # Build the hermes chat subprocess command.
    # NOTE: Using a list (not shell=True) prevents command injection.
    # The model/prompt values are passed as separate list elements.
    cmd = [
        HERMES_BIN, "chat",
        "-q", full_prompt,
        "-m", model,
        "--provider", provider,
        "-Q", "--yolo",           # -Q = quiet (stdout only), --yolo = no approval prompts
        "--pass-session-id",       # Include session_id in output for capture
    ]
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    if toolsets:
        cmd.extend(["-t", toolsets])
    if resume_session:
        cmd.extend(["--resume", resume_session])

    # Apply thinking level if specified.
    # PERF: This adds ~1s overhead (two hermes config subprocess calls).
    # The set/restore is wrapped in try/finally to guarantee restoration
    # even on timeout, exception, or SIGTERM.
    original_effort = None
    if thinking:
        original_effort = get_reasoning_effort()
        set_reasoning_effort(thinking)

    _safe_callback(progress_callback, {
        'event': 'dispatch_start', 'model': model,
        'role': role, 'thinking': thinking or 'default',
        'timestamp': time.time(),
    })

    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        elapsed = time.time() - start
        content, session_id, fallback = clean_output_full(result.stdout)

        # Session ID may be in stderr (quiet mode puts it there); parse stderr
        # regardless so a fallback notice there is never lost.
        _, stderr_session_id, stderr_fallback = clean_output_full(result.stderr)
        if not session_id:
            session_id = stderr_session_id
        if fallback is None:
            fallback = stderr_fallback

        # FALLBACK: If --resume failed with "Session not found", retry fresh.
        # This handles stale session IDs in the registry from crashed/expired
        # sessions. We strip --resume from the command and re-run.
        # NOTE: We also clean up the stale alias entry to prevent future retries.
        # PERF: Retry timeout is capped to the REMAINING time budget so the
        #       worst case is `timeout` seconds, not `2 * timeout`.
        if not content and resume_session and "Session not found" in result.stderr:
            # Remove --resume <id> from the command
            fresh_cmd = [c for i, c in enumerate(cmd)
                         if not (c == "--resume" or
                                 (i > 0 and cmd[i-1] == "--resume"))]
            # Clean up stale session entry
            if alias:
                _remove_session(alias)
            # Retry without --resume, using remaining time budget
            remaining_timeout = max(5, int(timeout - elapsed))
            start = time.time()
            result = subprocess.run(
                fresh_cmd, capture_output=True, text=True, timeout=remaining_timeout, cwd=cwd
            )
            elapsed = time.time() - start
            content, session_id, stdout_fallback = clean_output_full(result.stdout)
            if fallback is None:
                fallback = stdout_fallback
            _, stderr_session_id, stderr_fallback = clean_output_full(result.stderr)
            if not session_id:
                session_id = stderr_session_id
            if fallback is None:
                fallback = stderr_fallback
            resume_session = None  # Don't re-save to stale entry path

        # P1 fix: Detect API errors that hermes chat prints to stdout.
        # These look like content but are actually error messages (429, 500, etc).
        # Convert them to proper error returns so callers don't execute them as code.
        if content and is_api_error(content):
            if fallback:
                _safe_callback(progress_callback, {
                    'event': 'fallback', 'model': model, 'notice': fallback,
                })
            _safe_callback(progress_callback, {
                'event': 'dispatch_end', 'model': model,
                'elapsed': elapsed, 'success': False, 'chars': 0,
                'error': f'API error: {content[:500]}',
            })
            return {
                "content": None,
                "session_id": session_id,
                "elapsed": elapsed,
                "error": f"API error: {content[:500]}",
                "thinking": thinking or "default",
                "fallback": fallback,
            }

        if not content:
            empty_output_error = (
                f"Empty output (exit {result.returncode}). stderr: {result.stderr[:500]}"
            )
            if fallback:
                _safe_callback(progress_callback, {
                    'event': 'fallback', 'model': model, 'notice': fallback,
                })
            _safe_callback(progress_callback, {
                'event': 'dispatch_end', 'model': model,
                'elapsed': elapsed, 'success': False, 'chars': 0,
                'error': empty_output_error,
            })
            return {
                "content": None,
                "session_id": session_id,
                "elapsed": elapsed,
                "error": empty_output_error,
                "thinking": thinking or "default",
                "fallback": fallback,
                "returncode": result.returncode,
            }

        if fallback:
            _safe_callback(progress_callback, {
                'event': 'fallback', 'model': model, 'notice': fallback,
            })
        _safe_callback(progress_callback, {
            'event': 'dispatch_end', 'model': model,
            'elapsed': elapsed, 'success': True,
            'chars': len(content), 'error': None,
        })

        # Save session if we captured an ID and have an alias key.
        # Skip when resuming — the session already exists in the registry.
        if session_id and not resume_session and alias:
            save_session(alias, model, session_id, prompt)

        # Write to file with metadata header (for pipeline use)
        if output_file:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            header = (
                f"<!--\nmodel: {model}\nprovider: {provider}\n"
                f"elapsed: {elapsed:.1f}s\nchars: {len(content)}\n"
                f"session_id: {session_id or 'none'}\n"
                f"thinking: {thinking or 'default'}\n"
                f"-->\n\n"
            )
            with open(output_file, "w") as f:
                f.write(header + content)

        return {
            "content": content,
            "session_id": session_id,
            "elapsed": elapsed,
            "error": None,
            "thinking": thinking or "default",
            "fallback": fallback,
        }
    except subprocess.TimeoutExpired:
        _safe_callback(progress_callback, {
            'event': 'dispatch_end', 'model': model,
            'elapsed': time.time() - start, 'success': False, 'chars': 0,
            'error': f'Timed out after {timeout}s',
        })
        return {
            "content": None,
            "session_id": None,
            "elapsed": time.time() - start,
            "error": f"Timed out after {timeout}s",
            "thinking": thinking or "default",
            "fallback": None,
        }
    except Exception as e:
        _safe_callback(progress_callback, {
            'event': 'dispatch_end', 'model': model,
            'elapsed': time.time() - start, 'success': False, 'chars': 0,
            'error': str(e),
        })
        return {
            "content": None,
            "session_id": None,
            "elapsed": time.time() - start,
            "error": str(e),
            "thinking": thinking or "default",
            "fallback": None,
        }
    finally:
        # Restore original reasoning effort — ALWAYS runs, even on error/timeout.
        # NOTE: If the process is SIGKILLed, this won't run and config is left
        # in the thinking state. Acceptable tradeoff — the user can manually fix.
        # NOTE: If original_effort was empty/unset (""), we SKIP the restore
        #       because: (a) set_reasoning_effort("") returns False (invalid),
        #       and (b) writing "none" would permanently change the user's config
        #       from "unset" to "none". Instead we leave the thinking level in
        #       place — the user can manually `hermes config set` to clear it.
        # PERF: Only restore when original was a valid thinking level (not "").
        if thinking and original_effort:
            set_reasoning_effort(original_effort)


def dispatch_comparison(models: list, prompt: str, context: str, toolsets: str,
                        max_turns: Optional[int], timeout: int, provider: str,
                        thinking: Optional[str] = None,
                        progress_callback: Optional[Callable] = None) -> list:
    """Dispatch the same prompt to multiple models, return all results.

    Execution mode depends on --thinking:
        Without thinking: PARALLEL via ThreadPoolExecutor (fastest).
        With thinking:    SEQUENTIAL (avoids race on global reasoning_effort).

    Args:
        models: List of full model names to dispatch to.
        prompt: The prompt text (same for all models).
        context: Optional context (same for all models).
        toolsets: Comma-separated toolsets (same for all models).
        max_turns: Max agent turns per model. None = use Hermes config default.
        timeout: Per-model timeout in seconds.
        provider: Hermes provider name.
        thinking: If set, forces sequential execution (see RACE note).

    Returns:
        List of dispatch_single result dicts, sorted by original model order.
        Each dict has an added "model" key.

    Side Effects:
        - When thinking is set: prints a warning to stderr about serialization.
        - When thinking is set: mutates global config N times (set → call → restore × N).

    # RACE: The global agent.reasoning_effort config cannot be set per-thread.
    # Parallel calls with different thinking levels would stomp on each other.
    # Workaround: serialize when thinking is set. The proper fix is a
    # `--reasoning-effort` CLI flag on hermes chat (TODO, not yet implemented).
    """
    import concurrent.futures
    results = []

    if thinking:
        # Sequential path: each call sets → runs → restores before the next.
        # SLOWER but correct. N models × ~timeout seconds worst case.
        print(f"  ⚠️  --thinking {thinking}: running sequentially (not parallel) "
              f"to avoid reasoning_effort race condition. "
              f"{len(models)} models × ~{timeout}s max each.",
              file=sys.stderr)
        for model in models:
            r = dispatch_single(
                model, prompt, context, toolsets,
                max_turns, timeout, provider, None, None, None,
                thinking=thinking,
                progress_callback=progress_callback,
            )
            r["model"] = model
            results.append(r)
    else:
        # Parallel path: no thinking → no config mutation → safe to run concurrently.
        # PERF: N models run in ~max(model_times) instead of sum(model_times).
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = {
                pool.submit(
                    dispatch_single, model, prompt, context, toolsets,
                    max_turns, timeout, provider, None, None, None,
                    thinking=None,
                    progress_callback=progress_callback,
                ): model
                for model in models
            }
            for future in concurrent.futures.as_completed(futures):
                model = futures[future]
                r = future.result()
                r["model"] = model
                results.append(r)

    # Sort by original model order (not completion order)
    order = {m: i for i, m in enumerate(models)}
    results.sort(key=lambda r: order.get(r["model"], 99))
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    """CLI entry point — prompts a Hermes model, writes output to a file.

    Same flags as the model_utils CLI, plus --thinking.
    Used by dev.py (via subprocess) and by ask.py (via import).

    Exit codes:
        0 = success
        1 = error (message to stderr)
        2 = timeout (unused — dispatch_single returns error dict instead)
    """
    import argparse
    parser = argparse.ArgumentParser(
        description="model_utils — prompt a Hermes model, write output to a file"
    )
    parser.add_argument("-m", "--model", required=True, help="Model name or alias (e.g., deepseek, deepseek-v4-pro:cloud)")
    parser.add_argument("-p", "--prompt", required=True, help="The prompt text")
    parser.add_argument("--context", default="", help="Context to include after the prompt")
    parser.add_argument("-c", "--context-file", help="Read context from a file (overrides --context)")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument("-t", "--toolsets", default="", help="Comma-separated toolsets (e.g., file,web,terminal)")
    parser.add_argument("-s", "--skills", default="", help="Comma-separated skills to preload")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help=f"Provider name (default: {DEFAULT_PROVIDER})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Max agent turns (default: Hermes config)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--english-only", action="store_true", help="Force 'respond in English only' directive (auto-added for known non-English models)")
    parser.add_argument("--thinking", choices=list(THINKING_LEVELS.keys()), help="Reasoning effort: none/minimal/low/medium/high/xhigh")
    args = parser.parse_args()

    # Resolve alias to full model name
    model = resolve_alias(args.model)

    # Resolve context from --context, --context-file, or stdin
    context = args.context
    if args.context_file:
        with open(args.context_file) as f:
            context = f.read()
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            context = (context + "\n\n" if context else "") + stdin_data

    # Build prompt with language directive
    # NOTE: Previously called build_prompt() here AND inside dispatch_single(),
    #       causing /no_think and "respond in English only" to be duplicated.
    #       Now we pass the raw prompt and let dispatch_single() handle it.
    # Resolve alias to full model name for build_prompt's model checks
    toolsets = args.toolsets or DEFAULT_TOOLSETS

    r = dispatch_single(
        model, args.prompt, context, toolsets,
        args.max_turns, args.timeout, args.provider,
        output_file=args.output,
        thinking=args.thinking,
        english_only=args.english_only,
    )

    if r["content"]:
        if args.output:
            print(f"✅ {model} → {args.output} ({r['elapsed']:.1f}s, {len(r['content'])} chars)", file=sys.stderr)
        else:
            print(r["content"])
    else:
        print(f"❌ {model}: {r['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
