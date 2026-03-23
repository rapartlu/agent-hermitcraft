#!/usr/bin/env python3
"""Tests for tools/timeline.py"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import timeline  # noqa: E402

EVENTS_FILE = Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cli(*args: str) -> tuple[str, int]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = timeline.main(list(args))
    return buf.getvalue(), code


def load() -> list[dict]:
    with EVENTS_FILE.open() as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Events file validation
# ---------------------------------------------------------------------------

class TestEventsFile(unittest.TestCase):

    def test_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists(), "events.json not found")

    def test_valid_json_array(self):
        data = load()
        self.assertIsInstance(data, list)

    def test_at_least_30_events(self):
        data = load()
        self.assertGreaterEqual(len(data), 30)

    def test_seasons_6_through_10_present(self):
        data = load()
        present = {e["season"] for e in data}
        for s in range(6, 11):
            self.assertIn(s, present, f"Season {s} not represented")

    def test_at_least_5_events_per_covered_season(self):
        data = load()
        for s in range(6, 11):
            count = sum(1 for e in data if e.get("season") == s)
            self.assertGreaterEqual(count, 5, f"Season {s} has fewer than 5 events")

    def test_all_events_pass_schema(self):
        data = load()
        errors = []
        for e in data:
            for err in timeline.validate_event(e):
                errors.append(f"{e.get('id', '?')}: {err}")
        self.assertEqual(errors, [], "Schema errors:\n" + "\n".join(errors))

    def test_unique_ids(self):
        data = load()
        ids = [e["id"] for e in data]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate event IDs found")

    def test_all_types_valid(self):
        data = load()
        for e in data:
            self.assertIn(
                e["type"], timeline.VALID_TYPES,
                f"{e['id']}: invalid type '{e['type']}'",
            )

    def test_hermits_field_is_list(self):
        data = load()
        for e in data:
            self.assertIsInstance(e["hermits"], list, f"{e['id']}: hermits must be list")

    def test_season_field_is_int(self):
        data = load()
        for e in data:
            self.assertIsInstance(e["season"], int, f"{e['id']}: season must be int")

    def test_milestone_events_present(self):
        data = load()
        milestones = [e for e in data if e["type"] == "milestone"]
        self.assertGreater(len(milestones), 0)

    def test_each_season_has_start_event(self):
        data = load()
        for s in range(6, 11):
            season_events = [e for e in data if e["season"] == s]
            titles = " ".join(e["title"].lower() for e in season_events)
            self.assertIn("launch", titles, f"Season {s} missing a Launch milestone")


# ---------------------------------------------------------------------------
# filter_events
# ---------------------------------------------------------------------------

class TestFilterEvents(unittest.TestCase):

    def setUp(self):
        self.events = timeline.load_events()

    def test_no_filter_returns_all(self):
        result = timeline.filter_events(self.events)
        self.assertEqual(len(result), len(self.events))

    def test_filter_by_season(self):
        result = timeline.filter_events(self.events, season=7)
        self.assertTrue(all(e["season"] == 7 for e in result))
        self.assertGreater(len(result), 0)

    def test_filter_by_hermit_exact(self):
        result = timeline.filter_events(self.events, hermit="Grian")
        self.assertTrue(
            all(any("Grian" in h for h in e["hermits"]) or "All" in e["hermits"]
                for e in result),
        )
        self.assertGreater(len(result), 0)

    def test_filter_by_hermit_case_insensitive(self):
        lower = timeline.filter_events(self.events, hermit="grian")
        upper = timeline.filter_events(self.events, hermit="GRIAN")
        self.assertEqual(len(lower), len(upper))

    def test_filter_by_hermit_partial(self):
        # "Iskall" should match "Iskall85"
        result = timeline.filter_events(self.events, hermit="Iskall")
        self.assertGreater(len(result), 0)

    def test_filter_by_type_milestone(self):
        result = timeline.filter_events(self.events, event_type="milestone")
        self.assertTrue(all(e["type"] == "milestone" for e in result))
        self.assertGreater(len(result), 0)

    def test_filter_by_type_build(self):
        result = timeline.filter_events(self.events, event_type="build")
        self.assertTrue(all(e["type"] == "build" for e in result))
        self.assertGreater(len(result), 0)

    def test_search_title(self):
        result = timeline.filter_events(self.events, search="Demise")
        self.assertGreater(len(result), 0)
        for e in result:
            combined = e["title"] + e["description"] + " ".join(e["hermits"])
            self.assertRegex(combined, r"(?i)demise")

    def test_search_description(self):
        result = timeline.filter_events(self.events, search="mycelium")
        self.assertGreater(len(result), 0)

    def test_search_case_insensitive(self):
        a = timeline.filter_events(self.events, search="SAHARA")
        b = timeline.filter_events(self.events, search="sahara")
        self.assertEqual(len(a), len(b))

    def test_combined_season_and_hermit(self):
        result = timeline.filter_events(self.events, season=6, hermit="Iskall85")
        for e in result:
            self.assertEqual(e["season"], 6)
            self.assertTrue(any("Iskall" in h for h in e["hermits"]))

    def test_combined_season_and_type(self):
        result = timeline.filter_events(self.events, season=8, event_type="milestone")
        for e in result:
            self.assertEqual(e["season"], 8)
            self.assertEqual(e["type"], "milestone")

    def test_no_match_returns_empty_list(self):
        result = timeline.filter_events(self.events, season=999)
        self.assertEqual(result, [])

    def test_results_are_sorted_chronologically(self):
        result = timeline.filter_events(self.events, season=6)
        dates = [timeline._sort_key(e) for e in result]
        self.assertEqual(dates, sorted(dates))

    def test_all_seasons_results_sorted(self):
        result = timeline.filter_events(self.events)
        dates = [timeline._sort_key(e) for e in result]
        self.assertEqual(dates, sorted(dates))


# ---------------------------------------------------------------------------
# validate_event
# ---------------------------------------------------------------------------

class TestValidateEvent(unittest.TestCase):

    def _good(self):
        return {
            "id": "s6-001",
            "date": "2018-07-19",
            "date_precision": "day",
            "season": 6,
            "hermits": ["All"],
            "type": "milestone",
            "title": "Season 6 Launch",
            "description": "Season 6 begins.",
            "source": "knowledge/seasons/season-6.md",
        }

    def test_valid_event_no_errors(self):
        self.assertEqual(timeline.validate_event(self._good()), [])

    def test_missing_field(self):
        e = self._good()
        del e["date"]
        errors = timeline.validate_event(e)
        self.assertTrue(any("date" in err for err in errors))

    def test_invalid_type(self):
        e = self._good()
        e["type"] = "explosion"
        errors = timeline.validate_event(e)
        self.assertTrue(any("type" in err for err in errors))

    def test_hermits_not_list(self):
        e = self._good()
        e["hermits"] = "Grian"
        errors = timeline.validate_event(e)
        self.assertTrue(any("hermits" in err for err in errors))


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def test_default_returns_ndjson(self):
        out, code = run_cli()
        self.assertEqual(code, 0)
        lines = [l for l in out.strip().split("\n") if l]
        self.assertGreater(len(lines), 0)
        for line in lines:
            obj = json.loads(line)
            self.assertIn("id", obj)

    def test_season_filter(self):
        out, code = run_cli("--season", "7")
        self.assertEqual(code, 0)
        events = [json.loads(l) for l in out.strip().split("\n") if l]
        self.assertTrue(all(e["season"] == 7 for e in events))

    def test_hermit_filter(self):
        out, code = run_cli("--hermit", "TangoTek")
        self.assertEqual(code, 0)
        events = [json.loads(l) for l in out.strip().split("\n") if l]
        self.assertGreater(len(events), 0)

    def test_type_filter(self):
        out, code = run_cli("--type", "milestone")
        self.assertEqual(code, 0)
        events = [json.loads(l) for l in out.strip().split("\n") if l]
        self.assertTrue(all(e["type"] == "milestone" for e in events))

    def test_search_filter(self):
        out, code = run_cli("--search", "Boatem")
        self.assertEqual(code, 0)
        events = [json.loads(l) for l in out.strip().split("\n") if l]
        self.assertGreater(len(events), 0)

    def test_pretty_flag_returns_json_array(self):
        out, code = run_cli("--season", "8", "--pretty")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertTrue(all(e["season"] == 8 for e in data))

    def test_stats_flag(self):
        out, code = run_cli("--stats")
        self.assertEqual(code, 0)
        stats = json.loads(out)
        self.assertIn("total_events", stats)
        self.assertIn("by_season", stats)
        self.assertIn("by_type", stats)
        self.assertGreaterEqual(stats["total_events"], 30)

    def test_no_match_exits_1(self):
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            code = timeline.main(["--season", "999"])
        self.assertEqual(code, 1)

    def test_combined_filters(self):
        out, code = run_cli("--season", "6", "--type", "game")
        self.assertEqual(code, 0)
        events = [json.loads(l) for l in out.strip().split("\n") if l]
        for e in events:
            self.assertEqual(e["season"], 6)
            self.assertEqual(e["type"], "game")


# ---------------------------------------------------------------------------
# Content spot-checks (acceptance criteria from issue #38)
# ---------------------------------------------------------------------------

class TestContentCoverage(unittest.TestCase):
    """Verify the acceptance criteria: seasons 6-10, hermit/date/description."""

    def setUp(self):
        self.events = timeline.load_events()

    def _season(self, n):
        return timeline.filter_events(self.events, season=n)

    def test_season_6_has_demise_events(self):
        result = timeline.filter_events(self.events, season=6, search="Demise")
        self.assertGreaterEqual(len(result), 2)

    def test_season_6_has_civil_war_events(self):
        result = timeline.filter_events(self.events, season=6, search="civil war")
        # search won't find it directly — use G-Team or S.T.A.R.
        result2 = timeline.filter_events(self.events, season=6, search="G-Team")
        self.assertGreater(len(result) + len(result2), 0)

    def test_season_7_has_mycelium_event(self):
        result = timeline.filter_events(self.events, season=7, search="Mycelium")
        self.assertGreater(len(result), 0)

    def test_season_7_has_decked_out(self):
        result = timeline.filter_events(self.events, season=7, search="Decked Out")
        self.assertGreater(len(result), 0)

    def test_season_8_has_boatem(self):
        result = timeline.filter_events(self.events, season=8, search="Boatem")
        self.assertGreater(len(result), 0)

    def test_season_8_has_big_moon(self):
        result = timeline.filter_events(self.events, season=8, search="Moon")
        self.assertGreater(len(result), 0)

    def test_season_9_has_decked_out_2(self):
        result = timeline.filter_events(self.events, season=9, search="Decked Out 2")
        self.assertGreater(len(result), 0)

    def test_season_10_has_false_symmetry_win(self):
        result = timeline.filter_events(self.events, season=10, hermit="FalseSymmetry")
        self.assertGreater(len(result), 0)

    def test_every_event_has_hermits_and_description(self):
        for e in self.events:
            self.assertTrue(e.get("hermits"), f"{e['id']} has empty hermits")
            self.assertTrue(e.get("description"), f"{e['id']} has empty description")

    def test_grian_events_span_multiple_seasons(self):
        result = timeline.filter_events(self.events, hermit="Grian")
        seasons = {e["season"] for e in result if "All" not in e["hermits"]}
        self.assertGreaterEqual(len(seasons), 3)

    def test_tango_decked_out_across_seasons(self):
        result = timeline.filter_events(self.events, hermit="TangoTek", search="Decked Out")
        seasons = {e["season"] for e in result}
        # Decked Out appeared in S7 and S9
        self.assertGreaterEqual(len(seasons), 2)


if __name__ == "__main__":
    unittest.main()
