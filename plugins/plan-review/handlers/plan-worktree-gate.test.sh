#!/usr/bin/env bash
# Regression suite for plan-worktree-gate.py. Run: ./plan-worktree-gate.test.sh
# All cases avoid live codex calls by using a stub or a PATH without codex.
set -u
G="$(cd "$(dirname "$0")" && pwd)/plan-worktree-gate.py"
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
has_str() { grep -qF "$2" "$1" && echo yes || echo no; }

CX="$T/cx"; mkdir -p "$CX"
cat > "$CX/codex" <<'CXEOF'
#!/usr/bin/env bash
touch "${CODEX_MARKER:?}"
out=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
cat > /dev/null
printf '%b' "${CODEX_OUTPUT:-WORKTREE: not-needed — trivial\n}" > "$out"
CXEOF
chmod +x "$CX/codex"
MARK="$T/codex-called"
called() { [ -e "$MARK" ] && echo yes || echo no; }

NW="$T/non-worktree"; mkdir -p "$NW"
BASE="$(py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\nNone.'},'cwd':'$NW'}")"

rm -f "$MARK"
echo "$BASE" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CLAUDE_PLAN_WORKTREE_GATE=0 "$G" > "$T/o"; rc=$?
check disabled "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

rm -f "$MARK"
py '{"tool_name":"Bash","tool_input":{}}' | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
check wrong-tool "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

rm -f "$MARK"
py '{"tool_name":"ExitPlanMode","tool_input":{"plan":"   "}}' | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
check blank-plan "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

WT="$T/repo/.claude/worktrees/feature/nested"; mkdir -p "$WT"
rm -f "$MARK"
py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\nNone.'},'cwd':'$WT'}" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
check worktree-path "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

rm -f "$MARK"
py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\n## Git Isolation Strategy\\n\\n- use worktree\\n\\n## Open Unknowns\\nNone.'},'cwd':'$NW'}" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
check heading-present "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

rm -f "$MARK"
py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files'},'cwd':'$NW'}" | env -u CLAUDE_PLAN_UNKNOWNS_GATE PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
check defer-to-unknowns "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"

rm -f "$MARK"
echo "$BASE" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT='WORKTREE: not-needed — trivial\n' "$G" > "$T/o"; rc=$?
check not-needed-soft "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"

SECTION='## Git Isolation Strategy\n\n- **Create worktree** — use EnterWorktree.\n- **Seed changes** — carry untracked files explicitly.\n'
rm -f "$MARK"
echo "$BASE" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" "$G" > "$T/o"; rc=$?
check needed-soft "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"
check needed-soft-section yes "$(has_str $T/o 'carry untracked files explicitly')"
check needed-soft-enforcement yes "$(has_str $T/o 'Set CLAUDE_PLAN_WORKTREE_REQUIRE=1 to enforce.')"

rm -f "$MARK"
echo "$BASE" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLAN_WORKTREE_REQUIRE=1 "$G" > "$T/o"; rc=$?
check needed-hard "deny rc0 yes" "$(decision $T/o) rc$rc $(called)"
check needed-hard-section yes "$(has_str $T/o 'carry untracked files explicitly')"

echo "$BASE" | PATH=/usr/bin:/bin "$G" > "$T/o"; rc=$?
check missing-codex-soft "allow rc0" "$(outcome $T/o) rc$rc"
echo "$BASE" | PATH=/usr/bin:/bin CLAUDE_PLAN_WORKTREE_REQUIRE=1 "$G" > "$T/o"; rc=$?
check missing-codex-hard "deny rc0" "$(decision $T/o) rc$rc"
check missing-codex-reason yes "$(has_str $T/o 'untracked files')"

echo 'not json' | "$G" > "$T/o"; rc=$?
check malformed-stdin "allow rc0" "$(outcome $T/o) rc$rc"

rm -f "$MARK"
py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate many files'},'cwd':'$NW'}" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLAN_UNKNOWNS_GATE=0 "$G" > "$T/o"; rc=$?
check unknowns-disabled-runs "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"
check unknowns-disabled-section yes "$(has_str $T/o 'carry untracked files explicitly')"

python3 - "$G" <<'EOF' || fails=$((fails+1))
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
sec = g.extract_section("Sure!\n##Git Isolation Strategy\n- **Create** — worktree.\n")
assert sec is not None and sec.startswith("## Git Isolation Strategy\n"), sec
assert g.has_isolation_heading("# P\n\n" + sec)
assert not g.has_isolation_heading("# P\n```\n## Git Isolation Strategy\n```")
assert not g.has_unknowns_heading("# P\n~~~\n## Open Unknowns\n~~~")
big = "## Git Isolation Strategy\n" + ("- bullet\n" * 3000)
assert g.extract_section(big).endswith("(truncated)")
assert g.extract_section("## Git Isolation Strategy\n\n\n") is None
print("PASS normalize/truncate/empty-section/fence-awareness")
EOF

PL="$T/plans"; mkdir -p "$PL"
PFP="$T/plan-memo.md"
MEMO_PAYLOAD="$(py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\nNone.','planFilePath':'$PFP'},'cwd':'$NW'}")"

rm -f "$MARK"
echo "$MEMO_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; rc=$?
check memoize-first "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"
rm -f "$MARK"
echo "$MEMO_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; rc=$?
check memoize-skip "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"
check memoize-skip-section yes "$(has_str $T/o 'carry untracked files explicitly')"

EDITED_PAYLOAD="$(py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\nNone.\\nEdited.','planFilePath':'$PFP'},'cwd':'$NW'}")"
rm -f "$MARK"
echo "$EDITED_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; rc=$?
check memoize-invalidate "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"

DEFER_PAYLOAD="$(py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\n\\n- Verify runtime behavior. [investigate]','planFilePath':'$T/plan-defer.md'},'cwd':'$NW'}")"
: > "$PL/.needs-investigation-plan-defer"
rm -f "$PL/.investigated-plan-defer" "$PL/.investigation-waived-plan-defer" "$PL/.worktree-assessed-plan-defer" "$MARK"
echo "$DEFER_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; rc=$?
check investigation-defer "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"
: > "$PL/.investigation-waived-plan-defer"
rm -f "$MARK"
echo "$DEFER_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" CODEX_OUTPUT="$SECTION" CLAUDE_PLANS_DIR="$PL" "$G" > "$T/o"; rc=$?
check investigation-waived-runs "allow rc0 yes" "$(outcome $T/o) rc$rc $(called)"

if command -v git >/dev/null 2>&1; then
    REPO="$T/git-repo"; LINKED="$T/linked-wt"
    git init -q "$REPO"
    git -C "$REPO" config user.email test@example.com
    git -C "$REPO" config user.name "Test User"
    : > "$REPO/initial"
    git -C "$REPO" add initial
    git -C "$REPO" commit -qm initial
    git -C "$REPO" worktree add -q "$LINKED" -b linked-branch
    LINKED_PAYLOAD="$(py "{'tool_name':'ExitPlanMode','tool_input':{'plan':'# P\\n\\nmutate files\\n\\n## Open Unknowns\\nNone.'},'cwd':'$LINKED'}")"
    rm -f "$MARK"
    echo "$LINKED_PAYLOAD" | PATH="$CX:/usr/bin:/bin" CODEX_MARKER="$MARK" "$G" > "$T/o"; rc=$?
    check git-worktree-branch "allow rc0 no" "$(outcome $T/o) rc$rc $(called)"
else
    echo "SKIP git-worktree-branch (git unavailable)"
fi

echo; [ "$fails" -eq 0 ] && echo "ALL PASS" || echo "$fails FAILURE(S)"; exit "$fails"
