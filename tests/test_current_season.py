"""
Tests for tools/current_season.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools.current_season as _cs_module
from tools.current_season import (
    _build_narrative,
    _weeks_in,
    find_current_season,
    format_status,
    get_current_season_status,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_today(d: date):
    """Context manager that patches the module-level _TODAY override."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old = _cs_module._TODAY
        _cs_module._TODAY = d
        try:
            yield
        finally:
            _cs_module._TODAY = old

    return _ctx()


# ---------------------------------------------------------------------------
# _weeks_in
# ---------------------------------------------------------------------------

class TestWeeksIn(unittest.TestCase):
    def test_exact_weeks(self):
        with _with_today(date(2026, 1, 1)):
            # 2025-12-04 to 2026-01-01 = 28 days = 4 complete weeks
            result = _weeks_in("2025-12-04")
            self.assertEqual(result, 4)

    def test_same_day(self):
        with _with_today(date(2025, 11, 8)):
            result = _weeks_in("2025-11-08")
            self.assertEqual(result, 0)

    def test_one_week(self):
        with _with_today(date(2025, 11, 15)):
            result = _weeks_in("2025-11-08")
            self.assertEqual(result, 1)

    def test_empty_string(self):
        result = _weeks_in("")
        self.assertIsNone(result)

    def test_invalid_date(self):
        result = _weeks_in("not-a-date")
        self.assertIsNone(result)

    def test_truncated_to_date(self):
        # Only first 10 chars used
        with _with_today(date(2025, 11, 22)):
            result = _weeks_in("2025-11-08T00:00:00")
            self.assertEqual(result, 2)

    def test_non_negative(self):
        # Future start date should return 0 (not negative)
        with _with_today(date(2020, 1, 1)):
            result = _weeks_in("2025-11-08")
            self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# find_current_season
# ---------------------------------------------------------------------------

class TestFindCurrentSeason(unittest.TestCase):
    def test_returns_integer(self):
        result = find_current_season()
        self.assertIsInstance(result, int)

    def test_returns_known_season(self):
        from tools.season_recap import KNOWN_SEASONS
        result = find_current_season()
        self.assertIn(result, KNOWN_SEASONS)

    def test_returns_season_11(self):
        # Season 11 is the latest and has status: ongoing
        result = find_current_season()
        self.assertEqual(result, 11)


# ---------------------------------------------------------------------------
# get_current_season_status
# ---------------------------------------------------------------------------

class TestGetCurrentSeasonStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status = get_current_season_status()

    def test_returns_dict(self):
        self.assertIsInstance(self.status, dict)

    def test_required_keys_present(self):
        required = {
            "season", "status", "start_date", "weeks_in",
            "minecraft_version", "member_count", "theme",
            "members", "key_themes", "notable_events",
            "recent_events", "narrative",
        }
        for key in required:
            self.assertIn(key, self.status, f"Missing key: {key}")

    def test_season_is_11(self):
        self.assertEqual(self.status["season"], 11)

    def test_status_is_ongoing(self):
        self.assertIn("ongoing", self.status["status"].lower())

    def test_start_date_present(self):
        self.assertTrue(self.status["start_date"])

    def test_member_count_positive(self):
        self.assertGreater(self.status["member_count"], 0)

    def test_members_is_list(self):
        self.assertIsInstance(self.status["members"], list)

    def test_members_non_empty(self):
        self.assertGreater(len(self.status["members"]), 0)

    def test_recent_events_is_list(self):
        self.assertIsInstance(self.status["recent_events"], list)

    def test_recent_events_capped_at_top(self):
        status5 = get_current_season_status(top_events=5)
        self.assertLessEqual(len(status5["recent_events"]), 5)

    def test_recent_events_capped_at_top_3(self):
        status3 = get_current_season_status(top_events=3)
        self.assertLessEqual(len(status3["recent_events"]), 3)

    def test_recent_event_keys(self):
        for ev in self.status["recent_events"]:
            for key in ("date", "title", "type", "hermits", "description"):
                self.assertIn(key, ev)

    def test_narrative_is_non_empty_string(self):
        narrative = self.status["narrative"]
        self.assertIsInstance(narrative, str)
        self.assertGreater(len(narrative), 20)

    def test_narrative_mentions_season(self):
        narrative = self.status["narrative"]
        self.assertIn("11", narrative)

    def test_weeks_in_non_negative(self):
        weeks = self.status["weeks_in"]
        if weeks is not None:
            self.assertGreaterEqual(weeks, 0)

    def test_key_themes_is_list(self):
        self.assertIsInstance(self.status["key_themes"], list)

    def test_notable_events_is_list(self):
        self.assertIsInstance(self.status["notable_events"], list)

    def test_minecraft_version_present(self):
        self.assertTrue(self.status["minecraft_version"])


