#!/usr/bin/env bash
# Regression suite for plan-unknowns-gate.py. Run: ./plan-unknowns-gate.test.sh
# All cases avoid live codex calls (PATH-stripped where a deny is expected).
set -u
# Hermetic: CLAUDE_PLAN_* switch gate behaviour on/off. A developer shell that exports one
# (e.g. CLAUDE_PLAN_WORKTREE_GATE=0) must not change this suite's outcome — it once turned 14
# of this family's cases red on a laptop while CI (clean env) stayed green.
for v in $(compgen -e | grep '^CLAUDE_PLAN'); do unset "$v"; done
G="$(cd "$(dirname "$0")" && pwd)/plan-unknowns-gate.py"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fails=0
py() { python3 -c "import json,sys; print(json.dumps($1))"; }
check() { [ "$3" = "$2" ] && echo "PASS $1" || { echo "FAIL $1 (want $2, got $3)"; fails=$((fails+1)); }; }
decision() { python3 -c "import json;print(json.load(open('$1'))['hookSpecificOutput']['permissionDecision'])" 2>/dev/null; }
outcome() { [ -s "$1" ] && python3 -c "
import json
try:
    d = json.load(open('$1'))
    print('deny' if d.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny' else 'allow')
except Exception:
    print('allow')
" || echo allow; }

py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\nstuff\n\n## Open Unknowns\n\n- none"}}' | "$G" > "$T/o"; check marker-present allow "$(outcome $T/o)"
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\nno section"}}' | CLAUDE_PLAN_UNKNOWNS_GATE=0 "$G" > "$T/o"; check opt-out allow "$(outcome $T/o)"
echo 'not json' | "$G" > "$T/o"; check malformed-stdin "allow rc0" "$(outcome $T/o) rc$?"
py '{"tool_name":"Bash","tool_input":{}}' | "$G" > "$T/o"; check wrong-tool allow "$(outcome $T/o)"
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\nsteps only"},"cwd":"/tmp"}' | PATH=/usr/bin:/bin "$G" > "$T/o"; check no-codex-fallback deny "$(decision $T/o)"

for p in 'null' '[1,2]' '{"tool_name":"ExitPlanMode","tool_input":null}' '{"tool_name":"ExitPlanMode","tool_input":{"plan":123}}' '{"tool_name":"ExitPlanMode","tool_input":{"plan":null,"planFilePath":42}}'; do
  echo "$p" | "$G" > "$T/o"; rc=$?
  check "shape:$p" "allow rc0" "$(outcome $T/o) rc$rc"
done

printf '# Plan\n\xff\xfe broken bytes, no audit\n' > "$T/bad.md"
py "{\"tool_name\":\"ExitPlanMode\",\"tool_input\":{\"plan\":\"\",\"planFilePath\":\"$T/bad.md\"},\"cwd\":\"/tmp\"}" | PATH=/usr/bin:/bin "$G" > "$T/o"; rc=$?
check bad-utf8 "deny rc0" "$(decision $T/o) rc$rc"

py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\n```\n## Open Unknowns\n```\nsteps"},"cwd":"/tmp"}' | PATH=/usr/bin:/bin "$G" > "$T/o"; check fenced-heading-ignored deny "$(decision $T/o)"
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"#\nthese unknowns are prose\nsteps"},"cwd":"/tmp"}' | PATH=/usr/bin:/bin "$G" > "$T/o"; check newline-cross-ignored deny "$(decision $T/o)"
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\n  ## Open Unknowns\n- x"}}' | "$G" > "$T/o"; check indented-heading allow "$(outcome $T/o)"

# --- the removed investigation stage must stay removed ---
# CLAUDE_PLAN_INVESTIGATE used to append an advisory, and a closed-loop stage waited for /investigate-plan. Neither
# exists now: the variable has no effect, and no deny text names /investigate-plan or the [investigate] tag.
has_str() { grep -qF "$2" "$1" && echo yes || echo no; }
NOUNK='{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\nsteps only"},"cwd":"/tmp"}'
WITHUNK='{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\n## Open Unknowns\nNone."}}'
echo "$NOUNK" | PATH=/usr/bin:/bin CLAUDE_PLAN_INVESTIGATE=0 "$G" > "$T/o0"
echo "$NOUNK" | PATH=/usr/bin:/bin CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o1"
check env-var-no-effect-on-deny same "$(cmp -s "$T/o0" "$T/o1" && echo same || echo different)"
check fallback-deny deny "$(decision $T/o1)"
check fallback-asks-for-heading yes "$(has_str $T/o1 'Open Unknowns')"
check fallback-no-investigate-plan no "$(has_str $T/o1 '/investigate-plan')"
check fallback-no-investigate-tag no "$(has_str $T/o1 '[investigate]')"
echo "$WITHUNK" | CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o"
check env-var-allow-is-bare allow "$(outcome $T/o)"
check env-var-allow-no-output no "$([ -s "$T/o" ] && echo yes || echo no)"

# --- Unknowns audit with a Codex stub, in an isolated CLAUDE_PLANS_DIR ---
PL="$T/plans"; mkdir -p "$PL"
mkplan() { printf '%b' "$2" > "$PL/$1.md"; }               # mkplan slug content
pf() { python3 -c "import json,sys; print(json.dumps({'tool_name':'ExitPlanMode','tool_input':{'plan':'','planFilePath':sys.argv[1]},'cwd':'/tmp'}))" "$PL/$1.md"; }
# stub bins: a codex that emits a canned section ($CX_TAG is appended to the bullet), a docker that claims any container is up
CX="$T/cx"; UP="$T/up"; mkdir -p "$CX" "$UP"
cat > "$CX/codex" <<'CXEOF'
#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
cat > /dev/null
tag="${CX_TAG:-}"
printf '## Open Unknowns\n- **thing** — matters. *Resolve:* probe it. %s\n' "$tag" > "$out"
CXEOF
chmod +x "$CX/codex"
printf '#!/usr/bin/env bash\necho true\n' > "$UP/docker"; chmod +x "$UP/docker"

