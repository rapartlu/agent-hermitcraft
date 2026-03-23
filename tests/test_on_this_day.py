#!/usr/bin/env python3
"""Tests for tools/on_this_day.py"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Make sure the project root is on the path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.on_this_day import (
    DEFAULT_WINDOW,
    _infer_precision,
    _parse_frontmatter,
    find_on_this_day,
    load_events,
    load_hermit_profiles,
    matches_on_this_day,
    synthesise_hermit_events,
    _circular_distance,
    _day_of_year,
    _parse_event_date,
)

EVENTS_FILE = ROOT / "knowledge" / "timelines" / "events.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    id: str = "t-001",
    date: str = "2020-04-13",
    date_precision: str = "day",
    season: int = 7,
    hermits: list[str] | None = None,
    event_type: str = "milestone",
    title: str = "Test event",
    description: str = "A test event.",
    source: str = "test",
) -> dict:
    return {
        "id": id,
        "date": date,
        "date_precision": date_precision,
        "season": season,
        "hermits": hermits or [],
        "type": event_type,
        "title": title,
        "description": description,
        "source": source,
    }


# ---------------------------------------------------------------------------
# TestDateHelpers
# ---------------------------------------------------------------------------

class TestDateHelpers(unittest.TestCase):

    def test_parse_full_date(self):
        e = _make_event(date="2012-04-13")
        self.assertEqual(_parse_event_date(e), (2012, 4, 13))

    def test_parse_year_month(self):
        e = _make_event(date="2025-11")
        self.assertEqual(_parse_event_date(e), (2025, 11, None))

    def test_parse_year_only(self):
        e = _make_event(date="2018")
        self.assertEqual(_parse_event_date(e), (2018, None, None))

    def test_day_of_year_jan_1(self):
        self.assertEqual(_day_of_year(1, 1), 1)

    def test_day_of_year_dec_31(self):
        self.assertEqual(_day_of_year(12, 31), 365)

    def test_day_of_year_apr_13(self):
        # April 13 in non-leap year: 31+28+31+13 = 103
        self.assertEqual(_day_of_year(4, 13), 103)

    def test_circular_distance_same(self):
        self.assertEqual(_circular_distance(100, 100), 0)

    def test_circular_distance_forward(self):
        self.assertEqual(_circular_distance(100, 107), 7)

    def test_circular_distance_wrap(self):
        # Dec 31 (365) to Jan 1 (1): min(364, 1) = 1
        self.assertEqual(_circular_distance(365, 1), 1)

    def test_circular_distance_symmetric(self):
        self.assertEqual(_circular_distance(10, 20), _circular_distance(20, 10))


# ---------------------------------------------------------------------------
# TestMatchesOnThisDay
# ---------------------------------------------------------------------------

class TestMatchesOnThisDay(unittest.TestCase):

    def test_exact_day_match(self):
        e = _make_event(date="2012-04-13", date_precision="day")
        self.assertTrue(matches_on_this_day(e, 4, 13, window=0))

    def test_within_window(self):
        e = _make_event(date="2012-04-15", date_precision="day")
        self.assertTrue(matches_on_this_day(e, 4, 13, window=7))

    def test_outside_window(self):
        e = _make_event(date="2012-04-25", date_precision="day")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7))

    def test_exactly_at_window_edge(self):
        e = _make_event(date="2012-04-20", date_precision="day")
        self.assertTrue(matches_on_this_day(e, 4, 13, window=7))

    def test_one_past_window_edge(self):
        e = _make_event(date="2012-04-21", date_precision="day")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7))

    def test_year_wrap_dec_to_jan(self):
        # Dec 31 is within 3 days of Jan 1
        e = _make_event(date="2020-12-31", date_precision="day")
        self.assertTrue(matches_on_this_day(e, 1, 1, window=3))

    def test_approximate_included_by_default(self):
        e = _make_event(date="2017-04-13", date_precision="approximate")
        self.assertTrue(matches_on_this_day(e, 4, 13, window=7))

    def test_approximate_excluded_when_flag_off(self):
        e = _make_event(date="2017-04-13", date_precision="approximate")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7, include_approximate=False))

    def test_month_precision_matches_correct_month(self):
        e = _make_event(date="2025-11", date_precision="month")
        self.assertTrue(matches_on_this_day(e, 11, 15, window=7))

    def test_month_precision_wrong_month(self):
        e = _make_event(date="2025-11", date_precision="month")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7))

    def test_year_precision_excluded_by_default(self):
        e = _make_event(date="2018", date_precision="year")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7))

    def test_year_precision_included_with_flag(self):
        e = _make_event(date="2018", date_precision="year")
        self.assertTrue(matches_on_this_day(e, 4, 13, window=7, include_year=True))

    def test_missing_day_for_day_precision_returns_false(self):
        e = _make_event(date="2020-04", date_precision="day")
        self.assertFalse(matches_on_this_day(e, 4, 13, window=7))


# ---------------------------------------------------------------------------
# TestFindOnThisDay
# ---------------------------------------------------------------------------

class TestFindOnThisDay(unittest.TestCase):

    def setUp(self):
        self.events = [
            _make_event(id="e1", date="2012-04-13", date_precision="day", season=1),
            _make_event(id="e2", date="2017-04-13", date_precision="approximate", season=5),
            _make_event(id="e3", date="2020-06-17", date_precision="day", season=7),
            _make_event(id="e4", date="2025-11", date_precision="month", season=11),
            _make_event(id="e5", date="2018", date_precision="year", season=6),
            _make_event(id="e6", date="2012-12-31", date_precision="day", season=1),
        ]

    def test_finds_exact_day_match(self):
        results = find_on_this_day(self.events, 4, 13, window=0)
        ids = [e["id"] for e in results]
        self.assertIn("e1", ids)

    def test_approximate_included_by_default(self):
        results = find_on_this_day(self.events, 4, 13, window=0)
        ids = [e["id"] for e in results]
        self.assertIn("e2", ids)

    def test_approximate_excluded(self):
        results = find_on_this_day(self.events, 4, 13, window=0, include_approximate=False)
        ids = [e["id"] for e in results]
        self.assertNotIn("e2", ids)

    def test_year_events_excluded_by_default(self):
        results = find_on_this_day(self.events, 4, 13, window=7)
        ids = [e["id"] for e in results]
        self.assertNotIn("e5", ids)

    def test_year_events_included_with_flag(self):
        results = find_on_this_day(self.events, 4, 13, window=7, include_year=True)
        ids = [e["id"] for e in results]
        self.assertIn("e5", ids)

    def test_sorted_oldest_year_first(self):
        results = find_on_this_day(self.events, 4, 13, window=0)
        years = [_parse_event_date(e)[0] for e in results]
        self.assertEqual(years, sorted(years))

    def test_month_match_by_month(self):
        results = find_on_this_day(self.events, 11, 10, window=7)
        ids = [e["id"] for e in results]
        self.assertIn("e4", ids)

    def test_no_match_returns_empty_list(self):
        results = find_on_this_day(self.events, 2, 14, window=0)
        self.assertEqual(results, [])

    def test_year_wrap_included(self):
        results = find_on_this_day(self.events, 1, 1, window=3)
        ids = [e["id"] for e in results]
        self.assertIn("e6", ids)


# ---------------------------------------------------------------------------
# TestEventsFile — validate acceptance criteria against real data
# ---------------------------------------------------------------------------

class TestEventsFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.events = load_events()

    def test_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists())

    def test_valid_json_array(self):
        self.assertIsInstance(self.events, list)
        self.assertGreater(len(self.events), 0)

    # Acceptance criterion 1: server founding on April 13
    def test_server_founding_april_13(self):
        results = find_on_this_day(self.events, 4, 13, window=0, include_approximate=True)
        self.assertGreater(
            len(results), 0,
            "Expected at least one event on April 13 (server founding)",
        )
        ids = [e["id"] for e in results]
        self.assertIn("s1-001", ids, "Server founding event s1-001 should be returned")

    # Acceptance criterion 2: Season 7 launch on June 17
    def test_season_7_launch_june_17(self):
        results = find_on_this_day(self.events, 6, 17, window=7)
        self.assertGreater(
            len(results), 0,
            "Expected events near June 17 (Season 7 launch area)",
        )

    # Acceptance criterion 3: year-precision events handled without crash
    def test_year_precision_no_crash(self):
        try:
            results = find_on_this_day(self.events, 6, 1, window=7, include_year=True)
            # Should not raise; year-only events appear when flag is set
            year_events = [e for e in self.events if e.get("date_precision") == "year"]
            self.assertGreater(
                len([e for e in results if e.get("date_precision") == "year"]),
                0,
                "Year-precision events should appear with --include-year",
            )
        except Exception as exc:
            self.fail(f"Year-precision handling raised an exception: {exc}")

    def test_year_precision_excluded_by_default_real_data(self):
        results = find_on_this_day(self.events, 6, 1, window=7, include_year=False)
        for e in results:
            self.assertNotEqual(e.get("date_precision"), "year")


# ---------------------------------------------------------------------------
# TestCLI — subprocess tests for the command-line interface
# ---------------------------------------------------------------------------

TOOL = str(ROOT / "tools" / "on_this_day.py")


class TestCLI(unittest.TestCase):

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, TOOL] + args,
            capture_output=True,
            text=True,
        )

    def test_april_13_returns_founding(self):
        r = self._run(["--month", "4", "--day", "13"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        ids = [e["id"] for e in events]
        self.assertIn("s1-001", ids)

    def test_ndjson_output_default(self):
        r = self._run(["--month", "4", "--day", "13"])
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.strip().splitlines()
        self.assertGreater(len(lines), 0)
        for line in lines:
            obj = json.loads(line)
            self.assertIsInstance(obj, dict)

    def test_pretty_output_is_json_array(self):
        r = self._run(["--month", "4", "--day", "13", "--pretty"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIsInstance(data, list)

    def test_no_match_returns_exit_1(self):
        r = self._run(["--month", "2", "--day", "14", "--window", "0"])
        self.assertEqual(r.returncode, 1)

    def test_invalid_date_returns_exit_2(self):
        r = self._run(["--month", "13", "--day", "1"])
        self.assertEqual(r.returncode, 2)

    def test_invalid_day_returns_exit_2(self):
        r = self._run(["--month", "2", "--day", "30"])
        self.assertEqual(r.returncode, 2)

    def test_include_year_flag(self):
        r = self._run(["--month", "6", "--day", "1", "--include-year"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        precisions = {e.get("date_precision") for e in events}
        self.assertIn("year", precisions)

    def test_exclude_approximate_flag(self):
        # April 13, window=0: s1-001 and s1-002 are "day" precision so they
        # are always returned; s5-001/s5-002 are "approximate" and must be
        # absent.  We use window=0 so only exact-day matches are possible,
        # guaranteeing at least two "day" results independent of --no-approximate.
        r = self._run(["--month", "4", "--day", "13", "--window", "0", "--no-approximate"])
        self.assertEqual(r.returncode, 0, f"Expected results even without approximates; stderr: {r.stderr}")
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        for e in events:
            self.assertNotEqual(e.get("date_precision"), "approximate")

    def test_narrow_window_zero(self):
        r = self._run(["--month", "4", "--day", "13", "--window", "0"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        ids = [e["id"] for e in events]
        self.assertIn("s1-001", ids)

    def test_results_sorted_oldest_first(self):
        r = self._run(["--month", "4", "--day", "13"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        years = []
        for e in events:
            y, _, _ = _parse_event_date(e)
            if y:
                years.append(y)
        self.assertEqual(years, sorted(years))

    def test_default_date_uses_today(self):
        """Running without --month/--day should not crash (uses today)."""
        r = self._run([])
        # Exit 0 (found events) or 1 (none today) — not 2 (error)
        self.assertIn(r.returncode, (0, 1))

    def test_include_hermit_anniversaries_flag_no_crash(self):
        r = self._run(["--month", "4", "--day", "13", "--include-hermit-anniversaries"])
        # exit 0 (found) or 1 (none) — never 2 (error)
        self.assertIn(r.returncode, (0, 1))

    def test_include_hermit_anniversaries_surfaces_founding_join(self):
        # April 13 is Xisumavoid's / Keralis's / Hypnotizd's join date
        r = self._run([
            "--month", "4", "--day", "13",
            "--window", "0",
            "--include-hermit-anniversaries",
        ])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        ids = [e["id"] for e in events]
        # At least one hermit join event for April 13 founding members
        hermit_join_ids = [i for i in ids if i.startswith("hermit-") and i.endswith("-join")]
        self.assertGreater(len(hermit_join_ids), 0, "Expected hermit join events on April 13")

    def test_hermit_anniversary_source_field(self):
        r = self._run([
            "--month", "4", "--day", "13",
            "--window", "0",
            "--include-hermit-anniversaries",
        ])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        hermit_events = [e for e in events if e.get("id", "").startswith("hermit-")]
        for e in hermit_events:
            self.assertEqual(e["source"], "hermit_profile")
            self.assertEqual(e["type"], "milestone")

    def test_anniversaries_absent_without_flag(self):
        r = self._run(["--month", "4", "--day", "13", "--window", "0"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        ids = [e["id"] for e in events]
        self.assertFalse(any(i.startswith("hermit-") for i in ids))

    def test_all_events_flag_no_crash(self):
        """--all-events should run without error."""
        r = self._run(["--month", "4", "--day", "13", "--all-events"])
        self.assertIn(r.returncode, (0, 1))

    def test_all_events_enables_hermit_anniversaries(self):
        """--all-events should include hermit join events."""
        r = self._run(["--month", "4", "--day", "13", "--window", "0", "--all-events"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        ids = [e["id"] for e in events]
        hermit_join_ids = [i for i in ids if i.startswith("hermit-") and i.endswith("-join")]
        self.assertGreater(len(hermit_join_ids), 0, "Expected hermit join events with --all-events")

    def test_all_events_enables_year_precision(self):
        """--all-events should include year-precision events."""
        r = self._run(["--month", "6", "--day", "1", "--all-events"])
        self.assertEqual(r.returncode, 0)
        events = [json.loads(line) for line in r.stdout.strip().splitlines()]
        precisions = {e.get("date_precision") for e in events}
        self.assertIn("year", precisions, "Expected year-precision events with --all-events")

    def test_all_events_is_superset_of_default(self):
        """--all-events should return at least as many events as the default."""
        r_default = self._run(["--month", "4", "--day", "13"])
        r_all = self._run(["--month", "4", "--day", "13", "--all-events"])
        self.assertEqual(r_default.returncode, 0)
        self.assertEqual(r_all.returncode, 0)
        default_events = [json.loads(line) for line in r_default.stdout.strip().splitlines()]
        all_events = [json.loads(line) for line in r_all.stdout.strip().splitlines()]
        self.assertGreaterEqual(len(all_events), len(default_events))


# ---------------------------------------------------------------------------
# TestParseFrontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):

    def test_parses_scalar_fields(self):
        content = "---\nname: Grian\njoined_season: 6\n---\n# Body"
        fm = _parse_frontmatter(content)
        self.assertEqual(fm["name"], "Grian")
        self.assertEqual(fm["joined_season"], "6")

    def test_strips_quotes(self):
        content = '---\njoin_date: "2018-07-19"\nyt_channel_start: "2012"\n---\n'
        fm = _parse_frontmatter(content)
        self.assertEqual(fm["join_date"], "2018-07-19")
        self.assertEqual(fm["yt_channel_start"], "2012")

    def test_missing_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter("# No frontmatter"), {})

    def test_unclosed_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter("---\nname: Grian\n"), {})

    def test_skips_list_items(self):
        content = "---\nname: Grian\nspecialties:\n  - building\n---\n"
        fm = _parse_frontmatter(content)
        self.assertIn("name", fm)
        self.assertNotIn("specialties", fm)


# ---------------------------------------------------------------------------
# TestInferPrecision
# ---------------------------------------------------------------------------

class TestInferPrecision(unittest.TestCase):

    def test_full_date_is_day(self):
        self.assertEqual(_infer_precision("2012-04-13"), "day")

    def test_year_month_is_month(self):
        self.assertEqual(_infer_precision("2016-03"), "month")

    def test_year_only_is_year(self):
        self.assertEqual(_infer_precision("2013"), "year")


# ---------------------------------------------------------------------------
# TestSynthesiseHermitEvents
# ---------------------------------------------------------------------------

class TestSynthesiseHermitEvents(unittest.TestCase):

    def _profile(self, **kwargs) -> dict:
        base = {"name": "TestHermit", "joined_season": "7"}
        base.update(kwargs)
        return base

    def test_join_date_creates_join_event(self):
        profiles = [self._profile(join_date="2020-06-17")]
        events = synthesise_hermit_events(profiles)
        join_events = [e for e in events if e["id"].endswith("-join")]
        self.assertEqual(len(join_events), 1)
        e = join_events[0]
        self.assertEqual(e["date"], "2020-06-17")
        self.assertEqual(e["date_precision"], "day")
        self.assertEqual(e["source"], "hermit_profile")
        self.assertEqual(e["type"], "milestone")
        self.assertIn("TestHermit", e["hermits"])

    def test_yt_channel_start_creates_yt_event(self):
        profiles = [self._profile(join_date="2020-06-17", yt_channel_start="2018")]
        events = synthesise_hermit_events(profiles)
        yt_events = [e for e in events if e["id"].endswith("-yt")]
        self.assertEqual(len(yt_events), 1)
        e = yt_events[0]
        self.assertEqual(e["date"], "2018")
        self.assertEqual(e["date_precision"], "year")
        self.assertEqual(e["season"], 0)

    def test_no_join_date_no_join_event(self):
        profiles = [self._profile()]
        events = synthesise_hermit_events(profiles)
        self.assertFalse(any(e["id"].endswith("-join") for e in events))

    def test_no_yt_channel_start_no_yt_event(self):
        profiles = [self._profile(join_date="2020-06-17")]
        events = synthesise_hermit_events(profiles)
        self.assertFalse(any(e["id"].endswith("-yt") for e in events))

    def test_month_precision_join_date(self):
        profiles = [self._profile(join_date="2016-03")]
        events = synthesise_hermit_events(profiles)
        join_event = next(e for e in events if e["id"].endswith("-join"))
        self.assertEqual(join_event["date_precision"], "month")

    def test_multiple_profiles(self):
        profiles = [
            self._profile(name="Alpha", join_date="2012-04-13"),
            self._profile(name="Beta",  join_date="2018-07-19"),
        ]
        events = synthesise_hermit_events(profiles)
        ids = [e["id"] for e in events]
        self.assertIn("hermit-alpha-join", ids)
        self.assertIn("hermit-beta-join", ids)

    def test_season_field_set_from_joined_season(self):
        profiles = [self._profile(join_date="2016-03", joined_season="4")]
        events = synthesise_hermit_events(profiles)
        join_event = next(e for e in events if e["id"].endswith("-join"))
        self.assertEqual(join_event["season"], 4)

    def test_empty_profiles_returns_empty_list(self):
        self.assertEqual(synthesise_hermit_events([]), [])


# ---------------------------------------------------------------------------
# TestHermitProfilesRealData
# ---------------------------------------------------------------------------

class TestHermitProfilesRealData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.profiles = load_hermit_profiles()

    def test_profiles_loaded(self):
        self.assertGreater(len(self.profiles), 0)

    def test_at_least_10_profiles_have_join_date(self):
        with_join = [p for p in self.profiles if p.get("join_date")]
        self.assertGreaterEqual(
            len(with_join), 10,
            f"Expected ≥10 profiles with join_date, found {len(with_join)}",
        )

    def test_join_date_format_is_valid(self):
        """join_date values should be YYYY, YYYY-MM, or YYYY-MM-DD."""
        pattern = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
        for p in self.profiles:
            jd = p.get("join_date", "")
            if jd:
                self.assertRegex(jd, pattern, f"Bad join_date in profile {p.get('name')}")

    def test_synthesised_events_are_matchable(self):
        """Synthesised events for April 13 founding members should match."""
        events = synthesise_hermit_events(self.profiles)
        # Xisumavoid, Keralis, Hypnotizd all have join_date 2012-04-13
        apr13_joins = [
            e for e in events
            if e.get("id", "").endswith("-join") and e.get("date") == "2012-04-13"
        ]
        self.assertGreaterEqual(len(apr13_joins), 3,
            "Expected ≥3 join events for the April 13 founding date")

    def test_xisumavoid_join_event_exists(self):
        events = synthesise_hermit_events(self.profiles)
        ids = [e["id"] for e in events]
        self.assertIn("hermit-xisumavoid-join", ids)

    def test_grian_join_event_has_correct_date(self):
        events = synthesise_hermit_events(self.profiles)
        grian_join = next((e for e in events if e["id"] == "hermit-grian-join"), None)
        self.assertIsNotNone(grian_join)
        self.assertEqual(grian_join["date"], "2018-07-19")


if __name__ == "__main__":
    unittest.main()
