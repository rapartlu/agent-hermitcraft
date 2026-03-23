"""
Tests for tools/season_compare.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.season_compare import (
    _set_diff,
    _duration_to_days,
    build_comparison,
    format_text,
    main,
    KNOWN_SEASONS,
)


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------

class TestSetDiff(unittest.TestCase):
    def test_common_members(self):
        a = ["Alice", "Bob", "Carol"]
        b = ["Bob", "Carol", "Dave"]
        common, only_a, only_b = _set_diff(a, b)
        self.assertIn("Bob", common)
        self.assertIn("Carol", common)
        self.assertIn("Alice", only_a)
        self.assertIn("Dave", only_b)

    def test_identical_rosters(self):
        roster = ["Grian", "MumboJumbo", "Xisumavoid"]
        common, only_a, only_b = _set_diff(roster, roster)
        self.assertEqual(sorted(common), sorted(roster))
        self.assertEqual(only_a, [])
        self.assertEqual(only_b, [])

    def test_case_insensitive(self):
        a = ["grian", "mumbo"]
        b = ["Grian", "Mumbo"]
        common, only_a, only_b = _set_diff(a, b)
        self.assertEqual(len(common), 2)
        self.assertEqual(only_a, [])
        self.assertEqual(only_b, [])

    def test_empty_lists(self):
        common, only_a, only_b = _set_diff([], [])
        self.assertEqual(common, [])
        self.assertEqual(only_a, [])
        self.assertEqual(only_b, [])

    def test_disjoint_rosters(self):
        a = ["Alice"]
        b = ["Bob"]
        common, only_a, only_b = _set_diff(a, b)
        self.assertEqual(common, [])
        self.assertIn("Alice", only_a)
        self.assertIn("Bob", only_b)


class TestDurationToDays(unittest.TestCase):
    def test_months(self):
        result = _duration_to_days("~21.5 months (longest season)")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, int(21.5 * 30), delta=2)

    def test_integer_months(self):
        result = _duration_to_days("~13 months")
        self.assertEqual(result, 13 * 30)

    def test_years(self):
        result = _duration_to_days("~1.5 years")
        self.assertAlmostEqual(result, int(1.5 * 365), delta=2)

    def test_unparseable(self):
        result = _duration_to_days("unknown")
        self.assertIsNone(result)

    def test_empty_string(self):
        result = _duration_to_days("")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Integration tests — build_comparison
# ---------------------------------------------------------------------------

class TestBuildComparison(unittest.TestCase):
    def setUp(self):
        """Build the comparison once; reuse across tests."""
        self.cmp = build_comparison(9, 10)

    def test_seasons_key(self):
        self.assertEqual(self.cmp["seasons"], [9, 10])

    def test_participant_count_keys(self):
        pc = self.cmp["participant_count"]
        self.assertIn("a", pc)
        self.assertIn("b", pc)
        self.assertIn("delta", pc)
        self.assertIsInstance(pc["a"], int)
        self.assertIsInstance(pc["b"], int)

    def test_delta_correct(self):
        pc = self.cmp["participant_count"]
        self.assertEqual(pc["delta"], pc["b"] - pc["a"])

    def test_duration_keys(self):
        dur = self.cmp["duration"]
        self.assertIn("a", dur)
        self.assertIn("b", dur)
        self.assertIn("longer", dur)

    def test_minecraft_version_keys(self):
        mv = self.cmp["minecraft_version"]
        self.assertIn("a", mv)
        self.assertIn("b", mv)
        self.assertTrue(mv["a"])
        self.assertTrue(mv["b"])

    def test_roster_changes_keys(self):
        rc = self.cmp["roster_changes"]
        self.assertIn("common", rc)
        self.assertIn("left_after_a", rc)
        self.assertIn("joined_for_b", rc)

    def test_roster_changes_are_lists(self):
        rc = self.cmp["roster_changes"]
        self.assertIsInstance(rc["common"], list)
        self.assertIsInstance(rc["left_after_a"], list)
        self.assertIsInstance(rc["joined_for_b"], list)

    def test_themes_keys(self):
        themes = self.cmp["themes"]
        self.assertIn("a", themes)
        self.assertIn("b", themes)
        self.assertIn("shared", themes)
        self.assertIsInstance(themes["a"], list)
        self.assertIsInstance(themes["b"], list)

    def test_notable_events_keys(self):
        ne = self.cmp["notable_events"]
        self.assertIn("a", ne)
        self.assertIn("b", ne)

    def test_timeline_event_count_non_negative(self):
        tc = self.cmp["timeline_event_count"]
        self.assertGreaterEqual(tc["a"], 0)
        self.assertGreaterEqual(tc["b"], 0)

    def test_season_a_and_b_recap_present(self):
        self.assertIn("season_a", self.cmp)
        self.assertIn("season_b", self.cmp)
        self.assertEqual(self.cmp["season_a"]["season"], 9)
        self.assertEqual(self.cmp["season_b"]["season"], 10)

    def test_s9_s10_tinfoilchef_departed(self):
        """TinfoilChef left after Season 9 and is not in Season 10."""
        left = self.cmp["roster_changes"]["left_after_a"]
        names_lower = [n.lower() for n in left]
        self.assertTrue(
            any("tinfoilchef" in n for n in names_lower),
            msg=f"Expected TinfoilChef in left_after_a, got: {left}",
        )

    def test_s9_s10_member_count_increased(self):
        """Season 10 had more participants than Season 9 (27 vs 26)."""
        pc = self.cmp["participant_count"]
        self.assertGreater(pc["b"], pc["a"],
                           msg="S10 should have more participants than S9")

    def test_same_season_no_roster_changes(self):
        cmp = build_comparison(9, 9)
        rc = cmp["roster_changes"]
        self.assertEqual(rc["left_after_a"], [])
        self.assertEqual(rc["joined_for_b"], [])
        self.assertTrue(len(rc["common"]) > 0)


# ---------------------------------------------------------------------------
# format_text tests
# ---------------------------------------------------------------------------

class TestFormatText(unittest.TestCase):
    def setUp(self):
        self.cmp = build_comparison(9, 10)
        self.text = format_text(self.cmp)

    def test_output_is_string(self):
        self.assertIsInstance(self.text, str)

    def test_contains_both_season_numbers(self):
        self.assertIn("9", self.text)
        self.assertIn("10", self.text)

    def test_contains_participant_section(self):
        self.assertIn("Participants", self.text)

    def test_contains_roster_changes_section(self):
        self.assertIn("ROSTER CHANGES", self.text)

    def test_contains_themes_section(self):
        self.assertIn("KEY THEMES", self.text)

    def test_contains_notable_events_section(self):
        self.assertIn("NOTABLE EVENTS", self.text)

    def test_non_empty(self):
        self.assertGreater(len(self.text), 200)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def test_list_flag(self):
        result = main(["--list"])
        self.assertEqual(result, 0)

    def test_missing_args_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertNotEqual(ctx.exception.code, 0)

    def test_invalid_season_exits_1(self):
        result = main(["--a", "99", "--b", "10"])
        self.assertEqual(result, 1)

    def test_valid_comparison_text(self, capsys=None):
        result = main(["--a", "9", "--b", "10"])
        self.assertEqual(result, 0)

    def test_valid_comparison_json(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = main(["--a", "9", "--b", "10", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["seasons"], [9, 10])
        self.assertIn("participant_count", data)
        self.assertIn("roster_changes", data)
        self.assertIn("themes", data)
        self.assertIn("notable_events", data)
        # Full recap dicts should be omitted from JSON output (too large)
        self.assertNotIn("season_a", data)
        self.assertNotIn("season_b", data)

    def test_compare_early_seasons(self):
        """Seasons 1 and 2 should compare without error."""
        result = main(["--a", "1", "--b", "2"])
        self.assertEqual(result, 0)

    def test_compare_same_season(self):
        """Comparing a season to itself should succeed with zero deltas."""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = main(["--a", "7", "--b", "7", "--json"])
        self.assertEqual(result, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["participant_count"]["delta"], 0)

    def test_subprocess_invocation(self):
        """Smoke-test: the module runs correctly as a subprocess."""
        proc = subprocess.run(
            [sys.executable, "-m", "tools.season_compare", "--a", "9", "--b", "10"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Season 9", proc.stdout)
        self.assertIn("Season 10", proc.stdout)


# ---------------------------------------------------------------------------
# HTTP API surface test (documents expected JSON shape)
# ---------------------------------------------------------------------------

class TestAPIShape(unittest.TestCase):
    """
    Validates the shape of the JSON that GET /seasons/compare?a=N&b=M returns.
    The actual HTTP server is not tested here (integration test concern),
    but the dict contract is verified.
    """

    def _api_response(self, a: int, b: int) -> dict:
        """Simulate what the API handler returns."""
        cmp = build_comparison(a, b)
        # API strips the large recap sub-dicts, matching --json CLI behaviour
        return {k: v for k, v in cmp.items() if k not in ("season_a", "season_b")}

    def test_shape_s9_s10(self):
        data = self._api_response(9, 10)
        required_keys = {
            "seasons",
            "participant_count",
            "duration",
            "minecraft_version",
            "roster_changes",
            "themes",
            "notable_events",
            "timeline_event_count",
        }
        self.assertTrue(required_keys.issubset(data.keys()),
                        msg=f"Missing keys: {required_keys - data.keys()}")

    def test_participant_count_has_delta(self):
        data = self._api_response(7, 8)
        self.assertIn("delta", data["participant_count"])

    def test_longer_field_is_int_or_none(self):
        data = self._api_response(9, 10)
        longer = data["duration"]["longer"]
        self.assertTrue(longer is None or isinstance(longer, int))


if __name__ == "__main__":
    unittest.main()