# ---------------------------------------------------------------------------
# _build_narrative
# ---------------------------------------------------------------------------

class TestBuildNarrative(unittest.TestCase):
    def _make_recap(self, **overrides) -> dict:
        base = {
            "season": 11,
            "status": "ongoing",
            "start_date": "2025-11-08",
            "theme": "Decked Out 3; groups continue",
            "member_count": 25,
            "key_themes": ["**Decked Out 3** — the sequel", "Group dynamics"],
            "notable_events": ["Season launch", "Decked Out 3 starts"],
        }
        base.update(overrides)
        return base

    def test_returns_string(self):
        result = _build_narrative(self._make_recap(), [])
        self.assertIsInstance(result, str)

    def test_mentions_season_number(self):
        result = _build_narrative(self._make_recap(), [])
        self.assertIn("11", result)

    def test_mentions_member_count(self):
        result = _build_narrative(self._make_recap(), [])
        self.assertIn("25", result)

    def test_mentions_theme(self):
        result = _build_narrative(self._make_recap(), [])
        self.assertIn("Decked Out 3", result)

    def test_ongoing_says_live(self):
        result = _build_narrative(self._make_recap(status="ongoing"), [])
        self.assertIn("live", result.lower())

    def test_ended_says_ended(self):
        result = _build_narrative(self._make_recap(status="ended"), [])
        self.assertIn("ended", result.lower())

    def test_includes_recent_event(self):
        events = [{"title": "The Big Build", "date": "2025-12-01"}]
        result = _build_narrative(self._make_recap(), events)
        self.assertIn("The Big Build", result)

    def test_no_crash_on_empty_theme(self):
        result = _build_narrative(self._make_recap(theme=""), [])
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# format_status
# ---------------------------------------------------------------------------

class TestFormatStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status = get_current_season_status()
        cls.text = format_status(cls.status)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_contains_season_number(self):
        self.assertIn("11", self.text)

    def test_contains_what_is_happening_now(self):
        self.assertIn("WHAT'S HAPPENING NOW", self.text)

    def test_contains_member_count(self):
        self.assertIn(str(self.status["member_count"]), self.text)

    def test_contains_started(self):
        self.assertIn("Started", self.text)

    def test_contains_recent_events_header(self):
        if self.status["recent_events"]:
            self.assertIn("Recent events", self.text)

    def test_contains_summary_header(self):
        if self.status["narrative"]:
            self.assertIn("Summary", self.text)

    def test_non_empty(self):
        self.assertGreater(len(self.text), 100)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCurrentSeasonCLI(unittest.TestCase):
    def test_default_exits_0(self):
        rc = main([])
        self.assertEqual(rc, 0)

    def test_json_exits_0(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json"])
        self.assertEqual(rc, 0)

    def test_json_output_is_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json"])
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, dict)

    def test_json_output_has_required_keys(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json"])
        data = json.loads(buf.getvalue())
        for key in ("season", "status", "member_count", "recent_events", "narrative"):
            self.assertIn(key, data)

    def test_top_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--top", "3", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertLessEqual(len(data["recent_events"]), 3)

    def test_text_output_contains_hermitcraft(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([])
        self.assertIn("HERMITCRAFT", buf.getvalue())

    def test_subprocess_invocation(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.current_season"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("HERMITCRAFT", proc.stdout)

    def test_subprocess_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.current_season", "--json"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["season"], 11)
        self.assertIn("narrative", data)


if __name__ == "__main__":
    unittest.main()
