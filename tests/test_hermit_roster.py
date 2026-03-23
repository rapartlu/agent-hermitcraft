"""
Tests for tools/hermit_roster.py
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.hermit_roster import (
    _normalise,
    _parse_frontmatter,
    _resolve_hermit,
    all_hermits,
    format_all_text,
    format_changes_text,
    format_season_text,
    format_timeline_text,
    hermit_timeline,
    hermits_for_season,
    load_roster,
    roster_changes,
    main,
)


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


def _make_hermit(name: str, seasons: list[int], **kwargs) -> dict:
    """Minimal synthetic hermit dict for unit tests."""
    h = {"name": name, "seasons": seasons, "status": "active"}
    h.update(kwargs)
    return h


def _make_roster(*specs) -> list[dict]:
    """Build a synthetic roster from (name, seasons) tuples."""
    return [_make_hermit(name, list(seasons)) for name, seasons in specs]


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

class TestNormalise(unittest.TestCase):

    def test_lowercases(self):
        self.assertEqual(_normalise("Grian"), "grian")

    def test_strips_spaces(self):
        self.assertEqual(_normalise("Mumbo Jumbo"), "mumbojumbo")

    def test_strips_hyphens(self):
        self.assertEqual(_normalise("mumbo-jumbo"), "mumbojumbo")

    def test_strips_underscores(self):
        self.assertEqual(_normalise("mumbo_jumbo"), "mumbojumbo")

    def test_empty_string(self):
        self.assertEqual(_normalise(""), "")


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):

    def _fm(self, body: str) -> dict:
        return _parse_frontmatter(f"---\n{body}\n---\n\n# Body")

    def test_name_parsed(self):
        self.assertEqual(self._fm("name: Grian")["name"], "Grian")

    def test_seasons_list_parsed(self):
        result = self._fm("seasons: [6, 7, 8]")
        self.assertEqual(result["seasons"], [6, 7, 8])

    def test_seasons_single_element(self):
        result = self._fm("seasons: [10]")
        self.assertEqual(result["seasons"], [10])

    def test_joined_season_coerced_to_int(self):
        result = self._fm("name: X\njoined_season: 6")
        self.assertEqual(result["joined_season"], 6)
        self.assertIsInstance(result["joined_season"], int)

    def test_status_parsed(self):
        self.assertEqual(self._fm("status: active")["status"], "active")

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter("# Just a heading"), {})

    def test_quoted_value_unquoted(self):
        result = self._fm('join_date: "2018-07-19"')
        self.assertEqual(result["join_date"], "2018-07-19")

    def test_missing_seasons_absent_from_result(self):
        result = self._fm("name: NoSeasons")
        self.assertNotIn("seasons", result)

    def test_real_grian_profile(self):
        path = Path(__file__).parent.parent / "knowledge" / "hermits" / "grian.md"
        if not path.exists():
            self.skipTest("grian.md not present")
        result = _parse_frontmatter(path.read_text(encoding="utf-8"))
        self.assertEqual(result["name"], "Grian")
        self.assertIn(6, result["seasons"])
        self.assertIsInstance(result["seasons"], list)


# ---------------------------------------------------------------------------
# load_roster
# ---------------------------------------------------------------------------

class TestLoadRoster(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(load_roster(), list)

    def test_nonempty(self):
        self.assertGreater(len(load_roster()), 0)

    def test_each_entry_has_name(self):
        for h in load_roster():
            self.assertIn("name", h)
            self.assertIsInstance(h["name"], str)

    def test_each_entry_has_seasons_list(self):
        for h in load_roster():
            self.assertIn("seasons", h)
            self.assertIsInstance(h["seasons"], list)

    def test_grian_present(self):
        names = [h["name"] for h in load_roster()]
        self.assertIn("Grian", names)

    def test_xisumavoid_present(self):
        names = [h["name"] for h in load_roster()]
        self.assertIn("Xisumavoid", names)

    def test_sorted_by_first_season(self):
        roster = load_roster()
        first_seasons = [min(h["seasons"]) if h["seasons"] else 999
                         for h in roster]
        self.assertEqual(first_seasons, sorted(first_seasons))

    def test_readme_not_included(self):
        names = [h["name"] for h in load_roster()]
        # README.md should be skipped — no name "README"
        self.assertNotIn("README", names)


# ---------------------------------------------------------------------------
# _resolve_hermit
# ---------------------------------------------------------------------------

class TestResolveHermit(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Grian", [6, 7, 8]),
            ("MumboJumbo", [2, 3, 4]),
            ("GoodTimesWithScar", [4, 5, 6]),
        )

    def test_exact_match(self):
        self.assertEqual(_resolve_hermit(self._roster(), "Grian")["name"], "Grian")

    def test_case_insensitive(self):
        self.assertEqual(_resolve_hermit(self._roster(), "grian")["name"], "Grian")

    def test_partial_match(self):
        result = _resolve_hermit(self._roster(), "mumbo")
        self.assertEqual(result["name"], "MumboJumbo")

    def test_substring_match(self):
        result = _resolve_hermit(self._roster(), "scar")
        self.assertEqual(result["name"], "GoodTimesWithScar")

    def test_no_match_returns_none(self):
        self.assertIsNone(_resolve_hermit(self._roster(), "zzznomatch"))

    def test_empty_roster_returns_none(self):
        self.assertIsNone(_resolve_hermit([], "Grian"))


# ---------------------------------------------------------------------------
# all_hermits
# ---------------------------------------------------------------------------

class TestAllHermits(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Alpha", [1, 2, 3]),
            ("Beta", [5]),
            ("Gamma", [1, 3, 5]),   # non-consecutive
        )

    def test_returns_list(self):
        self.assertIsInstance(all_hermits(self._roster()), list)

    def test_count_matches_roster(self):
        self.assertEqual(len(all_hermits(self._roster())), 3)

    def test_required_keys(self):
        for entry in all_hermits(self._roster()):
            for key in ("name", "seasons", "season_range", "status"):
                self.assertIn(key, entry)

    def test_consecutive_range_format(self):
        entries = all_hermits(self._roster())
        alpha = next(e for e in entries if e["name"] == "Alpha")
        self.assertEqual(alpha["season_range"], "S1–S3")

    def test_single_season_format(self):
        entries = all_hermits(self._roster())
        beta = next(e for e in entries if e["name"] == "Beta")
        self.assertEqual(beta["season_range"], "S5")

    def test_non_consecutive_lists_explicitly(self):
        entries = all_hermits(self._roster())
        gamma = next(e for e in entries if e["name"] == "Gamma")
        self.assertIn("S1", gamma["season_range"])
        self.assertIn("S3", gamma["season_range"])
        self.assertIn("S5", gamma["season_range"])

    def test_no_seasons_shows_unknown(self):
        roster = [_make_hermit("Ghost", [])]
        entries = all_hermits(roster)
        self.assertEqual(entries[0]["season_range"], "unknown")

    def test_real_grian_seasons(self):
        roster = load_roster()
        entries = all_hermits(roster)
        grian = next((e for e in entries if e["name"] == "Grian"), None)
        self.assertIsNotNone(grian)
        self.assertIn(6, grian["seasons"])


# ---------------------------------------------------------------------------
# hermits_for_season
# ---------------------------------------------------------------------------

class TestHermitsForSeason(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Alpha", [1, 2, 3]),
            ("Beta", [2, 3]),
            ("Gamma", [3]),
        )

    def test_returns_list(self):
        self.assertIsInstance(hermits_for_season(self._roster(), 2), list)

    def test_correct_hermits_returned(self):
        active = hermits_for_season(self._roster(), 2)
        names = [h["name"] for h in active]
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)
        self.assertNotIn("Gamma", names)

    def test_sorted_alphabetically(self):
        active = hermits_for_season(self._roster(), 3)
        names = [h["name"] for h in active]
        self.assertEqual(names, sorted(names))

    def test_empty_for_unknown_season(self):
        self.assertEqual(hermits_for_season(self._roster(), 99), [])

    def test_required_keys(self):
        for h in hermits_for_season(self._roster(), 2):
            for key in ("name", "seasons", "status"):
                self.assertIn(key, h)

    def test_real_season_9_has_grian(self):
        roster = load_roster()
        active = hermits_for_season(roster, 9)
        names = [h["name"] for h in active]
        self.assertIn("Grian", names)

    def test_real_season_9_count(self):
        # Season 9 had many hermits — at least 10 should be in profiles
        roster = load_roster()
        active = hermits_for_season(roster, 9)
        self.assertGreaterEqual(len(active), 10)


# ---------------------------------------------------------------------------
# hermit_timeline
# ---------------------------------------------------------------------------

class TestHermitTimeline(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Grian", [6, 7, 8, 9, 10, 11]),
            ("MumboJumbo", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]),
        )

    def test_returns_dict(self):
        self.assertIsInstance(hermit_timeline(self._roster(), "Grian"), dict)

    def test_none_for_unknown(self):
        self.assertIsNone(hermit_timeline(self._roster(), "zzznobody"))

    def test_required_keys(self):
        info = hermit_timeline(self._roster(), "Grian")
        for key in ("name", "seasons", "season_range", "status", "total_seasons"):
            self.assertIn(key, info)

    def test_name_resolved_correctly(self):
        info = hermit_timeline(self._roster(), "grian")
        self.assertEqual(info["name"], "Grian")

    def test_partial_name_match(self):
        info = hermit_timeline(self._roster(), "mumbo")
        self.assertEqual(info["name"], "MumboJumbo")

    def test_total_seasons_count(self):
        info = hermit_timeline(self._roster(), "Grian")
        self.assertEqual(info["total_seasons"], 6)

    def test_season_range_consecutive(self):
        info = hermit_timeline(self._roster(), "Grian")
        self.assertEqual(info["season_range"], "S6–S11")

    def test_real_xisumavoid_s1(self):
        roster = load_roster()
        info = hermit_timeline(roster, "Xisumavoid")
        self.assertIn(1, info["seasons"])


# ---------------------------------------------------------------------------
# roster_changes
# ---------------------------------------------------------------------------

class TestRosterChanges(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Alpha", [1, 2, 3]),
            ("Beta", [2, 3]),
            ("Gamma", [3]),
            ("Delta", [1]),        # left after S1
        )

    def test_returns_list(self):
        self.assertIsInstance(roster_changes(self._roster()), list)

    def test_season_1_all_joined(self):
        changes = roster_changes(self._roster())
        s1 = next(c for c in changes if c["season"] == 1)
        self.assertIn("Alpha", s1["joined"])
        self.assertIn("Delta", s1["joined"])
        self.assertEqual(s1["departed"], [])

    def test_delta_departed_after_s1(self):
        changes = roster_changes(self._roster())
        s2 = next((c for c in changes if c["season"] == 2), None)
        self.assertIsNotNone(s2)
        self.assertIn("Delta", s2["departed"])

    def test_beta_joined_s2(self):
        changes = roster_changes(self._roster())
        s2 = next((c for c in changes if c["season"] == 2), None)
        self.assertIsNotNone(s2)
        self.assertIn("Beta", s2["joined"])

    def test_required_keys(self):
        for entry in roster_changes(self._roster()):
            for key in ("season", "joined", "departed"):
                self.assertIn(key, entry)

    def test_joined_departed_are_lists(self):
        for entry in roster_changes(self._roster()):
            self.assertIsInstance(entry["joined"], list)
            self.assertIsInstance(entry["departed"], list)

    def test_sorted_by_season(self):
        changes = roster_changes(self._roster())
        seasons = [c["season"] for c in changes]
        self.assertEqual(seasons, sorted(seasons))

    def test_empty_roster_returns_empty(self):
        self.assertEqual(roster_changes([]), [])

    def test_real_grian_joined_s6(self):
        roster = load_roster()
        changes = roster_changes(roster)
        s6 = next((c for c in changes if c["season"] == 6), None)
        self.assertIsNotNone(s6)
        self.assertIn("Grian", s6["joined"])

    def test_real_s8_has_new_hermits(self):
        roster = load_roster()
        changes = roster_changes(roster)
        s8 = next((c for c in changes if c["season"] == 8), None)
        self.assertIsNotNone(s8)
        self.assertGreater(len(s8["joined"]), 0)


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

class TestFormatters(unittest.TestCase):

    def _roster(self):
        return _make_roster(
            ("Grian", [6, 7, 8]),
            ("Scar", [4, 5, 6]),
        )

    def test_format_all_returns_string(self):
        self.assertIsInstance(format_all_text(all_hermits(self._roster())), str)

    def test_format_all_contains_names(self):
        text = format_all_text(all_hermits(self._roster()))
        self.assertIn("Grian", text)
        self.assertIn("Scar", text)

    def test_format_all_empty_no_crash(self):
        result = format_all_text([])
        self.assertIsInstance(result, str)

    def test_format_season_returns_string(self):
        active = hermits_for_season(self._roster(), 6)
        self.assertIsInstance(format_season_text(6, active), str)

    def test_format_season_contains_season_number(self):
        active = hermits_for_season(self._roster(), 6)
        self.assertIn("6", format_season_text(6, active))

    def test_format_season_empty_no_crash(self):
        self.assertIsInstance(format_season_text(99, []), str)

    def test_format_timeline_returns_string(self):
        info = hermit_timeline(self._roster(), "Grian")
        self.assertIsInstance(format_timeline_text(info), str)

    def test_format_timeline_contains_name(self):
        info = hermit_timeline(self._roster(), "Grian")
        self.assertIn("Grian", format_timeline_text(info))

    def test_format_changes_returns_string(self):
        changes = roster_changes(self._roster())
        self.assertIsInstance(format_changes_text(changes), str)

    def test_format_changes_empty_no_crash(self):
        self.assertIsInstance(format_changes_text([]), str)

    def test_format_changes_contains_plus_joined(self):
        changes = roster_changes(self._roster())
        text = format_changes_text(changes)
        self.assertIn("+", text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    # --all -------------------------------------------------------------------

    def test_all_exits_0(self):
        rc, _, _ = _run(["--all"])
        self.assertEqual(rc, 0)

    def test_all_json_exits_0(self):
        rc, _, _ = _run(["--all", "--json"])
        self.assertEqual(rc, 0)

    def test_all_json_valid(self):
        _, out, _ = _run(["--all", "--json"])
        data = json.loads(out)
        self.assertIn("hermits", data)

    def test_all_json_hermit_count(self):
        _, out, _ = _run(["--all", "--json"])
        data = json.loads(out)
        self.assertGreater(data["hermit_count"], 0)

    def test_all_text_contains_grian(self):
        _, out, _ = _run(["--all"])
        self.assertIn("Grian", out)

    # --season ----------------------------------------------------------------

    def test_season_exits_0(self):
        rc, _, _ = _run(["--season", "9"])
        self.assertEqual(rc, 0)

    def test_season_json_valid(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        self.assertIn("hermits", data)

    def test_season_json_season_field(self):
        _, out, _ = _run(["--season", "7", "--json"])
        data = json.loads(out)
        self.assertEqual(data["season"], 7)

    def test_season_text_contains_hermit_names(self):
        _, out, _ = _run(["--season", "9"])
        self.assertIn("Grian", out)

    def test_season_unknown_returns_empty_not_error(self):
        # Unknown season: no profiles match, but tool exits 0 with empty result
        rc, out, _ = _run(["--season", "99"])
        self.assertEqual(rc, 0)

    # --hermit ----------------------------------------------------------------

    def test_hermit_exits_0(self):
        rc, _, _ = _run(["--hermit", "Grian"])
        self.assertEqual(rc, 0)

    def test_hermit_json_valid(self):
        _, out, _ = _run(["--hermit", "Grian", "--json"])
        data = json.loads(out)
        self.assertIn("seasons", data)

    def test_hermit_partial_name(self):
        rc, _, _ = _run(["--hermit", "grian"])
        self.assertEqual(rc, 0)

    def test_hermit_partial_lowercase(self):
        rc, out, _ = _run(["--hermit", "mumbo", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["name"], "MumboJumbo")

    def test_hermit_not_found_exits_1(self):
        rc, _, err = _run(["--hermit", "zzznobodymatchesthis"])
        self.assertEqual(rc, 1)
        self.assertIn("zzznobodymatchesthis", err)

    def test_hermit_json_has_required_keys(self):
        _, out, _ = _run(["--hermit", "Grian", "--json"])
        data = json.loads(out)
        for key in ("name", "seasons", "season_range", "total_seasons", "status"):
            self.assertIn(key, data)

    # --changes ---------------------------------------------------------------

    def test_changes_exits_0(self):
        rc, _, _ = _run(["--changes"])
        self.assertEqual(rc, 0)

    def test_changes_json_valid(self):
        _, out, _ = _run(["--changes", "--json"])
        data = json.loads(out)
        self.assertIn("changes", data)

    def test_changes_json_is_list(self):
        _, out, _ = _run(["--changes", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data["changes"], list)

    def test_changes_text_shows_joined(self):
        _, out, _ = _run(["--changes"])
        self.assertIn("Joined", out)

    def test_changes_grian_joins_s6(self):
        _, out, _ = _run(["--changes", "--json"])
        data = json.loads(out)
        s6 = next((c for c in data["changes"] if c["season"] == 6), None)
        self.assertIsNotNone(s6)
        self.assertIn("Grian", s6["joined"])

    # Mutual exclusion / error cases ------------------------------------------

    def test_no_mode_exits_nonzero(self):
        rc, _, _ = _run([])
        self.assertNotEqual(rc, 0)

    def test_two_modes_exits_nonzero(self):
        rc, _, _ = _run(["--all", "--season", "9"])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
