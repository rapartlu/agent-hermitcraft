"""
Tests for the lore search source added to tools/search.py.

Covers:
  - search_lore_files() function (unit)
  - run_search() with sources=["lore"] (integration)
  - --sources lore CLI flag
  - hermit and season filters applied to lore results
  - lore results appear when searching with default sources=all
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.search import (
    ALL_SOURCES,
    LORE_DIR,
    _parse_lore_hermits_from_raw,
    _tokenise_query,
    run_search,
    search_lore_files,
    main as search_main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens(query: str) -> list[str]:
    return _tokenise_query(query)


# ---------------------------------------------------------------------------
# ALL_SOURCES includes "lore"
# ---------------------------------------------------------------------------

class TestAllSourcesIncludesLore(unittest.TestCase):
    def test_lore_in_all_sources(self):
        self.assertIn("lore", ALL_SOURCES)

    def test_lore_dir_exists(self):
        self.assertTrue(LORE_DIR.exists(), f"LORE_DIR not found: {LORE_DIR}")

    def test_lore_dir_has_md_files(self):
        md_files = [f for f in LORE_DIR.glob("*.md") if f.name != "README.md"]
        self.assertGreater(len(md_files), 0)


# ---------------------------------------------------------------------------
# _parse_lore_hermits_from_raw
# ---------------------------------------------------------------------------

class TestParseLoreHermitsFromRaw(unittest.TestCase):
    def test_parses_yaml_list(self):
        content = (
            "---\ntitle: Test\nhermits_involved:\n"
            "  - Grian\n  - MumboJumbo\n---\n# Body\n"
        )
        result = _parse_lore_hermits_from_raw(content)
        self.assertIn("Grian", result)
        self.assertIn("MumboJumbo", result)

    def test_stops_at_next_key(self):
        content = (
            "---\nhermits_involved:\n  - Grian\nseason: 7\n---\n"
        )
        result = _parse_lore_hermits_from_raw(content)
        self.assertEqual(result, ["Grian"])

    def test_empty_when_no_block(self):
        content = "---\ntitle: No hermits here\n---\n# Body\n"
        result = _parse_lore_hermits_from_raw(content)
        self.assertEqual(result, [])

    def test_empty_content(self):
        result = _parse_lore_hermits_from_raw("")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# search_lore_files — basic
# ---------------------------------------------------------------------------

class TestSearchLoreFilesBasic(unittest.TestCase):
    def test_returns_list(self):
        results = search_lore_files(_tokens("grian"))
        self.assertIsInstance(results, list)

    def test_result_has_required_keys(self):
        results = search_lore_files(_tokens("mycelium"))
        self.assertGreater(len(results), 0, "Expected at least one mycelium lore result")
        for r in results:
            for key in ("source", "score", "season", "hermits", "id", "title", "snippet", "type"):
                self.assertIn(key, r, f"Missing key '{key}' in result")

    def test_source_is_lore_file(self):
        results = search_lore_files(_tokens("prank"))
        for r in results:
            self.assertEqual(r["source"], "lore_file")

    def test_id_prefixed_with_lore(self):
        results = search_lore_files(_tokens("grian"))
        for r in results:
            self.assertTrue(r["id"].startswith("lore-"), f"Bad id: {r['id']}")

    def test_score_positive(self):
        results = search_lore_files(_tokens("resistance"))
        for r in results:
            self.assertGreater(r["score"], 0)

    def test_no_readme_in_results(self):
        results = search_lore_files(_tokens("hermitcraft"))
        ids = [r["id"] for r in results]
        self.assertNotIn("lore-README", ids)


# ---------------------------------------------------------------------------
# search_lore_files — specific content checks
# ---------------------------------------------------------------------------

class TestSearchLoreFilesContent(unittest.TestCase):
    def test_mycelium_resistance_found(self):
        results = search_lore_files(_tokens("mycelium"))
        ids = [r["id"] for r in results]
        self.assertIn(
            "lore-mycelium-resistance-season7", ids,
            msg="mycelium-resistance-season7.md not returned for query 'mycelium'",
        )

    def test_prank_lore_found(self):
        results = search_lore_files(_tokens("prank"))
        ids = [r["id"] for r in results]
        self.assertIn(
            "lore-pranks-and-prank-wars", ids,
            msg="pranks-and-prank-wars.md not returned for query 'prank'",
        )

    def test_boatem_lore_found(self):
        results = search_lore_files(_tokens("boatem"))
        ids = [r["id"] for r in results]
        self.assertIn(
            "lore-boatem-season8", ids,
            msg="boatem-season8.md not returned for query 'boatem'",
        )

    def test_snippet_non_empty_for_matches(self):
        results = search_lore_files(_tokens("mycelium"))
        self.assertTrue(
            any(r["snippet"] for r in results),
            msg="Expected at least one non-empty snippet",
        )

    def test_hermits_list_populated_for_mycelium(self):
        results = search_lore_files(_tokens("mycelium"))
        mycelium = next(
            (r for r in results if "mycelium" in r["id"]), None
        )
        self.assertIsNotNone(mycelium)
        self.assertGreater(
            len(mycelium["hermits"]), 0,
            msg="Expected hermit list to be populated for mycelium lore",
        )

    def test_mycelium_season_is_7(self):
        results = search_lore_files(_tokens("mycelium"))
        mycelium = next(
            (r for r in results if "mycelium" in r["id"]), None
        )
        self.assertIsNotNone(mycelium)
        self.assertEqual(mycelium["season"], 7)


# ---------------------------------------------------------------------------
# search_lore_files — season filter
# ---------------------------------------------------------------------------

class TestSearchLoreFilesSeasonFilter(unittest.TestCase):
    def test_season_filter_matches_expected(self):
        # season_filter=7 allows files where "season: 7" OR seasons list includes 7.
        # Cross-season files (e.g. pranks-and-prank-wars seasons:[6,7,8,9]) store
        # r["season"] as the *first* season in their list (6), not the filter value.
        # We verify that every returned result legitimately covers season 7.
        results = search_lore_files(_tokens("grian"), season_filter=7)
        for r in results:
            # Either the result's stored season is 7, or it's a cross-season file
            # whose season list includes 7 (we check via the source file).
            season = r["season"]
            path = LORE_DIR / (r["id"][len("lore-"):] + ".md")
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            covers_s7 = (
                season == 7
                or "7" in content[:500]  # frontmatter block mentions 7
            )
            self.assertTrue(
                covers_s7,
                msg=f"{r['id']} with season={season} should cover S7",
            )

    def test_season_filter_excludes_wrong_season(self):
        results_s7 = search_lore_files(_tokens("prank"), season_filter=7)
        results_s1 = search_lore_files(_tokens("prank"), season_filter=1)
        # Season 1 pranks aren't expected; certainly Season 7-specific lore
        # files should not appear for season_filter=1
        s7_ids = {r["id"] for r in results_s7}
        s1_ids = {r["id"] for r in results_s1}
        # mycelium resistance is S7 only — should not appear in S1
        if "lore-mycelium-resistance-season7" in s7_ids:
            self.assertNotIn("lore-mycelium-resistance-season7", s1_ids)

    def test_cross_season_lore_included_when_season_matches(self):
        # pranks-and-prank-wars.md lists seasons: [6, 7, 8, 9]
        results = search_lore_files(_tokens("prank"), season_filter=6)
        ids = [r["id"] for r in results]
        self.assertIn("lore-pranks-and-prank-wars", ids,
                      msg="Cross-season lore file not included for season=6")


# ---------------------------------------------------------------------------
# search_lore_files — hermit filter
# ---------------------------------------------------------------------------

class TestSearchLoreFilesHermitFilter(unittest.TestCase):
    def test_hermit_filter_grian(self):
        # If a result passes the hermit filter, Grian must appear in that lore
        # file — either in the hermits_involved list OR somewhere in the body.
        # (The snippet is a short excerpt, so it may not contain "grian" even
        # when the body does — we check the actual file instead.)
        results = search_lore_files(_tokens("prank war"), hermit_filter="Grian")
        for r in results:
            path = LORE_DIR / (r["id"][len("lore-"):] + ".md")
            content = path.read_text(encoding="utf-8").lower() if path.exists() else ""
            mentions_grian = (
                any("grian" in h.lower() for h in r["hermits"])
                or "grian" in content
            )
            self.assertTrue(mentions_grian,
                            msg=f"Result {r['id']} doesn't mention Grian")

    def test_hermit_filter_returns_empty_for_unknown(self):
        results = search_lore_files(
            _tokens("prank"), hermit_filter="NonExistentHermit99999"
        )
        self.assertEqual(results, [])

    def test_hermit_filter_case_insensitive(self):
        lower = search_lore_files(_tokens("grian"), hermit_filter="grian")
        upper = search_lore_files(_tokens("grian"), hermit_filter="GRIAN")
        self.assertEqual(
            sorted(r["id"] for r in lower),
            sorted(r["id"] for r in upper),
        )


# ---------------------------------------------------------------------------
# search_lore_files — type filter
# ---------------------------------------------------------------------------

class TestSearchLoreFilesTypeFilter(unittest.TestCase):
    def test_type_filter_server_event(self):
        results = search_lore_files(_tokens("grian"), type_filter="server_event")
        for r in results:
            self.assertEqual(r["type"], "server_event")

    def test_type_filter_no_match_returns_empty(self):
        results = search_lore_files(_tokens("grian"), type_filter="nonexistent_type")
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# run_search integration — lore source
# ---------------------------------------------------------------------------

class TestRunSearchLore(unittest.TestCase):
    def test_lore_source_in_run_search(self):
        results = run_search("mycelium", sources=["lore"])
        self.assertGreater(len(results), 0)
        self.assertTrue(all(r["source"] == "lore_file" for r in results))

    def test_default_sources_include_lore(self):
        results = run_search("mycelium")
        lore_results = [r for r in results if r["source"] == "lore_file"]
        self.assertGreater(len(lore_results), 0,
                           msg="Default search should return lore results for 'mycelium'")

    def test_lore_only_excludes_other_sources(self):
        results = run_search("grian", sources=["lore"])
        for r in results:
            self.assertEqual(r["source"], "lore_file")

    def test_prank_query_finds_prank_lore(self):
        results = run_search("prank Grian", sources=["lore"])
        ids = [r["id"] for r in results]
        self.assertIn("lore-pranks-and-prank-wars", ids)

    def test_hermit_filter_with_lore_source(self):
        results = run_search("war", sources=["lore"], hermit_filter="Grian")
        for r in results:
            hermits_lower = [h.lower() for h in r.get("hermits", [])]
            # Check actual file body, not just snippet (snippet is a short window)
            path = LORE_DIR / (r["id"][len("lore-"):] + ".md")
            body = path.read_text(encoding="utf-8").lower() if path.exists() else ""
            self.assertTrue(
                any("grian" in h for h in hermits_lower) or "grian" in body,
                msg=f"Result {r['id']} doesn't involve Grian",
            )


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestSearchLoreCLI(unittest.TestCase):
    def test_sources_lore_flag(self):
        rc = search_main(["--query", "mycelium", "--sources", "lore"])
        self.assertEqual(rc, 0)

    def test_sources_lore_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = search_main(["--query", "mycelium", "--sources", "lore", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["sources"], ["lore"])
        self.assertGreater(data["result_count"], 0)
        for r in data["results"]:
            self.assertEqual(r["source"], "lore_file")

    def test_default_search_includes_lore_results(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = search_main(["--query", "mycelium resistance", "--json"])
        self.assertIn(rc, (0, 1))
        if rc == 0:
            data = json.loads(buf.getvalue())
            sources = {r["source"] for r in data["results"]}
            self.assertIn("lore_file", sources)

    def test_lore_hermit_filter_cli(self):
        rc = search_main([
            "--query", "prank",
            "--sources", "lore",
            "--hermit", "Grian",
        ])
        self.assertIn(rc, (0, 1))

    def test_subprocess_lore_source(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.search",
             "--query", "mycelium", "--sources", "lore"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("mycelium", proc.stdout.lower())

    def test_sources_all_still_works(self):
        rc = search_main(["--query", "grian", "--sources",
                          "events", "hermits", "seasons", "lore"])
        self.assertIn(rc, (0, 1))


if __name__ == "__main__":
    unittest.main()
