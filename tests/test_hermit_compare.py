"""
Tests for tools/hermit_compare.py
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.hermit_compare import (
    HERMITS_DIR,
    EVENTS_FILE,
    VIDEO_EVENTS_FILE,
    _normalise,
    _parse_frontmatter,
    _season_range,
    _seasons_label,
    find_hermit_file,
    load_profile,
    load_shared_events,
    build_comparison,
    format_comparison_text,
    main,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

GRIAN_FRONTMATTER = """\
---
name: Grian
joined_season: 6
status: active
specialties:
  - building
  - pranks
  - storytelling
seasons: [6, 7, 8, 9, 10, 11]
---

# Grian

## Overview

Grian is a builder.
"""

MUMBO_FRONTMATTER = """\
---
name: MumboJumbo
joined_season: 2
status: active
specialties:
  - redstone
  - automation
  - farms
seasons: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
---

# MumboJumbo

## Overview

MumboJumbo is a redstone engineer.
"""

ETHO_FRONTMATTER = """\
---
name: EthosLab
joined_season: 1
status: active
specialties:
  - technical
  - redstone
seasons: [1, 2, 3, 4, 5]
---

# EthosLab

## Overview

EthosLab is a technical player.
"""

SAMPLE_EVENTS = [
    {
        "id": "s7-001",
        "date": "2020-06-12",
        "season": 7,
        "hermits": ["Grian", "MumboJumbo", "Iskall85"],
        "type": "collab",
        "title": "Sahara Mega-Shop Opens",
        "description": "The Architechs open Sahara.",
    },
    {
        "id": "s9-001",
        "date": "2022-04-03",
        "season": 9,
        "hermits": ["Grian", "MumboJumbo", "GoodTimesWithScar"],
        "type": "collab",
        "title": "Boatem Pole Rises",
        "description": "The Boatem group assembles.",
    },
    {
        "id": "s9-002",
        "date": "2022-05-01",
        "season": 9,
        "hermits": ["Grian", "Iskall85"],
        "type": "collab",
        "title": "G-Team Prank",
        "description": "Grian and Iskall prank someone.",
    },
    {
        "id": "s1-001",
        "date": "2012-04-13",
        "season": 1,
        "hermits": ["All"],
        "type": "milestone",
        "title": "Hermitcraft Founded",
        "description": "Server starts.",
    },
]


def _make_profile(name: str, handle: str, joined: int, seasons: list, specialties: list) -> dict:
    return {
        "handle": handle,
        "name": name,
        "joined_season": joined,
        "specialties": specialties,
        "seasons": sorted(seasons),
        "status": "active",
    }


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------
class TestNormalise(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(_normalise("Grian"), "grian")

    def test_strip_hyphens(self):
        self.assertEqual(_normalise("mumbo-jumbo"), "mumbojumbo")

    def test_strip_spaces(self):
        self.assertEqual(_normalise("Mumbo Jumbo"), "mumbojumbo")

    def test_strip_underscores(self):
        self.assertEqual(_normalise("etho_lab"), "etholab")

    def test_empty_string(self):
        self.assertEqual(_normalise(""), "")

    def test_mixed(self):
        self.assertEqual(_normalise("Good Times With Scar"), "goodtimeswithscar")


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------
class TestParseFrontmatter(unittest.TestCase):
    def _make(self, block: str) -> str:
        return f"---\n{block}\n---\n\nbody"

    def test_scalar_string(self):
        fm = _parse_frontmatter(self._make("name: Grian"))
        self.assertEqual(fm["name"], "Grian")

    def test_integer_field(self):
        fm = _parse_frontmatter(self._make("joined_season: 6"))
        self.assertEqual(fm["joined_season"], 6)

    def test_inline_list(self):
        fm = _parse_frontmatter(self._make("seasons: [6, 7, 8]"))
        self.assertEqual(fm["seasons"], ["6", "7", "8"])

    def test_block_list(self):
        fm = _parse_frontmatter(self._make("specialties:\n  - building\n  - pranks"))
        self.assertEqual(fm["specialties"], ["building", "pranks"])

    def test_no_frontmatter(self):
        fm = _parse_frontmatter("Just some text")
        self.assertEqual(fm, {})

    def test_quoted_value(self):
        fm = _parse_frontmatter(self._make('join_date: "2018-07-19"'))
        self.assertEqual(fm["join_date"], "2018-07-19")


# ---------------------------------------------------------------------------
# _season_range
# ---------------------------------------------------------------------------
class TestSeasonRange(unittest.TestCase):
    def test_single_season(self):
        self.assertEqual(_season_range([6]), "S6")

    def test_consecutive_range(self):
        self.assertEqual(_season_range([6, 7, 8, 9, 10, 11]), "S6–S11")

    def test_non_consecutive(self):
        self.assertEqual(_season_range([1, 3, 5]), "S1, S3, S5")

    def test_empty(self):
        self.assertEqual(_season_range([]), "none")

    def test_two_consecutive(self):
        self.assertEqual(_season_range([5, 6]), "S5–S6")

    def test_two_non_consecutive(self):
        self.assertEqual(_season_range([3, 7]), "S3, S7")


# ---------------------------------------------------------------------------
# _seasons_label
# ---------------------------------------------------------------------------
class TestSeasonsLabel(unittest.TestCase):
    def test_plural(self):
        label = _seasons_label([6, 7, 8])
        self.assertIn("3 seasons", label)
        self.assertIn("S6", label)

    def test_singular(self):
        label = _seasons_label([6])
        self.assertIn("1 season", label)
        self.assertNotIn("1 seasons", label)

    def test_empty(self):
        self.assertEqual(_seasons_label([]), "none")


# ---------------------------------------------------------------------------
# load_shared_events
# ---------------------------------------------------------------------------
class TestLoadSharedEvents(unittest.TestCase):
    def _run(self, name_a: str, name_b: str, events: list) -> list:
        with patch("tools.hermit_compare._load_event_files", return_value=events):
            return load_shared_events(name_a, name_b)

    def test_returns_events_involving_both(self):
        evs = self._run("Grian", "MumboJumbo", SAMPLE_EVENTS)
        titles = [e["title"] for e in evs]
        self.assertIn("Sahara Mega-Shop Opens", titles)
        self.assertIn("Boatem Pole Rises", titles)

    def test_excludes_event_with_only_one_hermit(self):
        evs = self._run("Grian", "MumboJumbo", SAMPLE_EVENTS)
        titles = [e["title"] for e in evs]
        self.assertNotIn("G-Team Prank", titles)

    def test_excludes_all_hermits_events(self):
        evs = self._run("Grian", "MumboJumbo", SAMPLE_EVENTS)
        titles = [e["title"] for e in evs]
        self.assertNotIn("Hermitcraft Founded", titles)

    def test_case_insensitive_match(self):
        evs = self._run("grian", "mumbojumbo", SAMPLE_EVENTS)
        self.assertTrue(len(evs) >= 2)

    def test_no_shared_events_returns_empty(self):
        evs = self._run("EthosLab", "Keralis", SAMPLE_EVENTS)
        self.assertEqual(evs, [])

    def test_sorted_chronologically(self):
        evs = self._run("Grian", "MumboJumbo", SAMPLE_EVENTS)
        dates = [e["date"] for e in evs]
        self.assertEqual(dates, sorted(dates))

    def test_empty_event_list(self):
        evs = self._run("Grian", "MumboJumbo", [])
        self.assertEqual(evs, [])


# ---------------------------------------------------------------------------
# build_comparison
# ---------------------------------------------------------------------------
class TestBuildComparison(unittest.TestCase):
    def setUp(self):
        self.profile_a = _make_profile("Grian", "grian", 6, [6, 7, 8, 9, 10, 11], ["building", "pranks"])
        self.profile_b = _make_profile("MumboJumbo", "mumbo-jumbo", 2, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], ["redstone"])
        self.shared = [SAMPLE_EVENTS[0], SAMPLE_EVENTS[1]]

    def test_seasons_together_correct(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        self.assertEqual(sorted(cmp["seasons_together"]), [6, 7, 8, 9, 10, 11])

    def test_seasons_together_count(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        self.assertEqual(cmp["seasons_together_count"], 6)

    def test_shared_event_count(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        self.assertEqual(cmp["shared_event_count"], 2)

    def test_hermit_a_fields(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        self.assertEqual(cmp["hermit_a"]["name"], "Grian")
        self.assertEqual(cmp["hermit_a"]["first_joined"], "S6")
        self.assertIn("building", cmp["hermit_a"]["specialties"])

    def test_hermit_b_fields(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        self.assertEqual(cmp["hermit_b"]["name"], "MumboJumbo")
        self.assertEqual(cmp["hermit_b"]["first_joined"], "S2")

    def test_no_common_seasons(self):
        etho = _make_profile("EthosLab", "ethoslab", 1, [1, 2, 3, 4, 5], ["technical"])
        grian = _make_profile("Grian", "grian", 6, [6, 7, 8, 9, 10, 11], ["building"])
        cmp = build_comparison(etho, grian, [])
        self.assertEqual(cmp["seasons_together"], [])
        self.assertEqual(cmp["seasons_together_count"], 0)
        self.assertEqual(cmp["seasons_together_label"], "none")

    def test_seasons_together_label_range(self):
        cmp = build_comparison(self.profile_a, self.profile_b, self.shared)
        label = cmp["seasons_together_label"]
        self.assertIn("S6", label)


# ---------------------------------------------------------------------------
# format_comparison_text
# ---------------------------------------------------------------------------
class TestFormatComparisonText(unittest.TestCase):
    def setUp(self):
        profile_a = _make_profile("Grian", "grian", 6, [6, 7, 8, 9, 10, 11], ["building", "pranks"])
        profile_b = _make_profile("MumboJumbo", "mumbo-jumbo", 2, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], ["redstone"])
        self.cmp = build_comparison(profile_a, profile_b, [SAMPLE_EVENTS[0], SAMPLE_EVENTS[1]])

    def test_header_contains_both_names(self):
        text = format_comparison_text(self.cmp)
        self.assertIn("Grian", text)
        self.assertIn("MumboJumbo", text)

    def test_seasons_together_shown(self):
        text = format_comparison_text(self.cmp)
        self.assertIn("Seasons together", text)
        self.assertIn("S6", text)

    def test_first_joined_shown(self):
        text = format_comparison_text(self.cmp)
        self.assertIn("First joined", text)
        self.assertIn("S2", text)  # MumboJumbo

    def test_specialties_shown(self):
        text = format_comparison_text(self.cmp)
        self.assertIn("Specialties", text)
        self.assertIn("building", text)
        self.assertIn("redstone", text)

    def test_shared_events_shown(self):
        text = format_comparison_text(self.cmp)
        self.assertIn("Shared events", text)
        self.assertIn("Sahara Mega-Shop Opens", text)

    def test_no_shared_events(self):
        profile_a = _make_profile("EthosLab", "ethoslab", 1, [1, 2, 3], ["technical"])
        profile_b = _make_profile("Grian", "grian", 6, [6, 7, 8], ["building"])
        cmp = build_comparison(profile_a, profile_b, [])
        text = format_comparison_text(cmp)
        self.assertIn("0", text)


# ---------------------------------------------------------------------------
# find_hermit_file (integration — uses real knowledge base)
# ---------------------------------------------------------------------------
class TestFindHermitFile(unittest.TestCase):
    def test_exact_handle_grian(self):
        path = find_hermit_file("grian")
        self.assertIsNotNone(path)
        self.assertEqual(path.stem, "grian")

    def test_case_insensitive(self):
        path = find_hermit_file("GRIAN")
        self.assertIsNotNone(path)
        self.assertEqual(path.stem, "grian")

    def test_partial_name_mumbo(self):
        path = find_hermit_file("mumbo")
        self.assertIsNotNone(path)
        self.assertIn("mumbo", path.stem.lower())

    def test_nonexistent_returns_none(self):
        path = find_hermit_file("xyznotahermit99")
        self.assertIsNone(path)


# ---------------------------------------------------------------------------
# load_profile (integration — uses real knowledge base)
# ---------------------------------------------------------------------------
class TestLoadProfile(unittest.TestCase):
    def test_grian_seasons(self):
        path = find_hermit_file("grian")
        if path is None:
            self.skipTest("grian.md not found")
        profile = load_profile(path)
        self.assertIn(6, profile["seasons"])
        self.assertIn(11, profile["seasons"])

    def test_grian_specialties(self):
        path = find_hermit_file("grian")
        if path is None:
            self.skipTest("grian.md not found")
        profile = load_profile(path)
        self.assertIn("building", profile["specialties"])

    def test_mumbo_joined_season(self):
        path = find_hermit_file("mumbo")
        if path is None:
            self.skipTest("mumbo profile not found")
        profile = load_profile(path)
        self.assertEqual(profile["joined_season"], 2)


# ---------------------------------------------------------------------------
# main() CLI — integration tests
# ---------------------------------------------------------------------------
class TestMain(unittest.TestCase):
    def _run(self, args: list) -> tuple[str, int]:
        """Run main() and capture stdout; return (output, exit_code)."""
        import io
        buf = io.StringIO()
        exit_code = 0
        with patch("sys.stdout", buf):
            try:
                main(args)
            except SystemExit as e:
                exit_code = e.code or 0
        return buf.getvalue(), exit_code

    def _run_err(self, args: list) -> tuple[str, int]:
        """Run main() and capture stderr; return (stderr_output, exit_code)."""
        import io
        buf = io.StringIO()
        exit_code = 0
        with patch("sys.stderr", buf):
            try:
                main(args)
            except SystemExit as e:
                exit_code = e.code or 0
        return buf.getvalue(), exit_code

    def test_text_output_contains_names(self):
        out, code = self._run(["--hermit-a", "Grian", "--hermit-b", "MumboJumbo"])
        self.assertEqual(code, 0)
        self.assertIn("Grian", out)
        self.assertIn("MumboJumbo", out)

    def test_json_flag_produces_valid_json(self):
        out, code = self._run(["--hermit-a", "Grian", "--hermit-b", "MumboJumbo", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("hermit_a", data)
        self.assertIn("hermit_b", data)
        self.assertIn("seasons_together", data)

    def test_json_includes_shared_event_count(self):
        out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "MumboJumbo", "--json"])
        data = json.loads(out)
        self.assertIn("shared_event_count", data)
        self.assertIsInstance(data["shared_event_count"], int)

    def test_unknown_hermit_exits_nonzero(self):
        err, code = self._run_err(["--hermit-a", "xyzfake999", "--hermit-b", "Grian"])
        self.assertNotEqual(code, 0)
        self.assertIn("xyzfake999", err)

    def test_same_hermit_exits_nonzero(self):
        err, code = self._run_err(["--hermit-a", "Grian", "--hermit-b", "Grian"])
        self.assertNotEqual(code, 0)

    def test_partial_match_works(self):
        # "mumbo" should match MumboJumbo
        out, code = self._run(["--hermit-a", "grian", "--hermit-b", "mumbo"])
        self.assertEqual(code, 0)
        self.assertIn("Grian", out)

    def test_text_output_has_seasons_together(self):
        out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "MumboJumbo"])
        self.assertIn("Seasons together", out)

    def test_text_output_has_specialties(self):
        out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "MumboJumbo"])
        self.assertIn("Specialties", out)


if __name__ == "__main__":
    unittest.main()
