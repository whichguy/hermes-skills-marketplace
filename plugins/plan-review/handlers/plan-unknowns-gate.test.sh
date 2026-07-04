#!/usr/bin/env bash
# Regression suite for plan-unknowns-gate.py. Run: ./plan-unknowns-gate.test.sh
# All cases avoid live codex calls (PATH-stripped where a deny is expected).
set -u
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

# --- CLAUDE_PLAN_INVESTIGATE advisory (opt-in; must not change decisions) ---
# distinctive to INVESTIGATE_ADVISORY only (deny reasons also mention /investigate-plan)
has_adv() { grep -qF 'resolves the researchable' "$1" && echo yes || echo no; }
NOUNK='{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\nsteps only"},"cwd":"/tmp"}'
WITHUNK='{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\n## Open Unknowns\nNone."}}'
# deny path: advisory absent when off, present when on; decision stays deny both ways
echo "$NOUNK" | PATH=/usr/bin:/bin CLAUDE_PLAN_INVESTIGATE=0 "$G" > "$T/o"; check adv-off-deny "deny no"  "$(decision $T/o) $(has_adv $T/o)"
echo "$NOUNK" | PATH=/usr/bin:/bin CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o"; check adv-on-deny  "deny yes" "$(decision $T/o) $(has_adv $T/o)"
# allow path: off = bare allow (empty stdout); on = allow (no decision) + advisory in systemMessage
echo "$WITHUNK" | CLAUDE_PLAN_INVESTIGATE=0 "$G" > "$T/o"; check adv-off-allow "allow no" "$(outcome $T/o) $(has_adv $T/o)"
echo "$WITHUNK" | CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o"; check adv-on-allow  "allow yes" "$(outcome $T/o) $(has_adv $T/o)"

# --- Stage/state-machine cases: sentinels in an isolated CLAUDE_PLANS_DIR -----
PL="$T/plans"; mkdir -p "$PL"
mkplan() { printf '%b' "$2" > "$PL/$1.md"; }               # mkplan slug content
pf() { python3 -c "import json,sys; print(json.dumps({'tool_name':'ExitPlanMode','tool_input':{'plan':'','planFilePath':sys.argv[1]},'cwd':'/tmp'}))" "$PL/$1.md"; }
has_str() { grep -qF "$2" "$1" && echo yes || echo no; }
# stub bins
UP="$T/up"; DOWN="$T/down"; CX="$T/cx"; mkdir -p "$UP" "$DOWN" "$CX"
printf '#!/usr/bin/env bash\necho true\n'  > "$UP/docker";  chmod +x "$UP/docker"
printf '#!/usr/bin/env bash\necho false\n' > "$DOWN/docker"; chmod +x "$DOWN/docker"
# codex stub: parse -o OUTFILE, emit a canned section (arg $CX_TAG controls [investigate])
cat > "$CX/codex" <<'CXEOF'
#!/usr/bin/env bash
out=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
cat > /dev/null
tag="${CX_TAG:-}"
printf '## Open Unknowns\n- **thing** — matters. *Resolve:* probe it. %s\n' "$tag" > "$out"
CXEOF
chmod +x "$CX/codex"

# Stage 1: review gate. rev plan has heading + no [investigate] -> Stages 2/3 pass.
mkplan rev '# P\n\nsteps\n\n## Open Unknowns\nNone.'
pf rev | CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o";                       check s1-soft-allow      allow "$(outcome $T/o)"
pf rev | CLAUDE_PLANS_DIR="$PL" CLAUDE_PLAN_REQUIRE_REVIEW=1 "$G" > "$T/o"; check s1-hard-deny  deny  "$(decision $T/o)"
touch "$PL/.review-ready-rev"
pf rev | CLAUDE_PLANS_DIR="$PL" CLAUDE_PLAN_REQUIRE_REVIEW=1 "$G" > "$T/o"; check s1-hard-satisfied allow "$(outcome $T/o)"
rm -f "$PL/.review-ready-rev"

