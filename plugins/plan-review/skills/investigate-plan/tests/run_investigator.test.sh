#!/usr/bin/env bash
# Regression suite for run_investigator.sh. Live Docker coverage is opt-in.
set -u
G="$(cd "$(dirname "$0")/.." && pwd)/scripts/run_investigator.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fails=0
# shellcheck disable=SC2015
check() { [ "$3" = "$2" ] && echo "PASS $1" || { echo "FAIL $1 (want $2, got $3)"; fails=$((fails+1)); }; }
json_error() { python3 -c 'import json,sys; print("error" if "error" in json.load(sys.stdin) else "no")' < "$1" 2>/dev/null || echo no; }

# --- Tier 1: offline argument and stdin validation -------------------------
"$G" --bogus > "$T/o" 2>/dev/null; rc=$?
check unknown-arg "error rc2" "$(json_error "$T/o") rc$rc"
python3 -c 'import json,sys; assert "error" in json.load(sys.stdin)' < "$T/o"; rc=$?
check error-json-parses 0 "$rc"

printf '' | "$G" > "$T/o" 2>/dev/null; rc=$?
check empty-stdin "error rc2" "$(json_error "$T/o") rc$rc"

printf '  \n\t\n' | "$G" > "$T/o" 2>/dev/null; rc=$?
check whitespace-stdin "error rc2" "$(json_error "$T/o") rc$rc"

# --- Tier 2: fake Docker dispatch and transport assertions -----------------
FAKE="$T/docker"
cat > "$FAKE" <<'EOF'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG/args"

if [ "${1:-}" = ps ]; then
  [ "${FAKE_MODE:-happy}" = down ] || printf '%s\n' hermes
  exit 0
fi

if [ "${1:-}" = exec ] && [ "${3:-}" = test ] && [ "${4:-}" = -f ]; then
  [ "${FAKE_MODE:-happy}" = missing ] && exit 1
  exit 0
fi

if [ "${1:-}" = exec ] && [ "${2:-}" = -e ]; then
  shift
  plan_b64=""
  run_dir=""
  while [ "${1:-}" = -e ]; do
    pair="${2:-}"
    case "$pair" in
      PLAN_B64=*) plan_b64="${pair#PLAN_B64=}" ;;
      RUN_DIR=*) run_dir="${pair#RUN_DIR=}" ;;
    esac
    shift 2
  done
  printf '%s' "$run_dir" > "$FAKE_DOCKER_LOG/run_dir"
  printf '%s' "$plan_b64" | base64 -d > "$FAKE_DOCKER_LOG/problem"
  printf '%s %s %s\n' "${1:-}" "${2:-}" "${3:-}" > "$FAKE_DOCKER_LOG/run_args"
  printf '%s\n' '{"tombstones":[],"stop_reason":"x"}'
  exit 0
fi

exit 99
EOF
chmod +x "$FAKE"
mkdir "$T/log"

printf 'problem' | FAKE_MODE=down FAKE_DOCKER_LOG="$T/log" INV_DOCKER_BIN="$FAKE" "$G" > "$T/o" 2>/dev/null; rc=$?
msg="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("error", ""))' < "$T/o" 2>/dev/null)"
case "$msg" in *'not running'*) shape=error ;; *) shape=bad ;; esac
check container-down "error rc3" "$shape rc$rc"

: > "$T/log/args"
printf 'problem' | FAKE_MODE=missing FAKE_DOCKER_LOG="$T/log" INV_DOCKER_BIN="$FAKE" "$G" > "$T/o" 2>/dev/null; rc=$?
msg="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("error", ""))' < "$T/o" 2>/dev/null)"
case "$msg" in *entrypoint*|*'not found'*) shape=error ;; *) shape=bad ;; esac
check entrypoint-missing "error rc3" "$shape rc$rc"

: > "$T/log/args"
problem="Plan's first line
second * line"
printf '%s' "$problem" | FAKE_MODE=happy FAKE_DOCKER_LOG="$T/log" INV_DOCKER_BIN="$FAKE" "$G" --slug 'a/b *!x' > "$T/o" 2>/dev/null; rc=$?
check happy-path '{"tombstones":[],"stop_reason":"x"} rc0' "$(cat "$T/o") rc$rc"
check base64-round-trip "$problem" "$(cat "$T/log/problem")"
run_base="$(basename "$(cat "$T/log/run_dir")")"
case "$run_base" in *[!A-Za-z0-9._-]*|'') safe=no ;; *) safe=yes ;; esac
check slug-sanitization yes "$safe"
check run-command 'hermes sh -lc' "$(cat "$T/log/run_args")"

# --- Tier 2b: host proof sentinel for the plan-review gate ------------------
# A successful (non-error) run drops ~/.claude/plans/.investigated-<slug> so the
# host-side gate can confirm investigation ran. Isolated via CLAUDE_PLANS_DIR.
PLD="$T/plans"; mkdir -p "$PLD"
: > "$T/log/args"
printf '%s' 'prob' | FAKE_MODE=happy FAKE_DOCKER_LOG="$T/log" INV_DOCKER_BIN="$FAKE" CLAUDE_PLANS_DIR="$PLD" "$G" --slug sentinel-slug > "$T/o" 2>/dev/null
check sentinel-written yes "$([ -s "$PLD/.investigated-sentinel-slug" ] && echo yes || echo no)"
check sentinel-stdout-intact '{"tombstones":[],"stop_reason":"x"}' "$(cat "$T/o")"
# error path (container down) must NOT write a sentinel
: > "$T/log/args"
printf '%s' 'prob' | FAKE_MODE=down FAKE_DOCKER_LOG="$T/log" INV_DOCKER_BIN="$FAKE" CLAUDE_PLANS_DIR="$PLD" "$G" --slug down-slug > "$T/o" 2>/dev/null
check sentinel-none-on-error no "$([ -f "$PLD/.investigated-down-slug" ] && echo yes || echo no)"

# --- Tier 3: live Docker integration (opt-in) ------------------------------
if [ "${INVESTIGATE_TEST_LIVE:-0}" != 1 ]; then
  echo "SKIP live: set INVESTIGATE_TEST_LIVE=1 to enable"
elif ! command -v docker >/dev/null 2>&1 || ! docker ps --filter name=hermes --format '{{.Names}}' 2>/dev/null | grep -qx hermes; then
  echo "SKIP live: hermes container is not running"
else
  printf '%s' 'some problem text' | env -u INV_DOCKER_BIN "$G" --slug a-suite-live --dry-run > "$T/live" 2>/dev/null; rc=$?
  if [ "$rc" -eq 0 ]; then
    python3 -c 'import json,sys; assert "tombstones" in json.load(sys.stdin)' < "$T/live" 2>/dev/null; json_rc=$?
  else
    json_rc=1
  fi
  check live-dry-run "json rc0" "$( [ "$json_rc" -eq 0 ] && echo json || echo bad ) rc$rc"
  docker exec hermes sh -lc 'rm -rf /opt/data/state/investigate-plan/a-suite-live' >/dev/null 2>&1 || true
fi

echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILURE(S)"; exit "$fails"
