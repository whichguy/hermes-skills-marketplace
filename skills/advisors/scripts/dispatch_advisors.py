#!/usr/bin/env python3
"""
Dispatch advisors with file-referenced context — separates the data channel
from the controller's context window.

Architecture:
  Brief file (disk) ──→ seats read via -t file ──→ seat outputs (disk)
  Seat outputs (disk) ──→ GLM reads via -t file ──→ synthesis (disk)
  Controller reads only synthesis.md (~1-2K chars) into context

The controller's context never carries the data payload — only short prompts
with file paths. This keeps the running conversation clean and avoids polluting
30-90K chars of review data that's never useful again after synthesis.

Usage (CLI):
  # All-in-one: prepare brief, dispatch seats, synthesize
  python3 dispatch_advisors.py run \
      --question "Should we use PostgreSQL or MongoDB?" \
      --context-file /opt/data/wiki/design.md \
      --outdir /tmp/advisors \
      --seats "deepseek-v4-pro:cloud|Reasoner,kimi-k2.7-code:cloud|Coder" \
      --toolsets file,web

  # Step-by-step (controller wants more control)
  python3 dispatch_advisors.py prepare \
      --question "..." --context-file design.md --outdir /tmp/advisors

  python3 dispatch_advisors.py dispatch \
      --brief /tmp/advisors/brief.md --outdir /tmp/advisors \
      --seats "deepseek-v4-pro:cloud|Reasoner,kimi-k2.7-code:cloud|Coder"

  python3 dispatch_advisors.py synthesize \
      --brief /tmp/advisors/brief.md --outdir /tmp/advisors \
      --model glm-5.2:cloud

Usage (Python import from execute_code):
  import sys
  sys.path.insert(0, '/opt/data/skills/autonomous-ai-agents/advisors/scripts')
  from dispatch_advisors import AdvisorDispatch

  ad = AdvisorDispatch(outdir='/tmp/advisors')
  ad.prepare_brief(question="...", context_file="/path/to/data.md")
  ad.dispatch(seats=[("deepseek-v4-pro:cloud", "Reasoner"), ("kimi-k2.7-code:cloud", "Coder")], toolsets="file,web")
  ad.synthesize(model="glm-5.2:cloud")
  print(ad.read_synthesis())  # ~1-2K chars into context
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import uuid

# ── Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASK_SCRIPTS_DIR = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "..", "..", "productivity", "ask", "scripts")
)
PROMPT_MODEL = os.path.join(SCRIPT_DIR, "prompt_model.py")

# ── Default panel
DEFAULT_SEATS = [
    ("deepseek-v4-pro:cloud", "Reasoner"),
    ("kimi-k2.7-code:cloud", "Coder"),
    ("minimax-m3:cloud", "Third Seat"),
]
DEFAULT_SYNTHESIS_MODEL = "glm-5.2:cloud"
DEFAULT_TOOLSETS = "file,web"

# ── Seat prompt template — short, references brief file
SEAT_PROMPT_TEMPLATE = (
    "Read the brief at {brief_path} and provide your analysis. "
    "The brief contains the question and all relevant context. "
    "Read it fully before responding."
)

# ── Synthesis prompt template — references seat files on disk
SYNTHESIS_PROMPT_TEMPLATE = (
    "You are synthesizing advisor reviews. "
    "Read the brief at {brief_path} for the original question and context. "
    "Then read each advisor's review:\n{seat_file_list}\n\n"
    "Produce: agreements, disagreements, final answer, confidence, caveats. "
    "Do NOT split the difference — pick the strongest answer and justify it."
)

# ── Verify-against-source preamble (prevents false positives)
VERIFY_PREAMBLE = (
    "Before identifying issues, verify each claim against the actual source "
    "files. If a file path is mentioned, read it. If you cannot access the "
    "file, mark any claims about it as UNVERIFIED and skip them. Only report "
    "issues you can confirm from the code you actually read.\n\n"
)


class AdvisorDispatch:
    """File-referenced advisor dispatch — keeps data out of controller context.

    Uses run-specific subdirectories to avoid stale file accumulation:
    outdir/
      <run-id>/
        brief.md
        seat-1-reasoner.md
        seat-1-reasoner.err
        seat-2-coder.md
        seat-2-coder.err
        seats.json
        synthesis.md

    The run-id is auto-generated unless outdir is set explicitly (CLI mode).
    """

    def __init__(self, outdir="/tmp/advisors", auto_subdir=True):
        """Initialize dispatch.

        Args:
            outdir: base output directory.
            auto_subdir: if True, create a run-specific subdirectory under
                outdir (e.g., /tmp/advisors/<uuid>/). This eliminates stale-file
                issues across runs. Set False for CLI step-by-step mode where
                the caller manages the directory.
        """
        base = os.path.abspath(outdir)
        if auto_subdir:
            run_id = uuid.uuid4().hex[:8]
            self.outdir = os.path.join(base, run_id)
        else:
            self.outdir = base
        os.makedirs(self.outdir, exist_ok=True)
        self.brief_path = None
        self.seat_results = []

    def _read_file_safe(self, path):
        """Read a file, returning None on error with a warning to stderr."""
        try:
            with open(path) as f:
                return f.read()
        except (OSError, PermissionError) as e:
            print(f"⚠️  Cannot read {path}: {e}", file=sys.stderr)
            return None

    def prepare_brief(self, question, context="", context_file=None,
                      extra_context_files=None, verify_preamble=False):
        """Write the brief (question + all context data) to disk.

        This is the data channel — everything the advisors need lives in this file.
        The controller's context only carries the question string and file paths.

        Both context_file AND inline context can be provided — they're
        concatenated with clear headers (not silently dropped).
        """
        parts = []

        if verify_preamble:
            parts.append(VERIFY_PREAMBLE)

        parts.append(f"## Question\n\n{question}")

        # ── Bug fix A: include both context_file AND inline context, not either/or
        if context_file:
            content = self._read_file_safe(context_file)
            if content is not None:
                parts.append(f"## Context (from {context_file})\n\n{content}")
            else:
                print(f"⚠️  context_file not found or unreadable: {context_file}", file=sys.stderr)

        if context:
            parts.append(f"## Additional Context (inline)\n\n{context}")

        if extra_context_files:
            for cf in extra_context_files:
                content = self._read_file_safe(cf)
                if content is not None:
                    parts.append(f"## Additional Context (from {cf})\n\n{content}")
                else:
                    print(f"⚠️  extra_context_file not found or unreadable: {cf}", file=sys.stderr)

        self.brief_path = os.path.join(self.outdir, "brief.md")
        with open(self.brief_path, "w") as f:
            f.write("\n\n---\n\n".join(parts))
        return self.brief_path

    def dispatch(self, seats=None, toolsets=DEFAULT_TOOLSETS, timeout=300):
        """Dispatch seats in parallel. Each seat reads the brief from disk.

        Args:
            seats: list of (model, role) tuples, or list of model strings.
                   Defaults to DEFAULT_SEATS.
            toolsets: comma-separated toolsets for each seat.
            timeout: per-seat timeout in seconds.

        Returns:
            list of (role, model, elapsed, returncode, outfile) tuples,
            in the same order as the input seats list.
        """
        if not self.brief_path:
            raise ValueError("Call prepare_brief() first")
        if not os.path.exists(self.brief_path):
            raise FileNotFoundError(f"Brief file not found: {self.brief_path}")
        if seats is None:
            seats = DEFAULT_SEATS

        # Normalize seats to (model, role) tuples
        normalized = []
        for s in seats:
            if isinstance(s, str):
                normalized.append((s, s))
            elif isinstance(s, (tuple, list)) and len(s) == 2:
                normalized.append(tuple(s))
            else:
                raise ValueError(f"Invalid seat: {s!r} — must be (model, role) tuple or model string")

        def _sanitize_role(role):
            """Sanitize role name for use in filenames — prevent path traversal."""
            safe = role.replace("/", "-").replace("\\", "-").replace(":", "-")
            safe = safe.replace("..", "_").replace(os.sep, "-")
            return safe.strip() or "seat"

        def dispatch_seat(model, role, index):
            safe_role = _sanitize_role(role.lower().replace(" ", "-"))
            outfile = os.path.join(self.outdir, f"seat-{index+1}-{safe_role}.md")
            errfile = os.path.join(self.outdir, f"seat-{index+1}-{safe_role}.err")
            prompt = SEAT_PROMPT_TEMPLATE.format(brief_path=self.brief_path)
            cmd = [
                sys.executable, PROMPT_MODEL,
                "-m", model,
                "-p", prompt,
                "-t", toolsets,
                "-o", outfile,
                "--timeout", str(timeout),
            ]
            start = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout + 5, cwd=ASK_SCRIPTS_DIR)
            except subprocess.TimeoutExpired:
                elapsed = time.time() - start
                print(f"⏰ {role} ({model}): timed out at {elapsed:.1f}s", file=sys.stderr)
                # Write a marker .err file so the manifest records the failure
                try:
                    with open(errfile, "w") as f:
                        f.write(f"TimeoutExpired after {elapsed:.1f}s\n")
                except OSError:
                    errfile = None
                return index, role, model, elapsed, -1, outfile, errfile, "TimeoutExpired"
            elapsed = time.time() - start
            # ── Bug fix B: preserve stderr to .err file
            if r.stderr.strip():
                with open(errfile, "w") as f:
                    f.write(r.stderr)
            return index, role, model, elapsed, r.returncode, outfile, errfile if r.stderr.strip() else None, r.stderr.strip()

        if not normalized:
            raise ValueError("No seats to dispatch")

        # ── Bug fix #4: preserve input order via index tracking
        indexed_results = []
        collection_timeout = timeout + 30  # defensive bound on as_completed
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(normalized)) as pool:
            futures = [
                pool.submit(dispatch_seat, model, role, i)
                for i, (model, role) in enumerate(normalized)
            ]
            for fut in concurrent.futures.as_completed(futures, timeout=collection_timeout):
                idx, role, model, elapsed, rc, outfile, errfile, err = fut.result()
                status = "✅" if rc == 0 else "❌"
                print(f"{status} {role} ({model}): {elapsed:.1f}s", file=sys.stderr)
                if err and rc != 0:
                    print(f"   error: {err[:200]}", file=sys.stderr)
                indexed_results.append((idx, role, model, elapsed, rc, outfile, errfile))

        # Sort by index to preserve input order
        indexed_results.sort(key=lambda x: x[0])
        results = [(role, model, elapsed, rc, outfile) for _, role, model, elapsed, rc, outfile, _ in indexed_results]
        self.seat_results = results

        # ── Bug fix #6: write seats.json manifest with errfile paths
        manifest = [
            {
                "role": role,
                "model": model,
                "outfile": outfile,
                "returncode": rc,
                "errfile": errfile,
            }
            for (idx, role, model, elapsed, rc, outfile, errfile) in indexed_results
        ]
        manifest_path = os.path.join(self.outdir, "seats.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        return results

    def synthesize(self, model=DEFAULT_SYNTHESIS_MODEL, timeout=120):
        """Dispatch GLM synthesis reading seat files from disk.

        The synthesis model reads the brief + all seat outputs from disk.
        Only the small synthesis file (~1-2K chars) needs to enter controller context.
        """
        if not self.seat_results:
            raise ValueError("Call dispatch() first")

        seat_files = []
        for role, model_name, elapsed, rc, outfile in self.seat_results:
            # ── Bug fix F: check file size, not just existence
            if rc == 0 and os.path.exists(outfile) and os.path.getsize(outfile) > 0:
                seat_files.append(f"- {outfile} ({role}, {model_name})")

        # ── Bug fix #5: short-circuit if no seats succeeded
        if not seat_files:
            print("⚠️  No successful seat outputs to synthesize", file=sys.stderr)
            return None

        seat_file_list = "\n".join(seat_files)
        prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            brief_path=self.brief_path,
            seat_file_list=seat_file_list,
        )

        synthesis_path = os.path.join(self.outdir, "synthesis.md")
        cmd = [
            sys.executable, PROMPT_MODEL,
            "-m", model,
            "-p", prompt,
            "-t", "file",
            "-o", synthesis_path,
            "--timeout", str(timeout),
        ]
        # ── Bug fix C: fix double timeout in synthesize too (was timeout + 30)
        r = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout + 5, cwd=ASK_SCRIPTS_DIR)
        if r.returncode != 0:
            print(f"❌ Synthesis failed: {r.stderr[:300]}", file=sys.stderr)
            return None
        # ── DeepSeek bug #2: check synthesis output isn't empty
        if not os.path.exists(synthesis_path) or os.path.getsize(synthesis_path) == 0:
            print("❌ Synthesis produced empty output", file=sys.stderr)
            return None
        print(f"✅ Synthesis ({model}) → {synthesis_path}", file=sys.stderr)
        return synthesis_path

    def read_synthesis(self):
        """Read the synthesis file into context (~1-2K chars).

        Returns None if the file doesn't exist or is empty.
        """
        path = os.path.join(self.outdir, "synthesis.md")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        with open(path) as f:
            return f.read()

    def read_seat(self, index=0):
        """Read a single seat's output by input order index (use sparingly)."""
        if index < len(self.seat_results):
            _, _, _, _, outfile = self.seat_results[index]
            if os.path.exists(outfile) and os.path.getsize(outfile) > 0:
                with open(outfile) as f:
                    return f.read()
        return None

    def read_seat_stderr(self, index=0):
        """Read a seat's stderr log (from .err file). Returns None if no .err file."""
        manifest_path = os.path.join(self.outdir, "seats.json")
        if not os.path.exists(manifest_path):
            return None
        with open(manifest_path) as f:
            manifest = json.load(f)
        if index < len(manifest):
            errfile = manifest[index].get("errfile")
            if errfile and os.path.exists(errfile):
                with open(errfile) as f:
                    return f.read()
        return None


