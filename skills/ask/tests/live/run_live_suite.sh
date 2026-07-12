#!/usr/bin/env bash
# Opt-in, live validation only. Requires a running Docker container named hermes.
set -uo pipefail

CONTAINER="hermes"
ASK_SCRIPTS="/opt/data/skills/productivity/ask/scripts"
GATE_PYTHON="/opt/data/.venv/bin/python3"
LIVE_TIMEOUT="${LIVE_TIMEOUT:-20}"
LC10_TIMEOUT="${LC10_TIMEOUT:-90}"  # per-model timeout; 30s starves cold hermes dispatches (verified live 2026-07-11)
LC7_MODEL_2="${LC7_MODEL_2:-fast}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLAN_FILE="${SCRIPT_DIR}/TEST_PLAN.md"
ALL_CASES=(LC1 LC2 LC3 LC4 LC5 LC6 LC7 LC8 LC9 LC10 LC10b LC11)
RESULT_IDS=()
RESULT_STATES=()
RESULT_SECONDS=()
RESULT_DETAILS=()
HAVE_JQ=0

usage() {
    printf 'Usage: %s [LC1 ... LC10 LC10b LC11]\n' "${0##*/}" >&2
}

emit_progress() {
    # Values are deliberately fixed strings so this remains valid JSON without a JSON dependency.
    printf '{"case":"%s","event":"%s"}\n' "$1" "$2" >&2
}

record_result() {
    RESULT_IDS+=("$1")
    RESULT_STATES+=("$2")
    RESULT_SECONDS+=("$3")
    RESULT_DETAILS+=("$4")
    local lower_state
    lower_state=$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')
    emit_progress "$1" "$lower_state"
}

run_in_container() {
    local stdout_file=$1 stderr_file=$2
    shift 2
    docker exec "$CONTAINER" "$@" >"$stdout_file" 2>"$stderr_file"
}

json_value() {
    local file=$1 path=$2
    if (( HAVE_JQ )); then
        # Do not use jq -e here: null and false are valid values under test.
        # Unlike a plain dotted query, this also errors when a path is missing.
        jq -r --arg path "$path" '
            ($path | split(".") | map(if test("^[0-9]+$") then tonumber else . end)) as $parts
            | def has_path($value; $remaining):
                if ($remaining | length) == 0 then true
                else $remaining[0] as $head
                | if ($value | type) == "object" then
                    if ($value | has($head)) then has_path($value[$head]; $remaining[1:]) else false end
                  elif ($value | type) == "array" then
                    if (($head | type) == "number" and $head >= 0 and $head < ($value | length)) then has_path($value[$head]; $remaining[1:]) else false end
                  else false
                  end
                end;
            if has_path(.; $parts) then getpath($parts) else error("missing JSON path: " + $path) end
        ' "$file"
    else
        python3 - "$file" "$path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    value = json.load(fh)
for key in sys.argv[2].split("."):
    if key.isdigit():
        value = value[int(key)]
    else:
        value = value[key]
if isinstance(value, str):
    print(value)
else:
    print(json.dumps(value, ensure_ascii=False))
PY
    fi
}

json_equal() {
    local file=$1 path=$2 expected=$3 actual
    actual=$(json_value "$file" "$path" 2>/dev/null) || { JSON_OBSERVED='<unreadable>'; return 1; }
    JSON_OBSERVED=$actual
    [[ "$actual" == "$expected" ]]
}

json_nonempty() {
    local file=$1 path=$2 actual
    actual=$(json_value "$file" "$path" 2>/dev/null) || return 1
    [[ -n "$actual" && "$actual" != "null" && "$actual" != "[]" ]]
}

json_length() {
    local file=$1 path=$2
    if (( HAVE_JQ )); then
        jq -r ".${path} | length" "$file"
    else
        python3 - "$file" "$path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    value = json.load(fh)
for key in sys.argv[2].split("."):
    value = value[int(key)] if key.isdigit() else value[key]
print(len(value))
PY
    fi
}

event_has() {
    local file=$1 wanted=$2
    if (( HAVE_JQ )); then
        jq -eR --arg wanted "$wanted" 'fromjson? | select(.event == $wanted)' "$file" >/dev/null
    else
        python3 - "$file" "$wanted" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == sys.argv[2]:
            raise SystemExit(0)
raise SystemExit(1)
PY
    fi
}

