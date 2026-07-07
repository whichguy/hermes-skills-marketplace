"""Test configuration: ensure LLM calls are skipped in all bridge tests.

The rich commit message builder (_build_rich_commit_message) and the git history
consolidator (_git_history_learnings) both guard on env vars to skip real LLM calls.
Without these, tests that exercise _run hang on a real model dispatch.
"""
import os

# Skip the LLM commit message builder — use the template fallback
os.environ.setdefault("DEVLOOP_NO_COMMIT_LLM", "1")
# Skip the LLM git history consolidator — use mechanical extraction
os.environ.setdefault("DEVLOOP_NO_HISTORY_LLM", "1")