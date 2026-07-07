#!/usr/bin/env python3
"""Mock-based contract tests for the arxiv search skill.

Exemplar of the *mock test* pattern for API skills: no network. We stub
urllib.request.urlopen to (a) capture the request URL the script builds for
various inputs (contract), and (b) feed a canned arXiv Atom response so the XML
parser is exercised end-to-end (parse correctness + no crash on real-shaped data).

Stdlib unittest only — runs with bare `python3 -m unittest`, no pytest needed.
"""
import io
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

# import the skill script as a module
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import search_arxiv as S  # noqa: E402


CANNED_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2402.03300v2</id>
    <title>Sample GRPO Paper</title>
    <published>2024-02-05T10:00:00Z</published>
    <updated>2024-02-07T10:00:00Z</updated>
    <summary>A study of GRPO.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <category term="cs.LG"/>
    <category term="cs.AI"/>
  </entry>
</feed>"""


class _FakeResp:
    def __init__(self, data): self._d = data
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _run_search(**kwargs):
    """Run S.search with urlopen mocked; return (captured_url, stdout)."""
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        return _FakeResp(CANNED_ATOM)

    buf = io.StringIO()
    with mock.patch.object(S.urllib.request, "urlopen", fake_urlopen):
        old = sys.stdout
        sys.stdout = buf
        try:
            S.search(**kwargs)
        finally:
            sys.stdout = old
    return captured.get("url", ""), buf.getvalue()


class ArxivUrlContract(unittest.TestCase):

    def test_query_builds_all_field(self):
        url, _ = _run_search(query="GRPO reinforcement learning")
        self.assertIn("export.arxiv.org/api/query", url)
        self.assertIn("search_query=all:", url)
        self.assertIn("sortBy=relevance", url)

    def test_author_and_category_combine_with_AND(self):
        url, _ = _run_search(author="Yann LeCun", category="cs.AI")
        self.assertIn("au:", url)
        self.assertIn("cat:cs.AI", url)
        self.assertIn("+AND+", url)

    def test_id_list_path(self):
        url, _ = _run_search(ids="2402.03300")
        self.assertIn("id_list=2402.03300", url)
        self.assertNotIn("search_query", url)

    def test_sort_date_maps_to_submittedDate(self):
        url, _ = _run_search(query="x", sort="date")
        self.assertIn("sortBy=submittedDate", url)

    def test_max_results_passthrough(self):
        url, _ = _run_search(query="x", max_results=10)
        self.assertIn("max_results=10", url)


class ArxivParse(unittest.TestCase):

    def test_parses_canned_entry_fields(self):
        _, out = _run_search(query="GRPO")
        self.assertIn("Sample GRPO Paper", out)
        self.assertIn("2402.03300", out)            # base id extracted from /abs/...v2
        self.assertIn("Ada Lovelace, Alan Turing", out)   # multiple authors joined
        self.assertIn("cs.LG, cs.AI", out)          # categories joined
        self.assertIn("Found 2 results", out)       # opensearch totalResults

    def test_version_suffix_preserved_in_display(self):
        _, out = _run_search(query="GRPO")
        self.assertIn("2402.03300v2", out)          # version shown next to base id


if __name__ == "__main__":
    unittest.main()