event_field_nonempty() {
    local file=$1 wanted=$2 field=$3
    if (( HAVE_JQ )); then
        jq -eR --arg wanted "$wanted" --arg field "$field" 'fromjson? | select(.event == $wanted) | .[$field] | select(. != null and . != "")' "$file" >/dev/null
    else
        python3 - "$file" "$wanted" "$field" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == sys.argv[2] and event.get(sys.argv[3]) not in (None, ""):
            raise SystemExit(0)
raise SystemExit(1)
PY
    fi
}

event_field_equal() {
    local file=$1 wanted=$2 field=$3 expected=$4
    if (( HAVE_JQ )); then
        jq -eR --arg wanted "$wanted" --arg field "$field" --arg expected "$expected" 'fromjson? | select(.event == $wanted and (.[$field] | tostring) == $expected)' "$file" >/dev/null
    else
        python3 - "$file" "$wanted" "$field" "$expected" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == sys.argv[2] and str(event.get(sys.argv[3])) == sys.argv[4]:
            raise SystemExit(0)
raise SystemExit(1)
PY
    fi
}

has_no_raw_fallback_notice() {
    local file=$1
    ! rg -qi 'Primary auth failed|Primary model failed' "$file"
}

join_problems() {
    local IFS='; '
    printf '%s' "$*"
}

clean_container_paths() {
    # These paths are owned exclusively by this suite; ignore cleanup failures.
    docker exec "$CONTAINER" sh -c 'rm -rf /tmp/gd-lc10 /tmp/gd-lc10.yaml /tmp/gd-lc10b /tmp/gd-lc10b.yaml /tmp/stub-lc3.sh /tmp/stub-lc4.sh /tmp/stub-lc5.sh /tmp/stub-lc10b.sh /tmp/ask-sessions.lc6.backup /tmp/ask-sessions.lc6.had-file /tmp/ask-live-suite-sessions.backup /tmp/ask-live-suite-sessions.had-file' >/dev/null 2>&1 || true
}

read_effort() {
    docker exec "$CONTAINER" env "PYTHONPATH=$ASK_SCRIPTS" python3 -c \
        'from model_utils import get_reasoning_effort; print(get_reasoning_effort())' 2>/dev/null | tr -d '\r\n'
}

session_registry_key_for_fast() {
    docker exec "$CONTAINER" env "PYTHONPATH=$ASK_SCRIPTS" python3 -c \
        "from model_utils import ALIASES, resolve_alias; model=resolve_alias('fast'); print(next(key for key, value in ALIASES.items() if value == model))" 2>/dev/null
}

session_id_for_registry_key() {
    local key=$1
    docker exec "$CONTAINER" env "ASK_SESSION_KEY=$key" python3 -c \
        "import json, os; path=os.path.expanduser('~/.hermes/ask-sessions.json'); registry=json.load(open(path)); print(registry.get(os.environ['ASK_SESSION_KEY'], {}).get('session_id', ''))" 2>/dev/null
}

restore_lc6_registry() {
    docker exec "$CONTAINER" sh -c '
        target="$HOME/.hermes/ask-sessions.json"
        if [ -f /tmp/ask-sessions.lc6.had-file ]; then
            mkdir -p "$(dirname "$target")"
            mv /tmp/ask-sessions.lc6.backup "$target"
        else
            rm -f "$target"
        fi
        rm -f /tmp/ask-sessions.lc6.had-file
    ' >/dev/null 2>&1 || true
}

snapshot_suite_registry() {
    docker exec "$CONTAINER" sh -c '
        target="$HOME/.hermes/ask-sessions.json"
        rm -f /tmp/ask-live-suite-sessions.backup /tmp/ask-live-suite-sessions.had-file
        if [ -f "$target" ]; then
            cp "$target" /tmp/ask-live-suite-sessions.backup
            : > /tmp/ask-live-suite-sessions.had-file
        fi
    '
}

restore_suite_registry() {
    docker exec "$CONTAINER" sh -c '
        target="$HOME/.hermes/ask-sessions.json"
        if [ -f /tmp/ask-live-suite-sessions.had-file ]; then
            mkdir -p "$(dirname "$target")"
            mv /tmp/ask-live-suite-sessions.backup "$target"
        else
            rm -f "$target"
        fi
    ' >/dev/null 2>&1 || true
}