# Stage 2: codex tags [investigate] -> needs-investigation sentinel written + deny
mkplan nh '# P\n\njust steps, no audit'
pf nh | PATH="$CX:/usr/bin:/bin" CX_TAG='[investigate]' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check s2-agentic-deny deny "$(decision $T/o)"
check s2-sentinel-written yes "$([ -f "$PL/.needs-investigation-nh" ] && echo yes || echo no)"
# Stage 2: codex, no tag -> deny but NO needs-investigation sentinel
mkplan nh2 '# P\n\njust steps'
pf nh2 | PATH="$CX:/usr/bin:/bin" CX_TAG='' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check s2-repo-deny deny "$(decision $T/o)"
check s2-no-sentinel no "$([ -f "$PL/.needs-investigation-nh2" ] && echo yes || echo no)"

# Stage 3: heading present + [investigate] in plan; container up -> deny
mkplan inv '# P\n\nsteps\n\n## Open Unknowns\n- **live** — matters. *Resolve:* probe. [investigate]'
pf inv | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-required-deny deny "$(decision $T/o)"
# investigated sentinel -> allow
touch "$PL/.investigated-inv"
pf inv | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-investigated-allow allow "$(outcome $T/o)"
rm -f "$PL/.investigated-inv"
# waived sentinel -> allow
touch "$PL/.investigation-waived-inv"
pf inv | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-waived-allow allow "$(outcome $T/o)"
rm -f "$PL/.investigation-waived-inv"
# container down -> fail open (allow) even with unresolved agentic unknowns
pf inv | PATH="$DOWN:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-container-down-allow allow "$(outcome $T/o)"
# needs-investigation sentinel (no [investigate] in plan text) + up -> deny
mkplan inv2 '# P\n\nsteps\n\n## Open Unknowns\nNone visible.'
touch "$PL/.needs-investigation-inv2"
pf inv2 | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-sentinel-deny deny "$(decision $T/o)"
# inline [investigate] but NO planFilePath (no slug) -> can't track state -> allow
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"# P\n\n## Open Unknowns\n- x [investigate]"},"cwd":"/tmp"}' | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-no-slug-allow allow "$(outcome $T/o)"

# Stage 3 menu is opt-in; default remains the plain investigation-required deny.
mkplan inv-menu '# P\n\nsteps\n\n## Open Unknowns\n- **live** — matters. *Resolve:* probe. [investigate]'
rm -f "$PL/.investigated-inv-menu" "$PL/.investigation-waived-inv-menu"
pf inv-menu | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" CLAUDE_PLAN_INVESTIGATE=1 "$G" > "$T/o"
check s3-menu-on-deny deny "$(decision $T/o)"
check s3-menu-on-askuserquestion yes "$(has_str $T/o 'AskUserQuestion')"
check s3-menu-on-investigate-now yes "$(has_str $T/o 'Investigate now')"
check s3-menu-on-waive-investigation yes "$(has_str $T/o 'Waive investigation')"
check s3-menu-on-revise-plan yes "$(has_str $T/o "I'll revise the plan")"
rm -f "$PL/.investigated-inv-menu" "$PL/.investigation-waived-inv-menu"
pf inv-menu | env -u CLAUDE_PLAN_INVESTIGATE PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check s3-menu-off-deny deny "$(decision $T/o)"
check s3-menu-off-plain-text no "$(has_str $T/o 'AskUserQuestion')"
check s3-menu-off-investigate-plan yes "$(has_str $T/o '/investigate-plan')"
check s3-menu-off-waive-investigation yes "$(has_str $T/o '/waive-investigation')"
rm -f "$PL/.investigated-inv-menu" "$PL/.investigation-waived-inv-menu"

# Stage 3: prose and fenced mentions are not active investigation tags.
mkplan inv-prose '# P\n\nsteps\n\n## Open Unknowns\n- the [investigate] tag is documented here, not a real tag'
pf inv-prose | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-prose-tag-allow allow "$(outcome $T/o)"
mkplan inv-fenced '# P\n\nsteps\n\n## Open Unknowns\n```\n- example [investigate]\n```'
pf inv-fenced | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-fenced-tag-allow allow "$(outcome $T/o)"
# Stage 3: a bullet ending with [investigate] still requires investigation.
mkplan inv-tagged '# P\n\nsteps\n\n## Open Unknowns\n- **x** — matters. *Resolve:* probe. [investigate]'
pf inv-tagged | PATH="$UP:/usr/bin:/bin" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; check s3-ending-tag-deny deny "$(decision $T/o)"