# ── CLI

def cli_prepare(args):
    ad = AdvisorDispatch(outdir=args.outdir, auto_subdir=False)
    path = ad.prepare_brief(
        question=args.question,
        context=args.context,
        context_file=args.context_file,
        extra_context_files=args.extra_context,
        verify_preamble=args.verify,
    )
    print(path)


def cli_dispatch(args):
    ad = AdvisorDispatch(outdir=args.outdir, auto_subdir=False)
    if not os.path.exists(args.brief):
        print(f"Error: brief file not found: {args.brief}", file=sys.stderr)
        sys.exit(1)
    ad.brief_path = os.path.abspath(args.brief)
    seats = parse_seats(args.seats)
    results = ad.dispatch(seats=seats, toolsets=args.toolsets, timeout=args.timeout)
    for role, model, elapsed, rc, outfile in results:
        print(f"{'✅' if rc == 0 else '❌'} {role} ({model}): {elapsed:.1f}s → {outfile}")


def cli_synthesize(args):
    ad = AdvisorDispatch(outdir=args.outdir, auto_subdir=False)
    if not os.path.exists(args.brief):
        print(f"Error: brief file not found: {args.brief}", file=sys.stderr)
        sys.exit(1)
    ad.brief_path = os.path.abspath(args.brief)
    # ── Bug fix D: require seats.json, no fallback to filename scanning
    manifest_path = os.path.join(ad.outdir, "seats.json")
    if not os.path.exists(manifest_path):
        print("Error: seats.json not found. Run 'dispatch' first.", file=sys.stderr)
        sys.exit(1)
    with open(manifest_path) as f:
        manifest = json.load(f)
    ad.seat_results = [
        (entry["role"], entry["model"], 0, entry["returncode"], entry["outfile"])
        for entry in manifest
    ]
    path = ad.synthesize(model=args.model, timeout=args.timeout)
    if path:
        print(path)