# Clean pass: heading present -> allow. (The former review-sentinel stage was removed 2026-07-26; that question is
# owned by plan-oversight/soft_exit.py. CLAUDE_PLAN_REQUIRE_REVIEW has no effect here, so it is asserted to be inert.)
mkplan rev '# P\n\nsteps\n\n## Open Unknowns\nNone.'
pf rev | CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o";                       check clean-allow        allow "$(outcome $T/o)"
pf rev | CLAUDE_PLANS_DIR="$PL" CLAUDE_PLAN_REQUIRE_REVIEW=1 "$G" > "$T/o"; check require-review-inert allow "$(outcome $T/o)"

# Codex returns a section: the deny carries it, with or without the retired tag, and nothing is written to the plans dir.
mkplan nh '# P\n\njust steps, no audit'
pf nh | PATH="$CX:/usr/bin:/bin" CX_TAG='' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check codex-deny deny "$(decision $T/o)"
check codex-deny-carries-section yes "$(has_str $T/o 'probe it')"
check codex-deny-no-investigate-plan no "$(has_str $T/o '/investigate-plan')"
check codex-deny-no-tag-instruction no "$(has_str $T/o 'Items tagged')"
pf nh | PATH="$CX:/usr/bin:/bin" CX_TAG='[investigate]' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check codex-tagged-deny deny "$(decision $T/o)"
check codex-tagged-writes-no-sentinel 0 "$(find "$PL" -mindepth 1 -maxdepth 1 -name '.*' | wc -l | tr -d ' ')"

# The retired closed loop: a plan with an [investigate] bullet is allowed, even with a container up and the old switch on.
mkplan inv '# P\n\nsteps\n\n## Open Unknowns\n- **live** — matters. *Resolve:* probe. [investigate]'
pf inv | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check tagged-plan-allowed allow "$(outcome $T/o)"
pf inv | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o"; check tagged-plan-allowed-old-switch-on allow "$(outcome $T/o)"

# Cleanup hook removes exactly its own sentinel and nothing else. An unrelated marker stands in for "everything else":
# the property under test is "cleanup stays inside its KINDS list", not the specific neighbour file.
CLEAN="$(cd "$(dirname "$0")" && pwd)/plan-review-cleanup.py"
[ -x "$CLEAN" ] || CLEAN="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/plan-review-cleanup.py"
for k in unrelated-marker worktree-assessed; do touch "$PL/.$k-inv"; done
pf inv | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
check cleanup-removes-worktree-sentinel no "$([ -e "$PL/.worktree-assessed-inv" ] && echo yes || echo no)"
check cleanup-stays-in-scope yes "$([ -e "$PL/.unrelated-marker-inv" ] && echo yes || echo no)"
rm -f "$PL"/.*-inv
touch "$PL/.needs-investigation-inv" "$PL/.investigated-inv" "$PL/.investigation-waived-inv"
pf inv | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
check cleanup-ignores-retired-investigation-sentinels 3 "$(find "$PL" -mindepth 1 -maxdepth 1 \( -name '.needs-investigation-inv' -o -name '.investigated-inv' -o -name '.investigation-waived-inv' \) | wc -l | tr -d ' ')"
rm -f "$PL"/.*-inv

touch "$PL/.worktree-assessed-my-plan-"
pf "my plan!" | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
check cleanup-removes-special-char-worktree yes "$([ ! -e "$PL/.worktree-assessed-my-plan-" ] && echo yes || echo no)"
rm -f "$PL/.worktree-assessed-my-plan-"

# The worktree gate names the sentinel and cleanup removes it, each deriving the slug from the plan path on its own.
# (The unknowns gate's slug helper went with the investigation stage, so this pairing is the invariant that is left.)
WG="$(cd "$(dirname "$0")" && pwd)/plan-worktree-gate.py"
for name in "my plan!" "Plan  With   Spaces" "UPPER.case" "dots.in.name" "ünï-çødé" "$(printf 'x%.0s' $(seq 1 100))"; do
  slug="$(python3 -I -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('wg',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.plan_slug({'planFilePath': sys.argv[2]}))" "$WG" "/x/$name.md")"
  touch "$PL/.worktree-assessed-$slug"
  pf "$name" | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
  check "slug-parity-${#slug}-$(printf '%s' "$slug" | cut -c1-12)" yes "$([ ! -e "$PL/.worktree-assessed-$slug" ] && echo yes || echo no)"
  rm -f "$PL/.worktree-assessed-$slug"
done

python3 - "$G" <<'EOF' || fails=$((fails+1))
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
sec = g.extract_section("Sure! Here it is:\n##Open Unknowns\n- **thing** — matters. *Suggestion:* do X.\n")
assert sec is not None and sec.startswith("## Open Unknowns\n"), sec
assert g.has_unknowns_heading("# P\n\n" + sec)
big = "## Open Unknowns\n" + ("- bullet\n" * 3000)
assert g.extract_section(big).endswith("(truncated)")
assert g.extract_section("## Open Unknowns\n\n\n") is None
print("PASS normalize/truncate/empty-section")
EOF

echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILURE(S)"; exit "$fails"
