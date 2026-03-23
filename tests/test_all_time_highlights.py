"""
Tests for tools/all_time_highlights.py
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.all_time_highlights import (
    _filter_events,
    rank_all_time_highlights,
    build_hall_of_fame,
    build_top_events_output,
    build_hall_of_fame_output,
    format_top_events_text,
    format_hall_of_fame_text,
    main,
)
from tools.all_time_highlights import KNOWN_SEASONS, _TYPE_SCORE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(argv: list[str]) -> tuple[int, str, str]:
    """Run main(argv), capture stdout/stderr, return (rc, out, err)."""
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        try:
            rc = main(argv)
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# _filter_events
# ---------------------------------------------------------------------------

class TestFilterEvents(unittest.TestCase):

    def _ev(self, ev_type: str) -> dict:
        return {"type": ev_type, "title": ev_type}

    def test_no_filter_returns_all(self):
        evs = [self._ev("milestone"), self._ev("lore"), self._ev("build")]
        self.assertEqual(_filter_events(evs, None), evs)

    def test_single_type_filter(self):
        evs = [self._ev("milestone"), self._ev("lore"), self._ev("build")]
        result = _filter_events(evs, ["milestone"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "milestone")

    def test_multi_type_filter(self):
        evs = [self._ev("milestone"), self._ev("lore"), self._ev("build")]
        result = _filter_events(evs, ["milestone", "lore"])
        self.assertEqual(len(result), 2)

    def test_empty_types_returns_all(self):
        evs = [self._ev("milestone"), self._ev("build")]
        self.assertEqual(_filter_events(evs, []), evs)

    def test_nonmatching_filter_returns_empty(self):
        evs = [self._ev("milestone"), self._ev("lore")]
        result = _filter_events(evs, ["meta"])
        self.assertEqual(result, [])

    def test_unknown_type_in_data_not_in_filter_excluded(self):
        evs = [self._ev("milestone"), self._ev("unknown_future_type")]
        result = _filter_events(evs, ["milestone"])
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# rank_all_time_highlights
# ---------------------------------------------------------------------------

class TestRankAllTimeHighlights(unittest.TestCase):

    def test_returns_list(self):
        result = rank_all_time_highlights(top_n=5)
        self.assertIsInstance(result, list)

    def test_has_results(self):
        result = rank_all_time_highlights(top_n=5)
        self.assertGreater(len(result), 0)

    def test_top_n_limits_results(self):
        result = rank_all_time_highlights(top_n=3)
        self.assertLessEqual(len(result), 3)

    def test_top_n_1_returns_one(self):
        result = rank_all_time_highlights(top_n=1)
        self.assertEqual(len(result), 1)

    def test_required_keys_present(self):
        required = {"rank", "season", "title", "description", "date",
                    "type", "hermits", "significance_score"}
        result = rank_all_time_highlights(top_n=5)
        for entry in result:
            self.assertTrue(required.issubset(entry.keys()), entry)

    def test_sorted_descending_by_score(self):
        result = rank_all_time_highlights(top_n=20)
        scores = [e["significance_score"] for e in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranks_sequential_from_1(self):
        result = rank_all_time_highlights(top_n=10)
        for i, entry in enumerate(result, start=1):
            self.assertEqual(entry["rank"], i)

    def test_season_field_is_int_or_none(self):
        result = rank_all_time_highlights(top_n=10)
        for entry in result:
            self.assertIn(type(entry["season"]), (int, type(None)))

    def test_hermits_is_list(self):
        result = rank_all_time_highlights(top_n=5)
        for entry in result:
            self.assertIsInstance(entry["hermits"], list)

    def test_types_filter_applied(self):
        result = rank_all_time_highlights(top_n=20, types=["milestone"])
        for entry in result:
            self.assertEqual(entry["type"], "milestone")

    def test_multi_type_filter(self):
        result = rank_all_time_highlights(top_n=30, types=["milestone", "lore"])
        for entry in result:
            self.assertIn(entry["type"], {"milestone", "lore"})

    def test_results_span_multiple_seasons(self):
        result = rank_all_time_highlights(top_n=30)
        seasons = {e["season"] for e in result}
        self.assertGreater(len(seasons), 1)

    def test_top_result_score_is_high(self):
        result = rank_all_time_highlights(top_n=1)
        self.assertGreaterEqual(result[0]["significance_score"], 10)

    def test_significance_score_max_14(self):
        result = rank_all_time_highlights(top_n=50)
        for entry in result:
            self.assertLessEqual(entry["significance_score"], 14)


# ---------------------------------------------------------------------------
# build_hall_of_fame
# ---------------------------------------------------------------------------

class TestBuildHallOfFame(unittest.TestCase):

    def test_returns_list(self):
        result = build_hall_of_fame()
        self.assertIsInstance(result, list)

    def test_has_results(self):
        result = build_hall_of_fame()
        self.assertGreater(len(result), 0)

    def test_at_most_one_entry_per_season(self):
        result = build_hall_of_fame()
        seasons = [e["season"] for e in result]
        self.assertEqual(len(seasons), len(set(seasons)))

    def test_seasons_only_from_known_seasons(self):
        result = build_hall_of_fame()
        for entry in result:
            self.assertIn(entry["season"], KNOWN_SEASONS)

    def test_sorted_chronologically_by_season(self):
        result = build_hall_of_fame()
        seasons = [e["season"] for e in result]
        self.assertEqual(seasons, sorted(seasons))

    def test_required_keys_present(self):
        required = {"season", "title", "description", "date", "type",
                    "hermits", "significance_score"}
        result = build_hall_of_fame()
        for entry in result:
            self.assertTrue(required.issubset(entry.keys()), entry)

    def test_no_rank_key(self):
        # Hall of Fame entries don't have a rank (they're organised by season)
        result = build_hall_of_fame()
        for entry in result:
            self.assertNotIn("rank", entry)

    def test_type_filter_applied(self):
        result = build_hall_of_fame(types=["milestone"])
        for entry in result:
            self.assertEqual(entry["type"], "milestone")

    def test_entry_has_highest_score_for_season(self):
        """For each season, the HoF entry should have the max score in that season."""
        from tools.all_time_highlights import (
            _load_all_events,
            significance_score,
        )

        hof = build_hall_of_fame()
        all_events = _load_all_events()
        for entry in hof:
            season = entry["season"]
            season_events = [ev for ev in all_events if ev.get("season") == season]
            max_score = max(significance_score(ev) for ev in season_events)
            self.assertEqual(entry["significance_score"], max_score,
                             f"Season {season} HoF entry should have max score")

    def test_empty_type_filter_no_crash(self):
        result = build_hall_of_fame(types=["meta"])
        self.assertIsInstance(result, list)


# ---------------------------------------------------------------------------
# build_top_events_output
# ---------------------------------------------------------------------------

class TestBuildTopEventsOutput(unittest.TestCase):

    def _sample(self) -> list[dict]:
        return rank_all_time_highlights(top_n=5)

    def test_mode_key(self):
        out = build_top_events_output(self._sample(), 5, None)
        self.assertEqual(out["mode"], "top_events")

    def test_top_n_requested(self):
        out = build_top_events_output(self._sample(), 7, None)
        self.assertEqual(out["top_n_requested"], 7)

    def test_result_count_matches_events(self):
        sample = self._sample()
        out = build_top_events_output(sample, 5, None)
        self.assertEqual(out["result_count"], len(sample))

    def test_events_key_is_list(self):
        out = build_top_events_output(self._sample(), 5, None)
        self.assertIsInstance(out["events"], list)

    def test_type_filter_included_when_set(self):
        out = build_top_events_output(self._sample(), 5, ["milestone"])
        self.assertEqual(out["type_filter"], ["milestone"])

    def test_type_filter_absent_when_none(self):
        out = build_top_events_output(self._sample(), 5, None)
        self.assertNotIn("type_filter", out)

    def test_json_serialisable(self):
        out = build_top_events_output(self._sample(), 5, None)
        serialised = json.dumps(out)
        self.assertIsInstance(serialised, str)


# ---------------------------------------------------------------------------
# build_hall_of_fame_output
# ---------------------------------------------------------------------------

class TestBuildHallOfFameOutput(unittest.TestCase):

    def test_mode_key(self):
        out = build_hall_of_fame_output(build_hall_of_fame(), None)
        self.assertEqual(out["mode"], "hall_of_fame")

    def test_season_count(self):
        entries = build_hall_of_fame()
        out = build_hall_of_fame_output(entries, None)
        self.assertEqual(out["season_count"], len(entries))

    def test_entries_key_is_list(self):
        out = build_hall_of_fame_output(build_hall_of_fame(), None)
        self.assertIsInstance(out["entries"], list)

    def test_type_filter_included_when_set(self):
        entries = build_hall_of_fame(types=["lore"])
        out = build_hall_of_fame_output(entries, ["lore"])
        self.assertEqual(out["type_filter"], ["lore"])

    def test_type_filter_absent_when_none(self):
        out = build_hall_of_fame_output(build_hall_of_fame(), None)
        self.assertNotIn("type_filter", out)

    def test_json_serialisable(self):
        out = build_hall_of_fame_output(build_hall_of_fame(), None)
        serialised = json.dumps(out)
        self.assertIsInstance(serialised, str)


# ---------------------------------------------------------------------------
# format_top_events_text
# ---------------------------------------------------------------------------

class TestFormatTopEventsText(unittest.TestCase):

    def _sample(self) -> list[dict]:
        return rank_all_time_highlights(top_n=5)

    def test_returns_string(self):
        result = format_top_events_text(self._sample(), 5, None)
        self.assertIsInstance(result, str)

    def test_header_contains_all_time(self):
        result = format_top_events_text(self._sample(), 5, None)
        self.assertIn("All-Time", result)

    def test_top_n_in_header(self):
        result = format_top_events_text(self._sample(), 7, None)
        self.assertIn("7", result)

    def test_rank_numbers_shown(self):
        result = format_top_events_text(self._sample(), 5, None)
        self.assertIn(" 1.", result)

    def test_season_label_shown(self):
        result = format_top_events_text(self._sample(), 5, None)
        self.assertRegex(result, r"S\d+")

    def test_score_shown(self):
        result = format_top_events_text(self._sample(), 5, None)
        self.assertIn("score:", result)

    def test_type_filter_in_header_when_set(self):
        sample = rank_all_time_highlights(top_n=5, types=["milestone"])
        result = format_top_events_text(sample, 5, ["milestone"])
        self.assertIn("milestone", result)

    def test_empty_highlights_no_crash(self):
        result = format_top_events_text([], 10, None)
        self.assertIn("No events found", result)


# ---------------------------------------------------------------------------
# format_hall_of_fame_text
# ---------------------------------------------------------------------------

class TestFormatHallOfFameText(unittest.TestCase):

    def test_returns_string(self):
        result = format_hall_of_fame_text(build_hall_of_fame(), None)
        self.assertIsInstance(result, str)

    def test_header_contains_hall_of_fame(self):
        result = format_hall_of_fame_text(build_hall_of_fame(), None)
        self.assertIn("Hall of Fame", result)

    def test_season_labels_shown(self):
        result = format_hall_of_fame_text(build_hall_of_fame(), None)
        self.assertRegex(result, r"S\s*\d+")

    def test_score_shown(self):
        result = format_hall_of_fame_text(build_hall_of_fame(), None)
        self.assertIn("score:", result)

    def test_type_filter_in_header_when_set(self):
        entries = build_hall_of_fame(types=["milestone"])
        result = format_hall_of_fame_text(entries, ["milestone"])
        self.assertIn("milestone", result)

    def test_empty_entries_no_crash(self):
        result = format_hall_of_fame_text([], None)
        self.assertIn("No events found", result)


# ---------------------------------------------------------------------------
# CLI — --top-events mode
# ---------------------------------------------------------------------------

class TestCLITopEvents(unittest.TestCase):

    def test_exits_0(self):
        rc, _, _ = _run(["--top-events"])
        self.assertEqual(rc, 0)

    def test_json_exits_0(self):
        rc, _, _ = _run(["--top-events", "--json"])
        self.assertEqual(rc, 0)

    def test_json_is_valid(self):
        _, out, _ = _run(["--top-events", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_json_mode_field(self):
        _, out, _ = _run(["--top-events", "--json"])
        data = json.loads(out)
        self.assertEqual(data["mode"], "top_events")

    def test_json_events_nonempty(self):
        _, out, _ = _run(["--top-events", "--json"])
        data = json.loads(out)
        self.assertGreater(len(data["events"]), 0)

    def test_top_flag_limits_results(self):
        _, out, _ = _run(["--top-events", "--json", "--top", "3"])
        data = json.loads(out)
        self.assertLessEqual(len(data["events"]), 3)

    def test_top_flag_reflected_in_json(self):
        _, out, _ = _run(["--top-events", "--json", "--top", "7"])
        data = json.loads(out)
        self.assertEqual(data["top_n_requested"], 7)

    def test_sorted_by_score_desc(self):
        _, out, _ = _run(["--top-events", "--json", "--top", "20"])
        data = json.loads(out)
        scores = [e["significance_score"] for e in data["events"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_types_filter_in_json(self):
        _, out, _ = _run(["--top-events", "--json", "--types", "milestone"])
        data = json.loads(out)
        self.assertIn("type_filter", data)
        for ev in data["events"]:
            self.assertEqual(ev["type"], "milestone")

    def test_types_filter_absent_when_not_given(self):
        _, out, _ = _run(["--top-events", "--json"])
        data = json.loads(out)
        self.assertNotIn("type_filter", data)

    def test_season_field_present_in_events(self):
        _, out, _ = _run(["--top-events", "--json", "--top", "5"])
        data = json.loads(out)
        for ev in data["events"]:
            self.assertIn("season", ev)

    def test_text_output_contains_alltime(self):
        _, out, _ = _run(["--top-events"])
        self.assertIn("All-Time", out)

    def test_text_output_has_rank_numbers(self):
        _, out, _ = _run(["--top-events", "--top", "5"])
        self.assertIn(" 1.", out)


# ---------------------------------------------------------------------------
# CLI — --hall-of-fame mode
# ---------------------------------------------------------------------------

class TestCLIHallOfFame(unittest.TestCase):

    def test_exits_0(self):
        rc, _, _ = _run(["--hall-of-fame"])
        self.assertEqual(rc, 0)

    def test_json_exits_0(self):
        rc, _, _ = _run(["--hall-of-fame", "--json"])
        self.assertEqual(rc, 0)

    def test_json_is_valid(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_json_mode_field(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        self.assertEqual(data["mode"], "hall_of_fame")

    def test_json_entries_nonempty(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        self.assertGreater(len(data["entries"]), 0)

    def test_one_entry_per_season(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        seasons = [e["season"] for e in data["entries"]]
        self.assertEqual(len(seasons), len(set(seasons)))

    def test_entries_sorted_by_season(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        seasons = [e["season"] for e in data["entries"]]
        self.assertEqual(seasons, sorted(seasons))

    def test_types_filter_in_json(self):
        _, out, _ = _run(["--hall-of-fame", "--json", "--types", "lore"])
        data = json.loads(out)
        self.assertIn("type_filter", data)
        for entry in data["entries"]:
            self.assertEqual(entry["type"], "lore")

    def test_types_filter_absent_when_not_given(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        self.assertNotIn("type_filter", data)

    def test_text_output_contains_hall_of_fame(self):
        _, out, _ = _run(["--hall-of-fame"])
        self.assertIn("Hall of Fame", out)

    def test_text_output_has_season_labels(self):
        _, out, _ = _run(["--hall-of-fame"])
        self.assertRegex(out, r"S\s*\d+")

    def test_no_rank_field_in_entries(self):
        _, out, _ = _run(["--hall-of-fame", "--json"])
        data = json.loads(out)
        for entry in data["entries"]:
            self.assertNotIn("rank", entry)


# ---------------------------------------------------------------------------
# CLI — mutual exclusion / error cases
# ---------------------------------------------------------------------------

class TestCLIErrors(unittest.TestCase):

    def test_no_mode_exits_nonzero(self):
        rc, _, _ = _run([])
        self.assertNotEqual(rc, 0)

    def test_both_modes_exits_nonzero(self):
        rc, _, _ = _run(["--top-events", "--hall-of-fame"])
        self.assertNotEqual(rc, 0)

    def test_invalid_type_exits_nonzero(self):
        rc, _, _ = _run(["--top-events", "--types", "invalid_type_xyz"])
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------

class TestDataIntegrity(unittest.TestCase):

    def test_top_events_covers_multiple_seasons(self):
        result = rank_all_time_highlights(top_n=30)
        seasons = {e["season"] for e in result}
        self.assertGreater(len(seasons), 3)

    def test_hall_of_fame_has_entries_for_well_documented_seasons(self):
        hof = build_hall_of_fame()
        hof_seasons = {e["season"] for e in hof}
        # Seasons 6–9 are the best-documented — all should appear
        for s in range(6, 10):
            self.assertIn(s, hof_seasons, f"Season {s} missing from Hall of Fame")

    def test_all_type_scores_positive(self):
        for t, score in _TYPE_SCORE.items():
            self.assertGreater(score, 0, f"Type '{t}' has non-positive score")


if __name__ == "__main__":
    unittest.main()