def cli_run(args):
    ad = AdvisorDispatch(outdir=args.outdir, auto_subdir=True)
    ad.prepare_brief(
        question=args.question,
        context=args.context,
        context_file=args.context_file,
        extra_context_files=args.extra_context,
        verify_preamble=args.verify,
    )
    print(f"📝 Brief: {ad.brief_path}", file=sys.stderr)

    seats = parse_seats(args.seats)
    results = ad.dispatch(seats=seats, toolsets=args.toolsets, timeout=args.timeout)

    if args.no_synthesis:
        return

    path = ad.synthesize(model=args.synthesis_model, timeout=args.synthesis_timeout)
    if path:
        print("\n" + "=" * 50)
        print("SYNTHESIS")
        print("=" * 50)
        print(ad.read_synthesis())


def parse_seats(seats_str):
    """Parse comma-separated model list into (model, role) tuples.

    Syntax:
      model                  → (model, model)
      model|Role             → (model, Role)
      model1,model2          → [(model1, model1), (model2, model2)]

    Colons in model names (e.g., 'deepseek-v4-pro:cloud') are preserved —
    colon is NOT used for role separation. Use pipe (|) for explicit roles.

    Examples:
      'deepseek-v4-pro:cloud,kimi-k2.7-code:cloud'
      'deepseek-v4-pro:cloud|Reasoner,kimi-k2.7-code:cloud|Coder'
      'qwen3.6:35b-a3b|Local Lens'
    """
    if not seats_str or not seats_str.strip():
        return list(DEFAULT_SEATS)

    seats = []
    for s in seats_str.split(","):
        s = s.strip()
        if not s:
            continue
        if "|" in s:
            # Explicit role via pipe syntax
            parts = s.rsplit("|", 1)
            seats.append((parts[0].strip(), parts[1].strip()))
        else:
            # No pipe — entire string is the model name, role defaults to model
            seats.append((s, s))
    # If all segments were empty/whitespace, fall back to defaults
    if not seats:
        return list(DEFAULT_SEATS)
    return seats