lc1() {
    local out="$RUN_TMP/lc1.out" err="$RUN_TMP/lc1.err" start rc elapsed
    local -a problems=()
    start=$SECONDS
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" definitely-not-a-model:tag \
        'Reply only with the word rerouted.' --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    elapsed=$((SECONDS - start))
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    [[ -s "$out" ]] || problems+=("expected non-empty CLI answer")
    has_no_raw_fallback_notice "$out" || problems+=("raw reroute/fallback notice leaked into content")
    event_has "$err" dispatch_end || problems+=("missing dispatch_end JSONL event")
    if ((${#problems[@]})); then record_result LC1 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC1 PASS "$elapsed" 'exit 0; non-empty, notice-free answer'; fi
}

lc2() {
    local out="$RUN_TMP/lc2.out" err="$RUN_TMP/lc2.err" probe="$RUN_TMP/lc2b.json" probe_err="$RUN_TMP/lc2b.err"
    local start rc probe_rc elapsed supplementary code
    local -a problems=()
    start=$SECONDS
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Reply only with: provider fallback probe.' --provider definitely-not-a-provider \
        --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    (( rc == 0 )) || problems+=("CLI expected exit 0, got ${rc}")
    [[ -s "$out" ]] || problems+=("CLI expected non-empty answer")
    has_no_raw_fallback_notice "$out" || problems+=("CLI content leaked raw fallback notice")
    event_has "$err" fallback || problems+=("CLI missing fallback JSONL event")
    event_field_nonempty "$err" fallback notice || problems+=("fallback event missing notice")

    # LC2b intentionally skips only argument parsing: dispatch_single still starts hermes chat.
    code="import json; from model_utils import dispatch_single, resolve_alias; r=dispatch_single(resolve_alias('fast'), 'Reply only with: structured fallback probe.', '', 'file,web', None, ${LIVE_TIMEOUT}, 'definitely-not-a-provider'); print(json.dumps(r, ensure_ascii=False))"
    run_in_container "$probe" "$probe_err" env "PYTHONPATH=$ASK_SCRIPTS" python3 -c "$code"
    probe_rc=$?
    supplementary='LC2b supplementary direct-dispatcher probe unavailable'
    local probe_content
    probe_content=$(json_value "$probe" content 2>/dev/null || true)
    if (( probe_rc == 0 )) && json_nonempty "$probe" fallback && [[ -n "$probe_content" ]] && [[ "$probe_content" != *'Primary auth failed'* && "$probe_content" != *'Primary model failed'* ]]; then
        supplementary='LC2b supplementary direct-dispatcher fallback field non-null'
    else
        supplementary="LC2b non-fatal: structured fallback probe failed (exit ${probe_rc})"
    fi
    elapsed=$((SECONDS - start))
    if ((${#problems[@]})); then record_result LC2 FAIL "$elapsed" "$(join_problems "${problems[@]}"); ${supplementary}"; else record_result LC2 PASS "$elapsed" "CLI clean fallback verified; ${supplementary}"; fi
}

lc3() {
    local out="$RUN_TMP/lc3.json" err="$RUN_TMP/lc3.err" start rc elapsed
    local -a problems=()
    start=$SECONDS
    docker exec "$CONTAINER" sh -c "printf '%s\\n' '#!/bin/sh' 'exit 0' > /tmp/stub-lc3.sh && chmod 700 /tmp/stub-lc3.sh" >/dev/null 2>&1
    run_in_container "$out" "$err" env HERMES_BIN=/tmp/stub-lc3.sh DEVLOOP_ENABLED=0 python3 "$ASK_SCRIPTS/pipeline.py" \
        'Write a tiny Python function named lc3_add that returns a plus b.' --json --emit-events --timeout 5
    rc=$?
    elapsed=$((SECONDS - start))
    (( rc == 1 )) || problems+=("expected exit 1, got ${rc}")
    json_equal "$out" dispatch_retries 1 || problems+=("dispatch_retries expected 1, got ${JSON_OBSERVED}")
    json_equal "$out" dispatch_result.retried true || problems+=("dispatch_result.retried expected true, got ${JSON_OBSERVED}")
    json_equal "$out" pipeline_status dispatch_failed || problems+=("pipeline_status expected dispatch_failed, got ${JSON_OBSERVED}")
    json_equal "$out" dispatch_result.content null || problems+=("dispatch_result.content expected null, got ${JSON_OBSERVED}")
    event_has "$err" dispatch_retry || problems+=("missing dispatch_retry JSONL event")
    docker exec "$CONTAINER" rm -f /tmp/stub-lc3.sh >/dev/null 2>&1 || true
    if ((${#problems[@]})); then record_result LC3 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC3 PASS "$elapsed" 'one empty-output retry; dispatch_failed'; fi
}

lc4() {
    local out="$RUN_TMP/lc4.json" err="$RUN_TMP/lc4.err" start rc elapsed error_text
    local -a problems=()
    start=$SECONDS
    docker exec "$CONTAINER" sh -c "printf '%s\\n' '#!/bin/sh' 'exit 2' > /tmp/stub-lc4.sh && chmod 700 /tmp/stub-lc4.sh" >/dev/null 2>&1
    run_in_container "$out" "$err" env HERMES_BIN=/tmp/stub-lc4.sh DEVLOOP_ENABLED=0 python3 "$ASK_SCRIPTS/pipeline.py" \
        'Write a tiny Python function named lc4_add that returns a plus b.' --json --emit-events --timeout 5
    rc=$?
    elapsed=$((SECONDS - start))
    error_text=$(json_value "$out" dispatch_result.error 2>/dev/null || true)
    (( rc == 1 )) || problems+=("expected exit 1, got ${rc}")
    json_equal "$out" dispatch_retries 0 || problems+=("dispatch_retries expected 0, got ${JSON_OBSERVED}")
    json_equal "$out" pipeline_status dispatch_failed || problems+=("pipeline_status expected dispatch_failed, got ${JSON_OBSERVED}")
    json_equal "$out" dispatch_result.content null || problems+=("dispatch_result.content expected null, got ${JSON_OBSERVED}")
    [[ "$error_text" == *'exit 2'* ]] || problems+=("dispatch error expected exit 2, got ${error_text:-unreadable}")
    ! event_has "$err" dispatch_retry || problems+=("unexpected dispatch_retry event")
    docker exec "$CONTAINER" rm -f /tmp/stub-lc4.sh >/dev/null 2>&1 || true
    if ((${#problems[@]})); then record_result LC4 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC4 PASS "$elapsed" 'hard exit 2 failed immediately without retry'; fi
}

lc5() {
    local out="$RUN_TMP/lc5.out" err="$RUN_TMP/lc5.err" start rc elapsed before after
    local -a problems=()
    start=$SECONDS
    before=$(read_effort)
    [[ -n "$before" ]] || problems+=("precondition: agent.reasoning_effort is unset or model_utils read failed")
    docker exec "$CONTAINER" sh -c "printf '%s\\n' '#!/bin/sh' 'if [ \"\$1\" = config ]; then exec /opt/hermes/bin/hermes \"\$@\"; fi' 'if [ \"\$1\" = chat ]; then sleep 30; exit 0; fi' 'exit 64' > /tmp/stub-lc5.sh && chmod 700 /tmp/stub-lc5.sh" >/dev/null 2>&1
    run_in_container "$out" "$err" env HERMES_BIN=/tmp/stub-lc5.sh python3 "$ASK_SCRIPTS/ask.py" fast \
        'Reply only with timeout probe.' --thinking high --timeout 5 --emit-events
    rc=$?
    after=$(read_effort)
    elapsed=$((SECONDS - start))
    (( rc == 1 )) || problems+=("ask maps timeout to exit 1; got ${rc}")
    rg -q 'Timed out after 5s' "$err" || problems+=("missing Timed out after 5s error")
    event_has "$err" dispatch_end || problems+=("missing failed dispatch_end JSONL event")
    [[ ! -s "$out" ]] || problems+=("unexpected answer output after timeout")
    [[ -n "$before" && "$after" == "$before" ]] || problems+=("reasoning effort not restored (before=${before:-unset}, after=${after:-unset})")
    docker exec "$CONTAINER" rm -f /tmp/stub-lc5.sh >/dev/null 2>&1 || true
    if ((${#problems[@]})); then record_result LC5 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC5 PASS "$elapsed" 'timeout error and reasoning effort restored'; fi
}

lc6() {
    local first_out="$RUN_TMP/lc6-first.out" first_err="$RUN_TMP/lc6-first.err" follow_out="$RUN_TMP/lc6-follow.out" follow_err="$RUN_TMP/lc6-follow.err" recover_out="$RUN_TMP/lc6-recover.out" recover_err="$RUN_TMP/lc6-recover.err"
    local start rc1 rc2 rc3 elapsed sid saved_sid registry_key
    local -a problems=()
    start=$SECONDS
    docker exec "$CONTAINER" sh -c '
        source="$HOME/.hermes/ask-sessions.json"
        if [ -f "$source" ]; then cp "$source" /tmp/ask-sessions.lc6.backup; : > /tmp/ask-sessions.lc6.had-file; fi
        rm -f "$source"
    ' >/dev/null 2>&1
    run_in_container "$first_out" "$first_err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Remember the exact token LC6-CONTEXT-482. Reply only with that token.' --timeout "$LIVE_TIMEOUT" --emit-events
    rc1=$?
    registry_key=$(session_registry_key_for_fast || true)
    sid=$(session_id_for_registry_key "$registry_key" || true)
    [[ -n "$registry_key" ]] || problems+=("could not resolve fast's first-match session-registry key")
    [[ -n "$sid" ]] || problems+=("could not capture session_id from registry key ${registry_key:-unresolved}")
    run_in_container "$follow_out" "$follow_err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'What exact token did I ask you to remember? Reply only with it.' --resume "$sid" --timeout "$LIVE_TIMEOUT" --emit-events
    rc2=$?
    run_in_container "$recover_out" "$recover_err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Reply only with LC6-RECOVERED.' --resume lc6-bogus-session-id --timeout "$LIVE_TIMEOUT" --emit-events
    rc3=$?
    saved_sid=$(session_id_for_registry_key "$registry_key" || true)
    restore_lc6_registry
    elapsed=$((SECONDS - start))
    (( rc1 == 0 && rc2 == 0 && rc3 == 0 )) || problems+=("ask exits expected 0 (got ${rc1}/${rc2}/${rc3})")
    rg -q 'LC6-CONTEXT-482' "$follow_out" || problems+=("resumed answer did not retain context token")
    rg -q 'LC6-RECOVERED' "$recover_out" || problems+=("bogus-session fresh recovery did not answer")
    [[ -n "$saved_sid" && "$saved_sid" != lc6-bogus-session-id ]] || problems+=("bogus session id was retained or no fresh session captured")
    if ((${#problems[@]})); then record_result LC6 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC6 PASS "$elapsed" 'captured, resumed, and stale-session recovered'; fi
}

lc7() {
    local out="$RUN_TMP/lc7.out" err="$RUN_TMP/lc7.err" start rc elapsed before after model1 model2 labels
    local -a problems=()
    start=$SECONDS
    before=$(read_effort)
    [[ -n "$before" ]] || problems+=("precondition: agent.reasoning_effort is unset or model_utils read failed")
    model1=$(docker exec "$CONTAINER" env "PYTHONPATH=$ASK_SCRIPTS" python3 -c "from model_utils import resolve_alias; print(resolve_alias('fast'))" 2>/dev/null || true)
    model2=$(docker exec "$CONTAINER" env "PYTHONPATH=$ASK_SCRIPTS" "LC7_MODEL_2=$LC7_MODEL_2" python3 -c "import os; from model_utils import resolve_alias; print(resolve_alias(os.environ['LC7_MODEL_2']))" 2>/dev/null || true)
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" fast "$LC7_MODEL_2" \
        'Reply only with comparison-ok.' --thinking low --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    after=$(read_effort)
    elapsed=$((SECONDS - start))
    labels=$(rg -F -c '🤖 ' "$out" || true)
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    rg -qF -- '--thinking low: running sequentially (not parallel)' "$err" || problems+=("missing serialization warning")
    (( labels >= 2 )) || problems+=("expected two labeled results, got ${labels}")
    [[ -n "$model1" ]] && rg -F -q "🤖 ${model1}" "$out" || problems+=("missing label for fast (${model1:-unresolved})")
    [[ -n "$model2" ]] && rg -F -q "🤖 ${model2}" "$out" || problems+=("missing label for LC7_MODEL_2 (${model2:-unresolved})")
    [[ -n "$before" && "$after" == "$before" ]] || problems+=("reasoning effort not restored (before=${before:-unset}, after=${after:-unset})")
    if ((${#problems[@]})); then record_result LC7 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC7 PASS "$elapsed" "serialized ${model1} and ${model2}; effort restored"; fi
}

lc8() {
    local out="$RUN_TMP/lc8.out" err="$RUN_TMP/lc8.err" start rc elapsed hostname sid registry_key
    local -a problems=()
    start=$SECONDS
    hostname=$(docker exec "$CONTAINER" cat /etc/hostname 2>/dev/null | tr -d '\r\n')
    docker exec "$CONTAINER" sh -c 'rm -f "$HOME/.hermes/ask-sessions.json"' >/dev/null 2>&1
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Use your file tool to read /etc/hostname. Reply with its contents only.' --toolsets file --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    registry_key=$(session_registry_key_for_fast || true)
    sid=$(session_id_for_registry_key "$registry_key" || true)
    elapsed=$((SECONDS - start))
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    [[ -s "$out" ]] || problems+=("expected non-empty tool answer")
    [[ -n "$hostname" ]] && rg -F -q "$hostname" "$out" || problems+=("answer did not reflect /etc/hostname")
    [[ -n "$sid" ]] || problems+=("no session_id found at fast's registry key ${registry_key:-unresolved}")
    if ((${#problems[@]})); then record_result LC8 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC8 PASS "$elapsed" 'file-tool answer reflects hostname and session captured'; fi
}

lc9() {
    local out="$RUN_TMP/lc9.out" err="$RUN_TMP/lc9.err" cap_out="$RUN_TMP/lc9-cap.out" cap_err="$RUN_TMP/lc9-cap.err"
    local start rc cap_rc elapsed cap_note primary_note last_line
    local -a problems=()
    start=$SECONDS
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Ask me exactly one clarifying question about my favorite color. As soon as I answer, give your final response immediately — do not ask a second question.' \
        --auto-answer --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    last_line=$(tail -n 1 "$out" 2>/dev/null || true)
    primary_note='free-text auto-answer completed'
    if (( rc == 0 )); then
        if event_has "$err" auto_answer; then
            event_field_nonempty "$err" auto_answer question || problems+=("auto_answer event missing question")
            event_field_nonempty "$err" auto_answer answer || problems+=("auto_answer event missing answer")
            event_field_nonempty "$err" auto_answer round || problems+=("auto_answer event missing round")
            event_field_equal "$err" auto_answer seam freetext || problems+=("auto_answer event seam expected freetext")
        else
            primary_note='no clarification elicited this run'
        fi
        [[ -s "$out" && "$last_line" != *'?' ]] || problems+=("final output is empty or only a clarifying question")
    elif (( rc == 2 )); then
        if event_has "$err" auto_answer; then
            primary_note='primary round-cap fallback accepted after auto-answer event'
            event_field_nonempty "$err" auto_answer question || problems+=("round-cap auto_answer event missing question")
            event_field_nonempty "$err" auto_answer answer || problems+=("round-cap auto_answer event missing answer")
            event_field_nonempty "$err" auto_answer round || problems+=("round-cap auto_answer event missing round")
            event_field_equal "$err" auto_answer seam freetext || problems+=("round-cap auto_answer event seam expected freetext")
        else
            problems+=("exit 2 with zero auto_answer events: clarification was never attempted (likely no session_id)")
        fi
    else
        problems+=("expected exit 0, or exit 2 after auto_answer events; got ${rc}")
    fi

    # Best effort only: live models may not keep asking after the two allowed rounds.
    run_in_container "$cap_out" "$cap_err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Before every answer, ask exactly one new clarifying question and never answer.' \
        --auto-answer --timeout "$LIVE_TIMEOUT" --emit-events
    cap_rc=$?
    if (( cap_rc == 2 )); then cap_note='round-cap sub-check observed exit 2'; else cap_note="round-cap sub-check non-fatal (observed exit ${cap_rc})"; fi
    elapsed=$((SECONDS - start))
    if ((${#problems[@]})); then record_result LC9 FAIL "$elapsed" "$(join_problems "${problems[@]}"); ${cap_note}"; else record_result LC9 PASS "$elapsed" "${primary_note}; ${cap_note}"; fi
}

lc10() {
    local out="$RUN_TMP/lc10.json" err="$RUN_TMP/lc10.err" start rc elapsed answer count
    local -a problems=()
    start=$SECONDS
    docker exec -i "$CONTAINER" sh -c 'cat > /tmp/gd-lc10.yaml' <<'YAML' >/dev/null 2>&1
workflow: lc10-live-gate
version: 1
description: A single live-agent approval gate for the ask live suite.
needs:
  - Run one approval demonstration.
returns:
  - A final summary after approval input.
steps:
  - id: approval
    prompt: |
      On your first turn, reply with EXACTLY this JSON object and nothing else:
      {"ask": {"prompt": "Approve this demo?", "options": ["approved", "denied"]}}
      Once the workflow context includes untrusted_human_response, produce a concise final summary that states the selected answer. Do not ask another question.
    # no acceptance criterion: it would invoke the engine's live-model judge, whose
    # strict decision protocol small local models fail ("judge returned no valid
    # decision") — LC10 validates the gate auto-answer loop, not the judge protocol
YAML
    run_in_container "$out" "$err" "$GATE_PYTHON" "$ASK_SCRIPTS/gate_driver.py" --flow /tmp/gd-lc10.yaml \
        --state-dir /tmp/gd-lc10 --auto-answer fast --json --emit-events --timeout "$LC10_TIMEOUT"
    rc=$?
    count=$(json_length "$out" auto_answers 2>/dev/null || true)
    answer=$(json_value "$out" auto_answers.0.answer 2>/dev/null || true)
    elapsed=$((SECONDS - start))
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    json_equal "$out" status completed || problems+=("status expected completed, got ${JSON_OBSERVED}")
    [[ "$count" == 1 ]] || problems+=("auto_answers length expected 1, got ${count:-unreadable}")
    [[ "$answer" == approved || "$answer" == denied ]] || problems+=("recorded gate answer not an allowed enum")
    event_has "$err" auto_answer || problems+=("missing gate auto_answer JSONL event")
    event_field_nonempty "$err" auto_answer question || problems+=("gate auto_answer event missing question")
    event_field_nonempty "$err" auto_answer answer || problems+=("gate auto_answer event missing answer")
    event_field_nonempty "$err" auto_answer round || problems+=("gate auto_answer event missing round")
    event_field_equal "$err" auto_answer seam gate || problems+=("gate auto_answer event seam expected gate")
    json_nonempty "$out" result || problems+=("missing final workflow result payload")
    docker exec "$CONTAINER" rm -rf /tmp/gd-lc10 /tmp/gd-lc10.yaml >/dev/null 2>&1 || true
    if ((${#problems[@]})); then record_result LC10 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC10 PASS "$elapsed" "completed one durable gate with ${answer}"; fi
}

lc10b() {
    local out="$RUN_TMP/lc10b.json" err="$RUN_TMP/lc10b.err" start rc elapsed answer count
    local -a problems=()
    start=$SECONDS
    docker exec "$CONTAINER" sh -c "printf '%s\\n' '#!/bin/sh' 'prompt=' 'previous=' 'for arg in \"\$@\"; do' '  if [ \"\$previous\" = \"-q\" ]; then' '    prompt=\$arg' '    break' '  fi' '  previous=\$arg' 'done' 'case \"\$prompt\" in' '  *untrusted_human_response*)' '    echo \"Demo approved. Workflow complete.\"' '    exit 0' '    ;;' 'esac' 'case \"\$prompt\" in' '  *\"Approve this demo\"*)' '    case \"\$prompt\" in' '      *\"permitted enum options\"*|*\"- approved\"*|*\"- denied\"*)' '        echo approved' '        exit 0' '        ;;' '    esac' '    ;;' 'esac' 'echo \"{\\\"ask\\\": {\\\"prompt\\\": \\\"Approve this demo?\\\", \\\"options\\\": [\\\"approved\\\", \\\"denied\\\"]}}\"' > /tmp/stub-lc10b.sh && chmod 700 /tmp/stub-lc10b.sh" >/dev/null 2>&1
    docker exec -i "$CONTAINER" sh -c 'cat > /tmp/gd-lc10b.yaml' <<'YAML' >/dev/null 2>&1
workflow: lc10b-stub-gate
version: 1
description: A deterministic stubbed approval gate for the ask live suite.
needs:
  - Run one approval demonstration.
returns:
  - A final summary after approval input.
steps:
  - id: approval
    prompt: |
      On your first turn, reply with EXACTLY this JSON object and nothing else:
      {"ask": {"prompt": "Approve this demo?", "options": ["approved", "denied"]}}
      After the caller's answer arrives, produce a concise final summary that states the selected answer. Do not ask another question.
YAML
    run_in_container "$out" "$err" env HERMES_BIN=/tmp/stub-lc10b.sh "$GATE_PYTHON" "$ASK_SCRIPTS/gate_driver.py" --flow /tmp/gd-lc10b.yaml \
        --state-dir /tmp/gd-lc10b --auto-answer fast --json --emit-events --timeout 15
    rc=$?
    count=$(json_length "$out" auto_answers 2>/dev/null || true)
    answer=$(json_value "$out" auto_answers.0.answer 2>/dev/null || true)
    elapsed=$((SECONDS - start))
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    [[ "$count" == 1 ]] || problems+=("auto_answers length expected 1, got ${count:-unreadable}")
    [[ "$answer" == approved || "$answer" == denied ]] || problems+=("recorded gate answer not an allowed enum")
    json_equal "$out" status completed || problems+=("status expected completed, got ${JSON_OBSERVED}")
    event_has "$err" auto_answer || problems+=("missing gate auto_answer JSONL event")
    event_field_equal "$err" auto_answer seam gate || problems+=("gate auto_answer event seam expected gate")
    docker exec "$CONTAINER" rm -rf /tmp/stub-lc10b.sh /tmp/gd-lc10b /tmp/gd-lc10b.yaml >/dev/null 2>&1 || true
    if ((${#problems[@]})); then record_result LC10b FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC10b PASS "$elapsed" "completed deterministic durable gate with ${answer}"; fi
}

lc11() {
    local out="$RUN_TMP/lc11.out" err="$RUN_TMP/lc11.err" start rc elapsed
    local -a problems=()
    start=$SECONDS
    run_in_container "$out" "$err" python3 "$ASK_SCRIPTS/ask.py" fast \
        'Reply exactly as follows: first line 😀 café — 東京; second line Primary authentication failed? This ordinary prose must remain.; then a numbered list from 1 through 20.' \
        --thinking none --timeout "$LIVE_TIMEOUT" --emit-events
    rc=$?
    elapsed=$((SECONDS - start))
    (( rc == 0 )) || problems+=("expected exit 0, got ${rc}")
    rg -F -q '😀 café — 東京' "$out" || problems+=("emoji/unicode first line was not preserved")
    rg -F -q 'Primary authentication failed? This ordinary prose must remain.' "$out" || problems+=("control-like ordinary prose was stripped or changed")
    rg -q '20\b' "$out" || problems+=("long numbered list did not reach item 20")
    has_no_raw_fallback_notice "$out" || problems+=("actual fallback-notice pattern unexpectedly leaked")
    if ((${#problems[@]})); then record_result LC11 FAIL "$elapsed" "$(join_problems "${problems[@]}")"; else record_result LC11 PASS "$elapsed" 'unicode, control-like prose, and long list preserved'; fi
}

append_results_log() {
    local now i detail
    now=$(date -Iseconds)
    {
        printf '\n### %s\n\n' "$now"
        printf '| Case | Result | Seconds | Detail |\n| --- | --- | ---: | --- |\n'
        for ((i = 0; i < ${#RESULT_IDS[@]}; i++)); do
            detail=${RESULT_DETAILS[i]//$'\n'/ }
            detail=${detail//|/\\|}
            printf '| %s | %s | %s | %s |\n' "${RESULT_IDS[i]}" "${RESULT_STATES[i]}" "${RESULT_SECONDS[i]}" "$detail"
        done
    } >> "$PLAN_FILE"
}

main() {
    local requested case valid=0 i failed=0
    local -a cases=()
    if command -v jq >/dev/null 2>&1; then HAVE_JQ=1; fi
    if (( ! HAVE_JQ )) && ! command -v python3 >/dev/null 2>&1; then
        printf 'Environment precondition failed: install jq or python3 for JSON assertions.\n' >&2
        return 10
    fi
    if (($# == 0)); then
        cases=("${ALL_CASES[@]}")
    else
        for requested in "$@"; do
            valid=0
            for case in "${ALL_CASES[@]}"; do
                [[ "$requested" == "$case" ]] && valid=1
            done
            if (( ! valid )); then
                usage
                return 2
            fi
            cases+=("$requested")
        done
    fi
    if ! docker ps --filter 'name=^/hermes$' --format '{{.Names}}' | rg -qx hermes; then
        printf 'Environment precondition failed: Docker container "hermes" is not running.\n' >&2
        return 10
    fi
    RUN_TMP=$(mktemp -d "${TMPDIR:-/tmp}/ask-live.XXXXXX") || { printf 'Could not create temporary directory.\n' >&2; return 10; }
    if ! snapshot_suite_registry; then
        printf 'Environment precondition failed: could not snapshot the container session registry.\n' >&2
        rm -rf "$RUN_TMP"
        return 10
    fi
    trap 'restore_suite_registry; clean_container_paths; rm -rf "$RUN_TMP"' EXIT
    local case_fn
    for case in "${cases[@]}"; do
        printf '\n== %s ==\n' "$case" >&2
        emit_progress "$case" start
        case_fn=$(printf '%s' "$case" | tr '[:upper:]' '[:lower:]')
        "$case_fn"
    done
    printf '\n| Case | Result | Seconds |\n| --- | --- | ---: |\n'
    for ((i = 0; i < ${#RESULT_IDS[@]}; i++)); do
        printf '| %s | %s | %s |\n' "${RESULT_IDS[i]}" "${RESULT_STATES[i]}" "${RESULT_SECONDS[i]}"
        [[ "${RESULT_STATES[i]}" == PASS ]] || failed=1
    done
    append_results_log
    (( failed == 0 )) && return 0
    return 1
}

main "$@"