# Stage 2: only an end-of-bullet Codex tag writes the investigation sentinel.
mkplan nh-prose '# P\n\njust steps, no audit'
pf nh-prose | PATH="$CX:/usr/bin:/bin" CX_TAG='[investigate] is documented here' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check s2-prose-tag-deny deny "$(decision $T/o)"
check s2-prose-no-sentinel no "$([ -f "$PL/.needs-investigation-nh-prose" ] && echo yes || echo no)"
mkplan nh-tagged '# P\n\njust steps, no audit'
pf nh-tagged | PATH="$CX:/usr/bin:/bin" CX_TAG='[investigate]' CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"
check s2-ending-tag-deny deny "$(decision $T/o)"
check s2-ending-tag-sentinel yes "$([ -f "$PL/.needs-investigation-nh-tagged" ] && echo yes || echo no)"
rm -f "$PL/.needs-investigation-nh-prose" "$PL/.needs-investigation-nh-tagged"

# Cleanup hook removes the investigation sentinels but LEAVES .review-ready
# (owned by review-plan / the plugin's own cleanup).
CLEAN="$(cd "$(dirname "$0")" && pwd)/plan-review-cleanup.py"
[ -x "$CLEAN" ] || CLEAN="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/plan-review-cleanup.py"
for k in review-ready needs-investigation investigated investigation-waived; do touch "$PL/.$k-inv"; done
pf inv | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
check cleanup-removes-investigation no "$([ -e "$PL/.needs-investigation-inv" ] || [ -e "$PL/.investigated-inv" ] || [ -e "$PL/.investigation-waived-inv" ] && echo yes || echo no)"
check cleanup-keeps-review-ready yes "$([ -e "$PL/.review-ready-inv" ] && echo yes || echo no)"
rm -f "$PL"/.*-inv

touch "$PL/.needs-investigation-my-plan-" "$PL/.worktree-assessed-my-plan-"
pf "my plan!" | CLAUDE_PLANS_DIR="$PL" "$CLEAN" >/dev/null 2>&1
check cleanup-removes-special-char-needsinv yes "$([ ! -e "$PL/.needs-investigation-my-plan-" ] && echo yes || echo no)"
check cleanup-removes-special-char-worktree yes "$([ ! -e "$PL/.worktree-assessed-my-plan-" ] && echo yes || echo no)"
rm -f "$PL/.needs-investigation-my-plan-" "$PL/.worktree-assessed-my-plan-"

python3 - "$G" <<'EOF' || fails=$((fails+1))
import importlib.util, subprocess, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
sec = g.extract_section("Sure! Here it is:\n##Open Unknowns\n- **thing** — matters. *Suggestion:* do X.\n")
assert sec is not None and sec.startswith("## Open Unknowns\n"), sec
assert g.has_unknowns_heading("# P\n\n" + sec)
big = "## Open Unknowns\n" + ("- bullet\n" * 3000)
assert g.extract_section(big).endswith("(truncated)")
assert g.extract_section("## Open Unknowns\n\n\n") is None

def shell_slug(base):
    proc = subprocess.run(
        "tr -c 'A-Za-z0-9._-' '-' | cut -c1-64",
        shell=True,
        input=base.encode("utf-8"),
        stdout=subprocess.PIPE,
        check=True,
    )
    return proc.stdout.decode("ascii").rstrip("\n")

assert g.plan_slug({"planFilePath": "/a/b/my-plan.md"}) == shell_slug("my-plan")
print("PASS slug-plain")
assert g.plan_slug({"planFilePath": "/a/b/my plan review.md"}) == shell_slug("my plan review")
print("PASS slug-spaces")
assert g.plan_slug({"planFilePath": "/a/b/plañ-résumé.md"}) == shell_slug("plañ-résumé")
print("PASS slug-unicode")
long_base = "abcdefghij" * 8
long_slug = g.plan_slug({"planFilePath": "/a/b/" + long_base + ".md"})
assert long_slug == shell_slug(long_base) and len(long_slug) == 64
print("PASS slug-truncated")
assert shell_slug("") == ""
assert g.plan_slug({"planFilePath": "/foo/bar/.md"}) == "plan"
print("PASS slug-empty-fallback")
assert g.plan_slug({}) is None
print("PASS normalize/truncate/empty-section/no-path-slug")
EOF

echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILURE(S)"; exit "$fails"