def main():
    parser = argparse.ArgumentParser(
        description="Dispatch advisors with file-referenced context (data channel separation)"
    )
    sub = parser.add_subparsers(dest="command")

    # ── run (all-in-one)
    p_run = sub.add_parser("run", help="Prepare brief → dispatch → synthesize")
    p_run.add_argument("--question", "-q", required=True, help="The question")
    p_run.add_argument("--context", default="", help="Inline context text")
    p_run.add_argument("--context-file", help="Context file path")
    p_run.add_argument("--extra-context", nargs="*", help="Additional context files")
    p_run.add_argument("--outdir", default="/tmp/advisors", help="Output directory")
    p_run.add_argument("--seats", default=None,
                       help="Comma-separated models. Use 'model|Role' for explicit roles. (default: 3-seat panel)")
    p_run.add_argument("--toolsets", default=DEFAULT_TOOLSETS)
    p_run.add_argument("--timeout", type=int, default=300, help="Per-seat timeout")
    p_run.add_argument("--verify", action="store_true",
                       help="Add verify-against-source preamble")
    p_run.add_argument("--no-synthesis", action="store_true")
    p_run.add_argument("--synthesis-model", default=DEFAULT_SYNTHESIS_MODEL)
    p_run.add_argument("--synthesis-timeout", type=int, default=120)
    p_run.set_defaults(func=cli_run)

    # ── prepare
    p_prep = sub.add_parser("prepare", help="Write brief to disk")
    p_prep.add_argument("--question", "-q", required=True)
    p_prep.add_argument("--context", default="")
    p_prep.add_argument("--context-file", help="Context file path")
    p_prep.add_argument("--extra-context", nargs="*")
    p_prep.add_argument("--outdir", default="/tmp/advisors")
    p_prep.add_argument("--verify", action="store_true")
    p_prep.set_defaults(func=cli_prepare)

    # ── dispatch
    p_disp = sub.add_parser("dispatch", help="Dispatch seats with file references")
    p_disp.add_argument("--brief", required=True, help="Path to brief.md")
    p_disp.add_argument("--outdir", default="/tmp/advisors")
    p_disp.add_argument("--seats", default=None,
                        help="Comma-separated models. Use 'model|Role' for explicit roles.")
    p_disp.add_argument("--toolsets", default=DEFAULT_TOOLSETS)
    p_disp.add_argument("--timeout", type=int, default=300)
    p_disp.set_defaults(func=cli_dispatch)

    # ── synthesize
    p_syn = sub.add_parser("synthesize", help="Dispatch GLM synthesis from seat files")
    p_syn.add_argument("--brief", required=True, help="Path to brief.md")
    p_syn.add_argument("--outdir", default="/tmp/advisors")
    p_syn.add_argument("--model", default=DEFAULT_SYNTHESIS_MODEL)
    p_syn.add_argument("--timeout", type=int, default=120)
    p_syn.set_defaults(func=cli_synthesize)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()