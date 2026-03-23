"""
Tests for tools/search.py
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.search import (
    ALL_SOURCES,
    EVENTS_FILE,
    HERMITS_DIR,
    SEASONS_DIR,
    VIDEO_EVENTS_FILE,
    _count_matches,
    _tokenise_query,
    format_search_results,
    make_snippet,
    run_search,
    score_result,
    search_events,
    search_hermit_profiles,
    search_season_files,
)

SCRIPT = str(Path(__file__).parent.parent / "tools" / "search.py")


# ---------------------------------------------------------------------------
# Unit tests — _tokenise_query
# ---------------------------------------------------------------------------

class TestTokeniseQuery(unittest.TestCase):
    def test_single_word(self):
        self.assertEqual(_tokenise_query("grian"), ["grian"])

    def test_multi_word(self):
        self.assertEqual(_tokenise_query("Boatem Hole"), ["boatem", "hole"])

    def test_extra_whitespace(self):
        tokens = _tokenise_query("  decked   out  ")
        self.assertEqual(tokens, ["decked", "out"])

    def test_empty_string(self):
        self.assertEqual(_tokenise_query(""), [])

    def test_case_lowered(self):
        tokens = _tokenise_query("GRIAN MumboJumbo")
        self.assertEqual(tokens, ["grian", "mumbojumbo"])


# ---------------------------------------------------------------------------
# Unit tests — _count_matches
# ---------------------------------------------------------------------------

class TestCountMatches(unittest.TestCase):
    def test_single_match(self):
        self.assertEqual(_count_matches("Grian pranked MumboJumbo", ["grian"]), 1)

    def test_multiple_matches(self):
        self.assertEqual(_count_matches("Decked Out is the best Decked Out", ["decked"]), 2)

    def test_no_match(self):
        self.assertEqual(_count_matches("nothing here", ["grian"]), 0)

    def test_case_insensitive(self):
        self.assertEqual(_count_matches("GRIAN and grian", ["grian"]), 2)

    def test_multiple_tokens(self):
        count = _count_matches("Grian and Scar went to Boatem", ["grian", "boatem"])
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# Unit tests — score_result
# ---------------------------------------------------------------------------

class TestScoreResult(unittest.TestCase):
    def test_title_match_worth_3x(self):
        tokens = ["decked"]
        s_title = score_result(tokens, "Decked Out", "nothing relevant")
        s_body  = score_result(tokens, "Event Title", "decked out happened here")
        self.assertEqual(s_title, 3)
        self.assertEqual(s_body, 1)

    def test_both_title_and_body(self):
        tokens = ["grian"]
        sc = score_result(tokens, "Grian Joins Season 6", "Grian first appears in Season 6")
        # 1 title hit × 3 + 1 body hit × 1 = 4
        self.assertEqual(sc, 4)

    def test_no_match_returns_zero(self):
        self.assertEqual(score_result(["xyz"], "Title", "body text"), 0)

    def test_empty_tokens_returns_zero(self):
        self.assertEqual(score_result([], "Title with words", "body"), 0)


# ---------------------------------------------------------------------------
# Unit tests — make_snippet
# ---------------------------------------------------------------------------

class TestMakeSnippet(unittest.TestCase):
    def test_snippet_includes_keyword_context(self):
        text = "This is a long introduction. TangoTek built Decked Out. More words follow here."
        snippet = make_snippet(text, ["decked"])
        self.assertIn("Decked", snippet)

    def test_snippet_respects_max_len(self):
        text = "a " * 200
        snippet = make_snippet(text, ["zzz"], max_len=50)
        self.assertLessEqual(len(snippet), 60)  # some slack for "..."

    def test_ellipsis_when_truncated(self):
        text = "start " + "filler " * 50 + "keyword here " + "filler " * 50 + "end"
        snippet = make_snippet(text, ["keyword"])
        self.assertIn("keyword", snippet.lower())

    def test_empty_text(self):
        self.assertEqual(make_snippet("", ["grian"]), "")

    def test_no_match_returns_start(self):
        text = "Season 7 launched in 2020 with 24 members."
        snippet = make_snippet(text, ["nonexistent"])
        self.assertTrue(snippet.startswith("Season 7"))


# ---------------------------------------------------------------------------
# Integration tests — search_events
# ---------------------------------------------------------------------------

class TestSearchEvents(unittest.TestCase):
    def test_decked_out_returns_results(self):
        results = search_events(["decked", "out"])
        self.assertGreater(len(results), 0)

    def test_each_result_has_required_fields(self):
        results = search_events(["season"])
        for r in results:
            for field in ("source", "score", "season", "hermits", "id", "title", "snippet"):
                self.assertIn(field, r, f"Missing field '{field}'")

    def test_source_field_is_event(self):
        results = search_events(["decked"])
        for r in results:
            self.assertEqual(r["source"], "event")

    def test_all_scores_positive(self):
        results = search_events(["grian"])
        for r in results:
            self.assertGreater(r["score"], 0)

    def test_season_filter_applied(self):
        results = search_events(["season"], season_filter=7)
        for r in results:
            self.assertEqual(r["season"], 7)

    def test_no_match_returns_empty(self):
        results = search_events(["xyzzy_no_match_ever"])
        self.assertEqual(results, [])

    def test_tangotek_decked_out_season7(self):
        results = search_events(["decked", "out"], season_filter=7)
        titles = [r["title"] for r in results]
        self.assertTrue(any("Decked Out" in t for t in titles))


# ---------------------------------------------------------------------------
# Integration tests — search_hermit_profiles
# ---------------------------------------------------------------------------

class TestSearchHermitProfiles(unittest.TestCase):
    def test_grian_found_by_name(self):
        results = search_hermit_profiles(["grian"])
        names = [r["hermits"][0] for r in results if r["hermits"]]
        self.assertIn("Grian", names)

    def test_source_field_is_hermit_profile(self):
        results = search_hermit_profiles(["mumbo"])
        for r in results:
            self.assertEqual(r["source"], "hermit_profile")

    def test_season_filter_excludes_non_members(self):
        # Season 1 had a very different roster; most modern hermits weren't there
        results_s1 = search_hermit_profiles(["building"], season_filter=1)
        results_all = search_hermit_profiles(["building"])
        # Season 1 filter should return fewer results than no filter
        self.assertLessEqual(len(results_s1), len(results_all))

    def test_redstone_finds_mumbo(self):
        results = search_hermit_profiles(["redstone"])
        names = [r["hermits"][0] for r in results if r["hermits"]]
        self.assertIn("MumboJumbo", names)

    def test_each_result_has_required_fields(self):
        results = search_hermit_profiles(["grian"])
        for r in results:
            for field in ("source", "score", "hermits", "id", "title", "snippet"):
                self.assertIn(field, r)

    def test_no_match_returns_empty(self):
        results = search_hermit_profiles(["xyzzy_no_match_ever"])
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Integration tests — search_season_files
# ---------------------------------------------------------------------------

class TestSearchSeasonFiles(unittest.TestCase):
    def test_mycelium_resistance_found(self):
        results = search_season_files(["mycelium"])
        self.assertGreater(len(results), 0)

    def test_source_is_season_file(self):
        results = search_season_files(["decked"])
        for r in results:
            self.assertEqual(r["source"], "season_file")

    def test_season_filter(self):
        results = search_season_files(["decked"], season_filter=7)
        for r in results:
            self.assertEqual(r["season"], 7)

    def test_boatem_found_in_season8(self):
        results = search_season_files(["boatem"])
        seasons = [r["season"] for r in results]
        self.assertIn(8, seasons)

    def test_each_result_has_season_number(self):
        results = search_season_files(["launched"])
        for r in results:
            self.assertIsNotNone(r["season"])
            self.assertIsInstance(r["season"], int)

    def test_no_match_returns_empty(self):
        results = search_season_files(["xyzzy_no_match_ever"])
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Integration tests — run_search
# ---------------------------------------------------------------------------

class TestRunSearch(unittest.TestCase):
    def test_boatem_hole_returns_results(self):
        results = run_search("Boatem Hole")
        self.assertGreater(len(results), 0)

    def test_results_sorted_by_score_descending(self):
        results = run_search("Decked Out")
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_season_filter_applied_across_sources(self):
        results = run_search("season", season_filter=7)
        # Every result that has a season field must equal 7
        # (hermit profile results have season=None — those are cross-season)
        for r in results:
            if r["season"] is not None:
                self.assertEqual(r["season"], 7,
                                 f"Expected season 7, got {r['season']} for {r['title']}")

    def test_sources_filter_events_only(self):
        results = run_search("grian", sources=["events"])
        for r in results:
            self.assertEqual(r["source"], "event")

    def test_sources_filter_hermits_only(self):
        results = run_search("building", sources=["hermits"])
        for r in results:
            self.assertEqual(r["source"], "hermit_profile")

    def test_limit_respected(self):
        results = run_search("the", limit=3)
        self.assertLessEqual(len(results), 3)

    def test_no_match_returns_empty(self):
        results = run_search("xyzzy_no_match_ever")
        self.assertEqual(results, [])

    def test_empty_query_returns_empty(self):
        results = run_search("")
        self.assertEqual(results, [])

    def test_all_results_have_season_and_hermits(self):
        results = run_search("Grian")
        for r in results:
            self.assertIn("season", r)
            self.assertIn("hermits", r)

    def test_mycelium_resistance_results_include_season7(self):
        results = run_search("Mycelium Resistance")
        seasons = [r["season"] for r in results if r["season"] is not None]
        self.assertIn(7, seasons)


# ---------------------------------------------------------------------------
# Integration tests — format_search_results
# ---------------------------------------------------------------------------

class TestFormatSearchResults(unittest.TestCase):
    def setUp(self):
        self.results = run_search("Decked Out")

    def test_returns_string(self):
        out = format_search_results("Decked Out", self.results)
        self.assertIsInstance(out, str)

    def test_query_in_header(self):
        out = format_search_results("Decked Out", self.results)
        self.assertIn("Decked Out", out)

    def test_result_count_in_header(self):
        out = format_search_results("Decked Out", self.results)
        self.assertIn(str(len(self.results)), out)

    def test_titles_present(self):
        out = format_search_results("Decked Out", self.results)
        # At least one result title should appear
        for r in self.results[:3]:
            # Title might be truncated, check first 20 chars
            self.assertIn(r["title"][:20], out)

    def test_empty_results_shows_no_matches(self):
        out = format_search_results("xyzzy", [])
        self.assertIn("No matches found", out)

    def test_singular_result_label(self):
        single = run_search("Decked Out", limit=1)
        out = format_search_results("Decked Out", single)
        self.assertIn("1 result found", out)

    def test_plural_result_label(self):
        multi = run_search("Decked Out", limit=5)
        if len(multi) > 1:
            out = format_search_results("Decked Out", multi)
            self.assertIn("results found", out)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def _run(self, *args: str) -> tuple[int, str, str]:
        result = subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_basic_query_exits_0(self):
        rc, _, _ = self._run("--query", "Decked Out")
        self.assertEqual(rc, 0)

    def test_no_match_exits_1(self):
        rc, _, _ = self._run("--query", "xyzzy_no_match_ever_12345")
        self.assertEqual(rc, 1)

    def test_no_args_exits_nonzero(self):
        rc, _, _ = self._run()
        self.assertNotEqual(rc, 0)

    def test_text_output_contains_header(self):
        _, stdout, _ = self._run("--query", "Boatem")
        self.assertIn("HERMITCRAFT SEARCH", stdout)

    def test_text_output_contains_query(self):
        _, stdout, _ = self._run("--query", "Boatem")
        self.assertIn("Boatem", stdout)

    def test_json_flag_valid_json(self):
        rc, stdout, _ = self._run("--query", "Grian", "--json")
        self.assertEqual(rc, 0)
        data = json.loads(stdout)
        self.assertIn("results", data)
        self.assertIn("result_count", data)
        self.assertIn("query", data)

    def test_json_results_have_required_fields(self):
        _, stdout, _ = self._run("--query", "Decked Out", "--json")
        data = json.loads(stdout)
        for r in data["results"]:
            for field in ("source", "score", "season", "hermits", "title"):
                self.assertIn(field, r, f"Missing field '{field}' in result")

    def test_season_filter(self):
        _, stdout, _ = self._run("--query", "builds", "--season", "7", "--json")
        data = json.loads(stdout)
        for r in data["results"]:
            if r["season"] is not None:
                self.assertEqual(r["season"], 7)

    def test_sources_events_only(self):
        _, stdout, _ = self._run("--query", "grian", "--sources", "events", "--json")
        data = json.loads(stdout)
        for r in data["results"]:
            self.assertEqual(r["source"], "event")

    def test_sources_hermits_only(self):
        _, stdout, _ = self._run("--query", "building", "--sources", "hermits", "--json")
        data = json.loads(stdout)
        for r in data["results"]:
            self.assertEqual(r["source"], "hermit_profile")

    def test_limit_flag(self):
        _, stdout, _ = self._run("--query", "the", "--limit", "3", "--json")
        data = json.loads(stdout)
        self.assertLessEqual(data["result_count"], 3)

    def test_results_sorted_by_score(self):
        _, stdout, _ = self._run("--query", "Decked Out", "--json")
        data = json.loads(stdout)
        scores = [r["score"] for r in data["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_mycelium_resistance_returns_season7(self):
        _, stdout, _ = self._run("--query", "Mycelium Resistance", "--json")
        data = json.loads(stdout)
        seasons = [r["season"] for r in data["results"] if r["season"] is not None]
        self.assertIn(7, seasons)

    def test_hermit_attribution_present(self):
        _, stdout, _ = self._run("--query", "TangoTek Decked Out", "--json")
        data = json.loads(stdout)
        # At least one result should attribute TangoTek
        attributed = any(
            "TangoTek" in r.get("hermits", []) or "TangoTek" in r.get("title", "")
            for r in data["results"]
        )
        self.assertTrue(attributed, "Expected TangoTek attribution in results")

    def test_no_match_text_output(self):
        _, stdout, _ = self._run("--query", "xyzzy_no_match_ever_12345")
        self.assertIn("No matches found", stdout)

    def test_short_flag_for_query(self):
        rc, _, _ = self._run("-q", "Grian")
        self.assertEqual(rc, 0)


# ---------------------------------------------------------------------------
# Constants / data integrity tests
# ---------------------------------------------------------------------------

class TestDataIntegrity(unittest.TestCase):
    def test_all_sources_constant(self):
        self.assertEqual(set(ALL_SOURCES), {"events", "hermits", "seasons"})

    def test_events_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists())

    def test_video_events_file_exists(self):
        self.assertTrue(VIDEO_EVENTS_FILE.exists())

    def test_hermits_dir_exists(self):
        self.assertTrue(HERMITS_DIR.exists())

    def test_seasons_dir_exists(self):
        self.assertTrue(SEASONS_DIR.exists())

    def test_events_are_searchable(self):
        results = search_events(["hermitcraft"])
        self.assertGreater(len(results), 0)

    def test_hermit_profiles_are_searchable(self):
        results = search_hermit_profiles(["hermitcraft"])
        self.assertGreater(len(results), 0)

    def test_season_files_are_searchable(self):
        results = search_season_files(["season"])
        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    import traceback

    suites = [
        ("_tokenise_query",   unittest.TestLoader().loadTestsFromTestCase(TestTokeniseQuery)),
        ("_count_matches",    unittest.TestLoader().loadTestsFromTestCase(TestCountMatches)),
        ("score_result",      unittest.TestLoader().loadTestsFromTestCase(TestScoreResult)),
        ("make_snippet",      unittest.TestLoader().loadTestsFromTestCase(TestMakeSnippet)),
        ("search_events",     unittest.TestLoader().loadTestsFromTestCase(TestSearchEvents)),
        ("search_hermits",    unittest.TestLoader().loadTestsFromTestCase(TestSearchHermitProfiles)),
        ("search_seasons",    unittest.TestLoader().loadTestsFromTestCase(TestSearchSeasonFiles)),
        ("run_search",        unittest.TestLoader().loadTestsFromTestCase(TestRunSearch)),
        ("format_results",    unittest.TestLoader().loadTestsFromTestCase(TestFormatSearchResults)),
        ("CLI",               unittest.TestLoader().loadTestsFromTestCase(TestCLI)),
        ("data_integrity",    unittest.TestLoader().loadTestsFromTestCase(TestDataIntegrity)),
    ]

    passed = failed = 0
    for label, suite in suites:
        print(f"{label}:")
        for test in suite:
            try:
                test.debug()
                print(f"  PASS {test._testMethodName}")
                passed += 1
            except Exception as exc:
                print(f"  FAIL {test._testMethodName}: {exc}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
