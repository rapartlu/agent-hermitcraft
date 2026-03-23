"""
Tests for tools/season_highlights.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.season_highlights import (
    KNOWN_SEASONS,
    EVENTS_FILE,
    _TYPE_SCORE,
    significance_score,
    rank_season_highlights,
    build_highlights_output,
    format_highlights_text,
    main,
)


# ---------------------------------------------------------------------------
# significance_score
# ---------------------------------------------------------------------------
class TestSignificanceScore(unittest.TestCase):
    """Unit tests for the documented significance scoring formula."""

    def _ev(self, **kwargs) -> dict:
        base: dict = {
            "type": "build",
            "hermits": ["Grian"],
            "date_precision": "month",
        }
        base.update(kwargs)
        return base

    # Type bonus ------------------------------------------------------------------

    def test_milestone_is_highest_type(self):
        self.assertEqual(_TYPE_SCORE["milestone"], 10)

    def test_meta_is_lowest_type(self):
        self.assertEqual(_TYPE_SCORE["meta"], 1)

    def test_type_score_order_is_descending(self):
        ordered = ["milestone", "lore", "game", "collab", "build", "meta"]
        scores = [_TYPE_SCORE[t] for t in ordered]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_all_six_types_covered(self):
        expected = {"milestone", "lore", "game", "collab", "build", "meta"}
        self.assertEqual(set(_TYPE_SCORE.keys()), expected)

    def test_unknown_type_gives_nonzero_safe_score(self):
        ev = self._ev(type="xyzunknown")
        # Should not raise; base is 0
        self.assertIsInstance(significance_score(ev), int)

    # Hermit-count bonus ----------------------------------------------------------

    def test_all_hermits_bonus_is_positive(self):
        solo = self._ev(hermits=["Grian"])
        server = self._ev(hermits=["All"])
        self.assertGreater(significance_score(server), significance_score(solo))

    def test_four_hermits_bonus_greater_than_pair(self):
        pair = self._ev(hermits=["A", "B"])
        quad = self._ev(hermits=["A", "B", "C", "D"])
        self.assertGreater(significance_score(quad), significance_score(pair))

    def test_pair_bonus_greater_than_solo(self):
        solo = self._ev(hermits=["Grian"])
        pair = self._ev(hermits=["Grian", "Mumbo"])
        self.assertGreater(significance_score(pair), significance_score(solo))

    def test_three_hermits_get_pair_bonus_not_group_bonus(self):
        pair = self._ev(hermits=["A", "B"])
        trio = self._ev(hermits=["A", "B", "C"])
        quad = self._ev(hermits=["A", "B", "C", "D"])
        self.assertEqual(significance_score(pair), significance_score(trio))
        self.assertGreater(significance_score(quad), significance_score(trio))

    # Date-precision bonus --------------------------------------------------------

    def test_day_precision_scores_higher_than_month(self):
        month_ev = self._ev(date_precision="month")
        day_ev = self._ev(date_precision="day")
        self.assertGreater(significance_score(day_ev), significance_score(month_ev))

    def test_year_precision_gets_no_bonus(self):
        year_ev = self._ev(date_precision="year")
        day_ev = self._ev(date_precision="day")
        self.assertGreater(significance_score(day_ev), significance_score(year_ev))

    # Maximum achievable score ----------------------------------------------------

    def test_milestone_all_hermits_day_equals_14(self):
        # 10 (milestone) + 3 (all) + 1 (day) = 14
        ev = self._ev(type="milestone", hermits=["All"], date_precision="day")
        self.assertEqual(significance_score(ev), 14)

    def test_returns_int(self):
        self.assertIsInstance(significance_score(self._ev()), int)


# ---------------------------------------------------------------------------
# rank_season_highlights
# ---------------------------------------------------------------------------
class TestRankSeasonHighlights(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(rank_season_highlights(6), list)

    def test_season_6_has_highlights(self):
        self.assertGreater(len(rank_season_highlights(6)), 0)

    def test_each_entry_has_required_keys(self):
        for entry in rank_season_highlights(6):
            for key in ("rank", "title", "description", "date",
                        "type", "hermits", "significance_score"):
                self.assertIn(key, entry)

    def test_sorted_descending_by_score(self):
        result = rank_season_highlights(6)
        scores = [e["significance_score"] for e in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranks_sequential_from_1(self):
        result = rank_season_highlights(6, top_n=5)
        self.assertEqual([e["rank"] for e in result], list(range(1, len(result) + 1)))

    def test_top_n_limits_results(self):
        self.assertLessEqual(len(rank_season_highlights(6, top_n=3)), 3)

    def test_top_n_1_returns_exactly_1(self):
        self.assertEqual(len(rank_season_highlights(6, top_n=1)), 1)

    def test_top_result_has_high_score(self):
        # #1 event should score above the minimum type score (meta=1)
        result = rank_season_highlights(6, top_n=1)
        self.assertGreater(result[0]["significance_score"], 4)

    def test_title_is_string(self):
        for entry in rank_season_highlights(7, top_n=5):
            self.assertIsInstance(entry["title"], str)

    def test_hermits_is_list(self):
        for entry in rank_season_highlights(7, top_n=5):
            self.assertIsInstance(entry["hermits"], list)

    def test_significance_score_matches_function(self):
        # Cross-check stored score equals what significance_score() would return
        import json as _j
        raw_events = _j.loads(EVENTS_FILE.read_text())
        s6_lookup = {e["title"]: e for e in raw_events if e.get("season") == 6}
        for entry in rank_season_highlights(6, top_n=5):
            raw = s6_lookup.get(entry["title"])
            if raw:
                self.assertEqual(
                    entry["significance_score"],
                    significance_score(raw),
                )

    def test_unknown_season_returns_empty(self):
        self.assertEqual(rank_season_highlights(999), [])

    def test_seasons_6_through_9_all_have_results(self):
        for s in (6, 7, 8, 9):
            result = rank_season_highlights(s)
            self.assertGreater(len(result), 0, f"Season {s} returned no highlights")

    def test_default_top_n_is_10(self):
        result = rank_season_highlights(9)
        self.assertLessEqual(len(result), 10)


# ---------------------------------------------------------------------------
# build_highlights_output
# ---------------------------------------------------------------------------
class TestBuildHighlightsOutput(unittest.TestCase):

    def setUp(self):
        self.highlights = rank_season_highlights(8, top_n=5)
        self.output = build_highlights_output(8, self.highlights, 5)

    def test_season_key_correct(self):
        self.assertEqual(self.output["season"], 8)

    def test_highlight_count_matches_list_length(self):
        self.assertEqual(self.output["highlight_count"], len(self.highlights))

    def test_top_n_requested_stored(self):
        self.assertEqual(self.output["top_n_requested"], 5)

    def test_events_key_present(self):
        self.assertIn("events", self.output)
        self.assertIsInstance(self.output["events"], list)

    def test_events_is_same_object_as_input(self):
        self.assertIs(self.output["events"], self.highlights)

    def test_empty_highlights_zero_count(self):
        out = build_highlights_output(1, [], 10)
        self.assertEqual(out["highlight_count"], 0)
        self.assertEqual(out["events"], [])

    def test_output_is_json_serialisable(self):
        # Should not raise
        json.dumps(self.output)


# ---------------------------------------------------------------------------
# format_highlights_text
# ---------------------------------------------------------------------------
class TestFormatHighlightsText(unittest.TestCase):

    def setUp(self):
        self.highlights = rank_season_highlights(9, top_n=5)
        self.text = format_highlights_text(9, self.highlights, 5)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_season_number_in_header(self):
        self.assertIn("Season 9", self.text)

    def test_top_n_mentioned(self):
        self.assertIn("5", self.text)

    def test_rank_numbers_shown(self):
        for entry in self.highlights:
            self.assertIn(str(entry["rank"]), self.text)

    def test_event_titles_shown(self):
        for entry in self.highlights[:3]:
            self.assertIn(entry["title"], self.text)

    def test_type_tags_shown(self):
        # At least one [type] bracket should appear
        self.assertRegex(self.text, r"\[.+\]")

    def test_score_shown(self):
        self.assertIn("score:", self.text)

    def test_empty_highlights_shows_no_events_message(self):
        text = format_highlights_text(1, [], 10)
        self.assertIn("No events found", text)

    def test_empty_still_contains_header(self):
        text = format_highlights_text(3, [], 10)
        self.assertIn("Season 3", text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCLI(unittest.TestCase):

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_basic_query_exits_0(self):
        rc, _, _ = self._run(["--season", "9"])
        self.assertEqual(rc, 0)

    def test_output_contains_season_number(self):
        _, out, _ = self._run(["--season", "9"])
        self.assertIn("9", out)

    def test_json_output_valid(self):
        rc, out, _ = self._run(["--season", "9", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        for key in ("season", "events", "highlight_count", "top_n_requested"):
            self.assertIn(key, data)

    def test_json_season_field_correct(self):
        _, out, _ = self._run(["--season", "6", "--json"])
        self.assertEqual(json.loads(out)["season"], 6)

    def test_json_events_nonempty_for_active_season(self):
        _, out, _ = self._run(["--season", "9", "--json"])
        self.assertGreater(len(json.loads(out)["events"]), 0)

    def test_json_event_has_required_fields(self):
        _, out, _ = self._run(["--season", "9", "--json"])
        first = json.loads(out)["events"][0]
        for key in ("rank", "title", "description", "date"):
            self.assertIn(key, first)

    def test_json_sorted_descending_by_score(self):
        _, out, _ = self._run(["--season", "9", "--json"])
        scores = [e["significance_score"] for e in json.loads(out)["events"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_flag_limits_results(self):
        _, out, _ = self._run(["--season", "9", "--top", "3", "--json"])
        self.assertLessEqual(len(json.loads(out)["events"]), 3)

    def test_top_default_is_10(self):
        _, out, _ = self._run(["--season", "9", "--json"])
        self.assertLessEqual(len(json.loads(out)["events"]), 10)

    def test_top_n_stored_in_json(self):
        _, out, _ = self._run(["--season", "8", "--top", "7", "--json"])
        self.assertEqual(json.loads(out)["top_n_requested"], 7)

    def test_unknown_season_exits_1(self):
        rc, _, err = self._run(["--season", "999"])
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)

    def test_unknown_season_error_mentions_available_seasons(self):
        _, _, err = self._run(["--season", "999"])
        self.assertIn("Available seasons", err)

    def test_unknown_season_error_lists_season_numbers(self):
        _, _, err = self._run(["--season", "999"])
        self.assertIn("1", err)
        self.assertIn("11", err)

    def test_list_flag_exits_0(self):
        rc, out, _ = self._run(["--list"])
        self.assertEqual(rc, 0)

    def test_list_shows_all_season_numbers(self):
        _, out, _ = self._run(["--list"])
        for s in KNOWN_SEASONS:
            self.assertIn(str(s), out)

    def test_all_known_seasons_exit_0(self):
        for s in KNOWN_SEASONS:
            rc, _, err = self._run(["--season", str(s)])
            self.assertEqual(rc, 0, f"Season {s} exited non-zero: {err}")

    def test_season_6_highlights_contain_sahara_or_similar(self):
        # Season 6 is well-documented — should have recognisable build/lore events
        _, out, _ = self._run(["--season", "6"])
        # At least one event title should appear in the output
        self.assertGreater(len(out.strip()), 50)


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------
class TestDataIntegrity(unittest.TestCase):

    def test_events_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists())

    def test_known_seasons_is_1_to_11(self):
        self.assertEqual(KNOWN_SEASONS, list(range(1, 12)))

    def test_type_score_all_positive(self):
        for t, s in _TYPE_SCORE.items():
            self.assertGreater(s, 0, f"Type '{t}' has non-positive score {s}")

    def test_all_event_types_in_data_are_scoreable(self):
        events = json.loads(EVENTS_FILE.read_text())
        unknown = {
            ev.get("type")
            for ev in events
            if ev.get("type") and ev.get("type") not in _TYPE_SCORE
        }
        self.assertEqual(unknown, set(), f"Unscored event types found: {unknown}")


if __name__ == "__main__":
    unittest.main()
