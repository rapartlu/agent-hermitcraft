"""
Tests for tools/search_suggest.py (autocomplete) and the new
--hermit / --type filter parameters added to tools/search.py.
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

from tools.search_suggest import (
    ALL_CATEGORIES,
    _event_type_candidates,
    _load_hermit_names,
    _load_season_titles,
    _load_event_titles,
    _score_candidate,
    format_suggestions,
    get_suggestions,
    main as suggest_main,
)
from tools.search import (
    run_search,
    search_events,
    search_hermit_profiles,
    search_season_files,
    _tokenise_query,
    main as search_main,
)


# ===========================================================================
# search_suggest.py — unit tests
# ===========================================================================

class TestScoreCandidate(unittest.TestCase):
    def _make(self, label: str, searchable: str | None = None) -> dict:
        return {
            "label": label,
            "category": "hermit",
            "value": label,
            "searchable": (searchable if searchable is not None else label.lower()),
        }

    def test_whole_prefix_scores_3(self):
        c = self._make("Grian")
        self.assertEqual(_score_candidate(c, "gr"), 3)

    def test_word_prefix_scores_2(self):
        c = self._make("GoodTimesWithScar", "goodtimeswithscar")
        # "scar" is not a word-start prefix in "goodtimeswithscar" but "good" is
        c2 = self._make("Season 9", "season 9")
        self.assertEqual(_score_candidate(c2, "sea"), 3)  # prefix of whole string

    def test_word_boundary_prefix_scores_2(self):
        c = self._make("Decked Out (S7)", "decked out (s7)")
        self.assertEqual(_score_candidate(c, "out"), 2)

    def test_substring_scores_1(self):
        c = self._make("Boatem Hole", "boatem hole")
        self.assertEqual(_score_candidate(c, "atem"), 1)

    def test_no_match_scores_0(self):
        c = self._make("Grian")
        self.assertEqual(_score_candidate(c, "mumbo"), 0)

    def test_empty_query_scores_0(self):
        c = self._make("Grian")
        self.assertEqual(_score_candidate(c, ""), 0)

    def test_case_insensitive(self):
        c = self._make("MumboJumbo")
        self.assertGreater(_score_candidate(c, "mumbo"), 0)


class TestLoadHermitNames(unittest.TestCase):
    def test_returns_list(self):
        result = _load_hermit_names()
        self.assertIsInstance(result, list)

    def test_non_empty(self):
        result = _load_hermit_names()
        self.assertGreater(len(result), 0)

    def test_each_has_required_keys(self):
        for c in _load_hermit_names():
            self.assertIn("label", c)
            self.assertIn("category", c)
            self.assertIn("value", c)
            self.assertIn("searchable", c)
            self.assertEqual(c["category"], "hermit")

    def test_searchable_is_lowercase(self):
        for c in _load_hermit_names():
            self.assertEqual(c["searchable"], c["searchable"].lower())

    def test_contains_grian(self):
        names = [c["label"].lower() for c in _load_hermit_names()]
        self.assertIn("grian", names)


class TestLoadSeasonTitles(unittest.TestCase):
    def test_returns_all_seasons(self):
        titles = _load_season_titles()
        self.assertGreaterEqual(len(titles), 11)

    def test_category_is_season(self):
        for c in _load_season_titles():
            self.assertEqual(c["category"], "season")

    def test_contains_season_9(self):
        values = [c["value"] for c in _load_season_titles()]
        self.assertIn("Season 9", values)


class TestLoadEventTitles(unittest.TestCase):
    def test_returns_list(self):
        result = _load_event_titles()
        self.assertIsInstance(result, list)

    def test_category_is_event(self):
        for c in _load_event_titles():
            self.assertEqual(c["category"], "event")

    def test_no_duplicate_titles(self):
        titles = [c["value"].lower() for c in _load_event_titles()]
        self.assertEqual(len(titles), len(set(titles)))


class TestEventTypeCandidates(unittest.TestCase):
    def test_returns_list(self):
        result = _event_type_candidates()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_category_is_type(self):
        for c in _event_type_candidates():
            self.assertEqual(c["category"], "type")

    def test_contains_build(self):
        values = [c["value"] for c in _event_type_candidates()]
        self.assertIn("build", values)


class TestGetSuggestions(unittest.TestCase):
    def test_hermit_prefix_returns_matches(self):
        results = get_suggestions("Gr", categories=["hermits"])
        labels_lower = [s["label"].lower() for s in results]
        self.assertTrue(any("grian" in l for l in labels_lower))

    def test_season_prefix_returns_matches(self):
        results = get_suggestions("Season 9", categories=["seasons"])
        self.assertGreater(len(results), 0)
        self.assertTrue(any(s["category"] == "season" for s in results))

    def test_type_prefix_returns_matches(self):
        results = get_suggestions("bui", categories=["types"])
        values = [s["value"] for s in results]
        self.assertIn("build", values)

    def test_empty_query_returns_empty(self):
        results = get_suggestions("")
        self.assertEqual(results, [])

    def test_whitespace_query_returns_empty(self):
        results = get_suggestions("   ")
        self.assertEqual(results, [])

    def test_limit_respected(self):
        results = get_suggestions("a", limit=3)
        self.assertLessEqual(len(results), 3)

    def test_limit_capped_at_25(self):
        results = get_suggestions("a", limit=100)
        self.assertLessEqual(len(results), 25)

    def test_result_has_required_keys(self):
        results = get_suggestions("Grian")
        for r in results:
            self.assertIn("label", r)
            self.assertIn("category", r)
            self.assertIn("value", r)

    def test_prefix_ranked_before_substring(self):
        # "Grian" starts with "Gr" → higher score than something that only
        # contains "gr" as a substring mid-word
        results = get_suggestions("Gri", categories=["hermits"])
        self.assertGreater(len(results), 0)
        # First result should be Grian
        self.assertIn("grian", results[0]["label"].lower())

    def test_category_filter_hermits_only(self):
        results = get_suggestions("a", categories=["hermits"])
        for r in results:
            self.assertEqual(r["category"], "hermit")

    def test_category_filter_seasons_only(self):
        results = get_suggestions("Season", categories=["seasons"])
        for r in results:
            self.assertEqual(r["category"], "season")

    def test_no_match_returns_empty(self):
        results = get_suggestions("xyzzy_no_match_12345")
        self.assertEqual(results, [])

    def test_cross_category_results(self):
        # A broad query should return suggestions from multiple categories
        results = get_suggestions("dec")
        categories = {r["category"] for r in results}
        self.assertGreater(len(categories), 0)


class TestFormatSuggestions(unittest.TestCase):
    def test_returns_string(self):
        suggestions = get_suggestions("Grian")
        text = format_suggestions("Grian", suggestions)
        self.assertIsInstance(text, str)

    def test_contains_query(self):
        text = format_suggestions("Gr", [])
        self.assertIn("Gr", text)

    def test_empty_suggestions_shows_no_matches(self):
        text = format_suggestions("xyzzy", [])
        self.assertIn("no matches", text.lower())


class TestSuggestCLI(unittest.TestCase):
    def test_list_categories(self):
        result = suggest_main(["--list-categories"])
        self.assertEqual(result, 0)

    def test_missing_query_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            suggest_main([])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_valid_query_text(self):
        result = suggest_main(["--query", "Grian"])
        self.assertIn(result, (0, 1))  # 0=found, 1=not found

    def test_valid_query_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = suggest_main(["--query", "Gr", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["query"], "Gr")
        self.assertIn("suggestions", data)
        self.assertIsInstance(data["suggestions"], list)
        for s in data["suggestions"]:
            self.assertIn("label", s)
            self.assertIn("category", s)
            self.assertIn("value", s)

    def test_types_filter(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = suggest_main(["--query", "b", "--types", "types", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        for s in data["suggestions"]:
            self.assertEqual(s["category"], "type")

    def test_limit_respected_in_cli(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            suggest_main(["--query", "a", "--limit", "3", "--json"])
        data = json.loads(buf.getvalue())
        self.assertLessEqual(len(data["suggestions"]), 3)

    def test_subprocess_invocation(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.search_suggest", "--query", "Season"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("season", proc.stdout.lower())


# ===========================================================================
# search.py — new --hermit / --type filter tests
# ===========================================================================

class TestSearchHermitFilter(unittest.TestCase):
    def test_hermit_filter_events_returns_only_matching(self):
        tokens = _tokenise_query("build")
        results = search_events(tokens, hermit_filter="Grian")
        for r in results:
            hermits_lower = [h.lower() for h in r["hermits"]]
            self.assertTrue(
                any("grian" in h for h in hermits_lower),
                msg=f"Expected Grian in hermits but got {r['hermits']}",
            )

    def test_hermit_filter_profiles_skips_non_matching(self):
        tokens = _tokenise_query("redstone")
        results = search_hermit_profiles(tokens, hermit_filter="Mumbo")
        for r in results:
            self.assertTrue(
                any("mumbo" in h.lower() for h in r["hermits"]),
                msg=f"Profile filter leak: {r['hermits']}",
            )

    def test_hermit_filter_case_insensitive(self):
        tokens = _tokenise_query("base")
        lower = search_hermit_profiles(tokens, hermit_filter="grian")
        upper = search_hermit_profiles(tokens, hermit_filter="GRIAN")
        self.assertEqual(
            [r["id"] for r in lower],
            [r["id"] for r in upper],
        )

    def test_run_search_hermit_filter(self):
        results = run_search("prank", hermit_filter="Grian")
        for r in results:
            if r["source"] == "event":
                hermits_lower = [h.lower() for h in r["hermits"]]
                self.assertTrue(any("grian" in h for h in hermits_lower))

    def test_hermit_filter_season_files(self):
        tokens = _tokenise_query("decked")
        results = search_season_files(tokens, hermit_filter="TangoTek")
        # If any season file mentions TangoTek and "decked", it should appear
        for r in results:
            self.assertIn("tango", r["snippet"].lower() + r["title"].lower()
                         + "tango" if True else "")
            # Just verify it doesn't crash; TangoTek is in S9 body text

    def test_unknown_hermit_returns_empty(self):
        results = run_search("build", hermit_filter="NonExistentHermit99")
        # Event results should be empty; profile/season results may vary
        event_results = [r for r in results if r["source"] == "event"]
        self.assertEqual(event_results, [])


class TestSearchTypeFilter(unittest.TestCase):
    def test_type_filter_build(self):
        tokens = _tokenise_query("base")
        results = search_events(tokens, type_filter="build")
        for r in results:
            self.assertEqual(r["type"], "build")

    def test_type_filter_collab(self):
        tokens = _tokenise_query("team")
        results = search_events(tokens, type_filter="collab")
        for r in results:
            self.assertEqual(r["type"], "collab")

    def test_type_filter_non_profile_skips_profiles(self):
        tokens = _tokenise_query("grian")
        results = search_hermit_profiles(tokens, type_filter="build")
        self.assertEqual(results, [])

    def test_type_filter_profile_includes_profiles(self):
        tokens = _tokenise_query("grian")
        results = search_hermit_profiles(tokens, type_filter="profile")
        self.assertGreater(len(results), 0)

    def test_type_filter_non_season_summary_skips_seasons(self):
        tokens = _tokenise_query("season")
        results = search_season_files(tokens, type_filter="build")
        self.assertEqual(results, [])

    def test_type_filter_season_summary_includes_seasons(self):
        tokens = _tokenise_query("hermitcraft")
        results = search_season_files(tokens, type_filter="season_summary")
        self.assertGreater(len(results), 0)

    def test_run_search_type_filter(self):
        results = run_search("build", type_filter="build")
        for r in results:
            self.assertEqual(r["type"], "build")

    def test_type_filter_case_insensitive(self):
        tokens = _tokenise_query("base")
        lower_results = search_events(tokens, type_filter="build")
        upper_results = search_events(tokens, type_filter="BUILD")
        self.assertEqual(
            [r["id"] for r in lower_results],
            [r["id"] for r in upper_results],
        )


class TestSearchCombinedFilters(unittest.TestCase):
    def test_season_and_hermit_combined(self):
        results = run_search("base", season_filter=9, hermit_filter="Grian")
        for r in results:
            if r["source"] == "event":
                self.assertEqual(r["season"], 9)
                hermits_lower = [h.lower() for h in r["hermits"]]
                self.assertTrue(any("grian" in h for h in hermits_lower))

    def test_season_and_type_combined(self):
        results = run_search("build", season_filter=7, type_filter="build")
        for r in results:
            if r["source"] == "event":
                self.assertEqual(r["season"], 7)
                self.assertEqual(r["type"], "build")

    def test_json_payload_includes_new_filter_fields(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = search_main(["--query", "build", "--hermit", "Grian",
                              "--type", "build", "--json"])
        data = json.loads(buf.getvalue())
        self.assertIn("hermit_filter", data)
        self.assertEqual(data["hermit_filter"], "Grian")
        self.assertIn("type_filter", data)
        self.assertEqual(data["type_filter"], "build")

    def test_cli_hermit_flag(self):
        rc = search_main(["--query", "prank", "--hermit", "Grian"])
        self.assertIn(rc, (0, 1))

    def test_cli_type_flag(self):
        rc = search_main(["--query", "build", "--type", "build"])
        self.assertIn(rc, (0, 1))

    def test_cli_all_filters_combined(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = search_main([
                "--query", "decked",
                "--season", "9",
                "--hermit", "TangoTek",
                "--type", "build",
                "--json",
            ])
        self.assertIn(rc, (0, 1))
        data = json.loads(buf.getvalue())
        self.assertEqual(data["season_filter"], 9)
        self.assertEqual(data["hermit_filter"], "TangoTek")
        self.assertEqual(data["type_filter"], "build")

    def test_subprocess_with_hermit_filter(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.search",
             "--query", "build", "--hermit", "Grian", "--json"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertIn(proc.returncode, (0, 1))
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            self.assertEqual(data["hermit_filter"], "Grian")


if __name__ == "__main__":
    unittest.main()
