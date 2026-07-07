"""Build the spike sample seed repo at /opt/data/devloop-spike-sample — a small multi-file project
the go/no-go spike's MODIFY tasks act on (CREATE tasks just add new files to it). Idempotent: wipes
+ recreates + git-inits + commits, then makes it world-accessible so the ask subprocess (a different
uid) can read it and the per-task worktrees off it work. Run in-container."""
import os
import shutil
import subprocess

ROOT = "/opt/data/devloop-spike-sample"

FILES = {
    "README.md": "# devloop spike sample\n\nA small multi-file project used by the go/no-go spike.\n",
    "textutil.py": (
        '"""Text utilities."""\n'
        "import re\n\n\n"
        "def normalize(s):\n"
        '    """Lowercase s and strip everything except a-z0-9. Assumes a non-empty string."""\n'
        '    return re.sub(r"[^a-z0-9]", "", s.lower())\n'
    ),
    "app.py": (
        '"""Demo app that builds a key from a label."""\n'
        "from textutil import normalize\n\n\n"
        "def make_key(label):\n"
        '    return "key-" + normalize(label)\n'
    ),
    "email_client.py": (
        '"""Email client with an inline 3-attempt retry loop."""\n'
        "import time\n\n\n"
        "def send_email(to, body, transport):\n"
        "    last = None\n"
        "    for attempt in range(3):\n"
        "        try:\n"
        "            return transport(to, body)\n"
        "        except Exception as e:  # noqa: BLE001\n"
        "            last = e\n"
        "            time.sleep(0.01 * (attempt + 1))\n"
        "    raise last\n"
    ),
    "tests/test_textutil.py": (
        '"""Pre-existing suite: pins normalize\'s NON-EMPTY behavior (orthogonal to the t3 task,\n'
        'which changes empty-input behavior only) — the regression gate must keep this green."""\n'
        "from textutil import normalize\n\n\n"
        "def test_normalize_basic():\n"
        '    assert normalize("Hello, World!") == "helloworld"\n'
    ),
    "tests/test_email_client.py": (
        '"""Pre-existing suite: pins the 3-attempt retry SEMANTICS of send_email. The t8 extraction\n'
        'task must preserve these; a naive extraction (wrong attempts / no re-raise) breaks them —\n'
        'exactly what the regression gate + the spike regression_red check must catch."""\n'
        "import pytest\n\n"
        "from email_client import send_email\n\n\n"
        "def test_succeeds_on_third_attempt():\n"
        "    calls = []\n"
        "    def transport(to, body):\n"
        "        calls.append(1)\n"
        "        if len(calls) < 3:\n"
        '            raise RuntimeError("flaky")\n'
        '        return "sent"\n'
        '    assert send_email("a@b", "hi", transport) == "sent"\n'
        "    assert len(calls) == 3\n\n\n"
        "def test_reraises_after_three_failures():\n"
        "    calls = []\n"
        "    def transport(to, body):\n"
        "        calls.append(1)\n"
        '        raise RuntimeError("down")\n'
        "    with pytest.raises(RuntimeError):\n"
        '        send_email("a@b", "hi", transport)\n'
        "    assert len(calls) == 3\n"
    ),
    "webhook_client.py": (
        '"""Webhook client with an inline 3-attempt retry loop (duplicated from email_client)."""\n'
        "import time\n\n\n"
        "def post_webhook(url, payload, transport):\n"
        "    last = None\n"
        "    for attempt in range(3):\n"
        "        try:\n"
        "            return transport(url, payload)\n"
        "        except Exception as e:  # noqa: BLE001\n"
        "            last = e\n"
        "            time.sleep(0.01 * (attempt + 1))\n"
        "    raise last\n"
    ),
}

shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(ROOT)
for rel, content in FILES.items():
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(content)
for cmd in (["init", "-q"], ["config", "user.email", "spike@devloop"],
            ["config", "user.name", "devloop-spike"], ["add", "."], ["commit", "-qm", "seed"]):
    subprocess.run(["git", "-C", ROOT, *cmd], check=True)
for dp, _dirs, files in os.walk(ROOT):
    os.chmod(dp, 0o777)
    for f in files:
        os.chmod(os.path.join(dp, f), 0o666)
head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print(f"seed repo ready: {ROOT} ({len(FILES)} files, HEAD {head[:8]})")
