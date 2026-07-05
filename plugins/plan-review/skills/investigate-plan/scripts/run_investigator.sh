#!/usr/bin/env bash
# run_investigator.sh — drive one Hermes investigator run over a plan's
# researchable/agentic unknowns, from the host, via `docker exec hermes`.
#
# The investigator (iterate.py) must run INSIDE the hermes container (it needs
# the `ask` skill's model_utils + the next-best-questions ranker + Ollama).
# It takes a free-form --problem and generates its OWN questions, returning
# resolved "tombstone" facts as JSON. We embed the plan + its emphasized
# Open-Unknowns into --problem to bias it toward the plan's actual gaps.
#
# Usage:
#   run_investigator.sh [--slug NAME] [--dry-run] < problem.txt
#   printf '%s' "$PROBLEM_TEXT" | run_investigator.sh --slug my-plan
#
# The PROBLEM text is read from stdin (arbitrary length / content — passed to
# the container base64-encoded, so no shell-quoting or argv-length pitfalls).
#
# Tunables (env overrides):
#   INV_CONTAINER   container name              (default: hermes)
#   INV_K           questions per round         (default: 4)
#   INV_MAX_ROUNDS  investigation rounds        (default: 2)
#   INV_CAPABILITY  act | experiment | read     (default: act)
#   INV_FLOOR       value floor to keep asking  (default: 0.12)
#   INV_RUN_ROOT    container dir for run-dirs  (default: /opt/data/state/investigate-plan)
#   INV_ENTRY       iterate.py path in container
#
# Output: the investigator's full result dict as JSON on stdout. On any
# failure prints a JSON object {"error": "..."} and exits non-zero — the
# caller (the /investigate-plan skill) decides how to degrade gracefully.
set -euo pipefail

CONTAINER="${INV_CONTAINER:-hermes}"
K="${INV_K:-4}"
MAX_ROUNDS="${INV_MAX_ROUNDS:-2}"
CAPABILITY="${INV_CAPABILITY:-act}"
FLOOR="${INV_FLOOR:-0.12}"
RUN_ROOT="${INV_RUN_ROOT:-/opt/data/state/investigate-plan}"
ENTRY="${INV_ENTRY:-/opt/data/hermes-agent/skills/autonomous-ai-agents/investigator/scripts/iterate.py}"
DOCKER="${INV_DOCKER_BIN:-docker}"

SLUG=""
DRY_RUN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN="--dry-run"; shift ;;
    *) echo "{\"error\": \"unknown arg: $1\"}"; exit 2 ;;
  esac
done

emit_err() { printf '{"error": %s}\n' "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"; }

# --- read the problem text from stdin ---------------------------------------
PROBLEM="$(cat)"
if [ -z "${PROBLEM//[[:space:]]/}" ]; then
  emit_err "empty problem text on stdin"; exit 2
fi

# --- slug (deterministic if not supplied) -----------------------------------
if [ -z "$SLUG" ]; then
  SLUG="$(printf '%s' "$PROBLEM" | shasum 2>/dev/null | cut -c1-12)"
  [ -z "$SLUG" ] && SLUG="plan"
fi
# sanitize to a safe dir name
SLUG="$(printf '%s' "$SLUG" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-64)"
RUN_DIR="$RUN_ROOT/$SLUG"

# --- preflight: container up + entrypoint present ---------------------------
if ! "$DOCKER" ps --filter "name=$CONTAINER" --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
  emit_err "container '$CONTAINER' is not running (docker ps)"; exit 3
fi
if ! "$DOCKER" exec "$CONTAINER" test -f "$ENTRY" 2>/dev/null; then
  emit_err "investigator entrypoint not found in container: $ENTRY"; exit 3
fi

# --- run: pass problem in base64 via env, decode + invoke inside ------------
PLAN_B64="$(printf '%s' "$PROBLEM" | base64 | tr -d '\n')"

# shellcheck disable=SC2016
set +e
RESULT="$("$DOCKER" exec \
  -e PLAN_B64="$PLAN_B64" \
  -e RUN_DIR="$RUN_DIR" \
  -e ENTRY="$ENTRY" \
  -e K="$K" -e MAX_ROUNDS="$MAX_ROUNDS" -e CAPABILITY="$CAPABILITY" \
  -e FLOOR="$FLOOR" -e DRY_RUN="$DRY_RUN" \
  "$CONTAINER" sh -lc '
    set -e
    mkdir -p "$RUN_DIR"
    PROBLEM="$(printf %s "$PLAN_B64" | base64 -d)"
    exec python3 "$ENTRY" \
      --problem "$PROBLEM" \
      --k "$K" --max-rounds "$MAX_ROUNDS" --floor "$FLOOR" \
      --capability "$CAPABILITY" \
      --run-dir "$RUN_DIR" \
      $DRY_RUN \
      --json
  ')"
RC=$?
set -e

# Emit the investigator result verbatim on stdout (the /investigate-plan skill
# parses it). Preserved exactly — the sentinel below is a side effect.
printf '%s\n' "$RESULT"

# Host-visible proof of investigation. The plan-review gate runs on the HOST and
# cannot see the container run-dir, so on a successful (non-error) result drop a
# sentinel it can stat: ~/.claude/plans/.investigated-<slug>. Slug matches the
# gate's (plan basename). Best-effort — never fail the run over the sentinel.
if [ "$RC" -eq 0 ] && ! printf '%s' "$RESULT" | grep -q '"error"'; then
  HOST_PLANS="${CLAUDE_PLANS_DIR:-$HOME/.claude/plans}"
  SUMMARY="$(printf '%s' "$RESULT" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print("n_answered=%s n_gaps=%s stop=%s" % (d.get("n_answered"), d.get("n_gaps"), d.get("stop_reason")))
except Exception:
    print("investigation completed")' 2>/dev/null || printf 'investigation completed')"
  { mkdir -p "$HOST_PLANS" && printf '%s  run-dir=%s  %s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_DIR" "$SUMMARY" \
      > "$HOST_PLANS/.investigated-$SLUG"; } 2>/dev/null || true
fi

exit "$RC"
