"""
Tests for tools/hermit_profile.py
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.hermit_profile import (
    HERMITS_DIR,
    EVENTS_FILE,
    VIDEO_EVENTS_FILE,
    _normalise,
    _parse_frontmatter,
    _strip_frontmatter,
    _extract_section,
    _first_paragraph,
    _extract_build_bullets,
    list_hermits,
    find_hermit_file,
    load_profile,
    load_hermit_events,
    build_output,
    format_profile_text,
    main,
)


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------
class TestNormalise(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(_normalise("Grian"), "grian")

    def test_strips_hyphens(self):
        self.assertEqual(_normalise("mumbo-jumbo"), "mumbojumbo")

    def test_strips_spaces(self):
        self.assertEqual(_normalise("mumbo jumbo"), "mumbojumbo")

    def test_strips_underscores(self):
        self.assertEqual(_normalise("mumbo_jumbo"), "mumbojumbo")

    def test_empty(self):
        self.assertEqual(_normalise(""), "")


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------
class TestParseFrontmatter(unittest.TestCase):
    def _make(self, block: str) -> str:
        return f"---\n{block}\n---\n\nbody text"

    def test_simple_scalar(self):
        fm = _parse_frontmatter(self._make("name: Grian"))
        self.assertEqual(fm["name"], "Grian")

    def test_integer_field(self):
        fm = _parse_frontmatter(self._make("joined_season: 6"))
        self.assertEqual(fm["joined_season"], 6)

    def test_quoted_scalar(self):
        fm = _parse_frontmatter(self._make('join_date: "2018-07-19"'))
        self.assertEqual(fm["join_date"], "2018-07-19")

    def test_inline_list(self):
        fm = _parse_frontmatter(self._make("seasons: [6, 7, 8]"))
        self.assertEqual(fm["seasons"], ["6", "7", "8"])

    def test_block_list(self):
        fm = _parse_frontmatter(
            self._make("specialties:\n  - building\n  - pranks")
        )
        self.assertEqual(fm["specialties"], ["building", "pranks"])

    def test_inline_dict_list(self):
        fm = _parse_frontmatter(
            self._make(
                'subscriber_milestones:\n  - { date: "2019-03", count: "1M" }'
            )
        )
        self.assertIsInstance(fm["subscriber_milestones"], list)
        self.assertEqual(fm["subscriber_milestones"][0]["count"], "1M")

    def test_no_frontmatter_returns_empty(self):
        fm = _parse_frontmatter("just some text")
        self.assertEqual(fm, {})

    def test_missing_closing_fence_returns_empty(self):
        fm = _parse_frontmatter("---\nname: Grian\n")
        self.assertEqual(fm, {})


# ---------------------------------------------------------------------------
# _strip_frontmatter
# ---------------------------------------------------------------------------
class TestStripFrontmatter(unittest.TestCase):
    def test_strips_block(self):
        content = "---\nname: Grian\n---\n\n# Heading\nbody"
        body = _strip_frontmatter(content)
        self.assertNotIn("name:", body)
        self.assertIn("# Heading", body)

    def test_no_frontmatter_returns_content(self):
        content = "just text"
        self.assertEqual(_strip_frontmatter(content), content)


# ---------------------------------------------------------------------------
# _extract_section
# ---------------------------------------------------------------------------
class TestExtractSection(unittest.TestCase):
    BODY = "## Overview\nBio text here.\n\n## Notable Builds\nBuild list.\n\n## Teams\nTeam info."

    def test_extracts_first_section(self):
        result = _extract_section(self.BODY, "Overview")
        self.assertIn("Bio text", result)
        self.assertNotIn("Build list", result)

    def test_extracts_middle_section(self):
        result = _extract_section(self.BODY, "Notable Builds")
        self.assertIn("Build list", result)

    def test_missing_section_returns_empty(self):
        result = _extract_section(self.BODY, "NonExistent")
        self.assertEqual(result, "")

    def test_case_insensitive(self):
        result = _extract_section(self.BODY, "overview")
        self.assertIn("Bio text", result)


# ---------------------------------------------------------------------------
# _first_paragraph
# ---------------------------------------------------------------------------
class TestFirstParagraph(unittest.TestCase):
    def test_returns_first_paragraph(self):
        text = "First paragraph text.\n\nSecond paragraph."
        self.assertEqual(_first_paragraph(text), "First paragraph text.")

    def test_skips_headings(self):
        text = "# Heading\n\nActual paragraph."
        self.assertEqual(_first_paragraph(text), "Actual paragraph.")

    def test_strips_bold(self):
        text = "He is **famous** for builds."
        result = _first_paragraph(text)
        self.assertNotIn("**", result)
        self.assertIn("famous", result)

    def test_empty_returns_empty(self):
        self.assertEqual(_first_paragraph(""), "")


# ---------------------------------------------------------------------------
# _extract_build_bullets
# ---------------------------------------------------------------------------
class TestExtractBuildBullets(unittest.TestCase):
    RAW = (
        "- **Decked Out (Season 7):** A dungeon crawler game.\n"
        "- **Decked Out 2 (Season 9):** The sequel.\n"
        "Some non-bullet text.\n"
    )

    def test_extracts_two_bullets(self):
        results = _extract_build_bullets(self.RAW)
        self.assertEqual(len(results), 2)

    def test_title_parsed(self):
        results = _extract_build_bullets(self.RAW)
        self.assertIn("Decked Out (Season 7)", results[0]["title"])

    def test_description_parsed(self):
        results = _extract_build_bullets(self.RAW)
        self.assertIn("dungeon", results[0]["description"])

    def test_empty_returns_empty(self):
        self.assertEqual(_extract_build_bullets(""), [])


# ---------------------------------------------------------------------------
# list_hermits
# ---------------------------------------------------------------------------
class TestListHermits(unittest.TestCase):
    def test_returns_list(self):
        hermits = list_hermits()
        self.assertIsInstance(hermits, list)

    def test_each_has_handle_and_name(self):
        for h in list_hermits():
            self.assertIn("handle", h)
            self.assertIn("name", h)

    def test_grian_present(self):
        handles = [h["handle"] for h in list_hermits()]
        self.assertIn("grian", handles)

    def test_readme_excluded(self):
        handles = [h["handle"] for h in list_hermits()]
        self.assertNotIn("README", handles)

    def test_count_matches_files(self):
        expected = len([p for p in HERMITS_DIR.glob("*.md") if p.name != "README.md"])
        self.assertEqual(len(list_hermits()), expected)


# ---------------------------------------------------------------------------
# find_hermit_file
# ---------------------------------------------------------------------------
class TestFindHermitFile(unittest.TestCase):
    def test_exact_handle(self):
        path = find_hermit_file("grian")
        self.assertIsNotNone(path)
        self.assertEqual(path.stem, "grian")

    def test_case_insensitive(self):
        path = find_hermit_file("GRIAN")
        self.assertIsNotNone(path)

    def test_partial_handle(self):
        path = find_hermit_file("tango")
        self.assertIsNotNone(path)
        self.assertIn("tangotek", path.stem)

    def test_spaced_name(self):
        path = find_hermit_file("mumbo jumbo")
        self.assertIsNotNone(path)

    def test_hyphenated_handle(self):
        path = find_hermit_file("mumbo-jumbo")
        self.assertIsNotNone(path)

    def test_not_found_returns_none(self):
        path = find_hermit_file("nonexistent_xyz_999")
        self.assertIsNone(path)

    def test_tangotek_by_full_name(self):
        path = find_hermit_file("TangoTek")
        self.assertIsNotNone(path)


# ---------------------------------------------------------------------------
# load_profile
# ---------------------------------------------------------------------------
class TestLoadProfile(unittest.TestCase):
    def setUp(self):
        self.grian_path = find_hermit_file("grian")
        self.profile = load_profile(self.grian_path)

    def test_name_parsed(self):
        self.assertEqual(self.profile["name"], "Grian")

    def test_handle_is_stem(self):
        self.assertEqual(self.profile["handle"], "grian")

    def test_seasons_are_ints(self):
        for s in self.profile["seasons"]:
            self.assertIsInstance(s, int)

    def test_grian_in_season_6(self):
        self.assertIn(6, self.profile["seasons"])

    def test_specialties_list(self):
        self.assertIsInstance(self.profile["specialties"], list)
        self.assertGreater(len(self.profile["specialties"]), 0)

    def test_subscriber_milestones_list(self):
        self.assertIsInstance(self.profile["subscriber_milestones"], list)

    def test_milestone_has_date_and_count(self):
        for m in self.profile["subscriber_milestones"]:
            self.assertIn("date", m)
            self.assertIn("count", m)

    def test_bio_non_empty(self):
        self.assertGreater(len(self.profile["bio"]), 10)

    def test_status_active(self):
        self.assertEqual(self.profile["status"], "active")

    def test_joined_season_int(self):
        self.assertIsInstance(self.profile["joined_season"], int)


# ---------------------------------------------------------------------------
# load_hermit_events
# ---------------------------------------------------------------------------
class TestLoadHermitEvents(unittest.TestCase):
    def test_grian_has_events(self):
        events = load_hermit_events("Grian")
        self.assertGreater(len(events), 0)

    def test_all_events_involve_grian(self):
        events = load_hermit_events("Grian")
        for ev in events:
            hermits = [h.lower() for h in ev.get("hermits", [])]
            self.assertIn("grian", hermits)

    def test_season_filter_applied(self):
        events = load_hermit_events("Grian", season_filter=7)
        for ev in events:
            self.assertEqual(ev.get("season"), 7)

    def test_all_events_excluded(self):
        # Events with hermits == ["All"] should not appear
        events = load_hermit_events("Grian")
        for ev in events:
            self.assertNotEqual(ev.get("hermits"), ["All"])

    def test_case_insensitive(self):
        lower = load_hermit_events("grian")
        upper = load_hermit_events("GRIAN")
        self.assertEqual(len(lower), len(upper))

    def test_sorted_chronologically(self):
        events = load_hermit_events("Grian")
        dates = [ev.get("date", "") for ev in events]
        # All dates should be non-decreasing (as strings in YYYY format)
        for i in range(1, len(dates)):
            self.assertGreaterEqual(dates[i][:4], dates[i - 1][:4])

    def test_unknown_hermit_returns_empty(self):
        events = load_hermit_events("XyzNonExistentHermit999")
        self.assertEqual(events, [])

    def test_tangotek_decked_out(self):
        events = load_hermit_events("TangoTek")
        titles = [ev.get("title", "") for ev in events]
        self.assertTrue(any("Decked Out" in t for t in titles))


# ---------------------------------------------------------------------------
# build_output
# ---------------------------------------------------------------------------
class TestBuildOutput(unittest.TestCase):
    def setUp(self):
        path = find_hermit_file("grian")
        self.profile = load_profile(path)
        self.events = load_hermit_events("Grian")
        self.output = build_output(self.profile, self.events)

    def test_has_required_fields(self):
        for field in ("name", "handle", "seasons", "bio", "events", "event_count"):
            self.assertIn(field, self.output)

    def test_event_count_matches_events(self):
        self.assertEqual(self.output["event_count"], len(self.output["events"]))

    def test_season_filter_stored(self):
        out = build_output(self.profile, self.events, season_filter=7)
        self.assertEqual(out["season_filter"], 7)

    def test_no_season_filter_key_absent(self):
        out = build_output(self.profile, self.events)
        self.assertNotIn("season_filter", out)


# ---------------------------------------------------------------------------
# format_profile_text
# ---------------------------------------------------------------------------
class TestFormatProfileText(unittest.TestCase):
    def setUp(self):
        path = find_hermit_file("grian")
        profile = load_profile(path)
        events = load_hermit_events("Grian")
        self.output = build_output(profile, events)
        self.text = format_profile_text(self.output)

    def test_name_in_header(self):
        self.assertIn("Grian", self.text)

    def test_status_in_header(self):
        self.assertIn("ACTIVE", self.text)

    def test_seasons_shown(self):
        self.assertIn("6", self.text)

    def test_specialties_shown(self):
        self.assertIn("building", self.text)

    def test_bio_section_shown(self):
        self.assertIn("ABOUT", self.text)

    def test_milestones_section_shown(self):
        self.assertIn("SUBSCRIBER MILESTONES", self.text)

    def test_events_section_shown(self):
        self.assertIn("TIMELINE EVENTS", self.text)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_no_season_events_message(self):
        path = find_hermit_file("grian")
        profile = load_profile(path)
        # Season 1 — Grian wasn't in season 1
        events = load_hermit_events("Grian", season_filter=1)
        out = build_output(profile, events, season_filter=1)
        text = format_profile_text(out)
        self.assertIn("No recorded events", text)


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------
class TestDataIntegrity(unittest.TestCase):
    def test_hermits_dir_exists(self):
        self.assertTrue(HERMITS_DIR.exists())

    def test_events_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists())

    def test_video_events_file_exists(self):
        self.assertTrue(VIDEO_EVENTS_FILE.exists())

    def test_all_profiles_parseable(self):
        for path in HERMITS_DIR.glob("*.md"):
            if path.name == "README.md":
                continue
            try:
                load_profile(path)
            except Exception as e:
                self.fail(f"load_profile({path.name}) raised {e}")

    def test_all_profiles_have_seasons(self):
        for path in HERMITS_DIR.glob("*.md"):
            if path.name == "README.md":
                continue
            p = load_profile(path)
            self.assertIsInstance(p["seasons"], list, f"{path.name} missing seasons")

    def test_all_profiles_have_name(self):
        for path in HERMITS_DIR.glob("*.md"):
            if path.name == "README.md":
                continue
            p = load_profile(path)
            self.assertTrue(p["name"], f"{path.name} has empty name")

    def test_all_profiles_have_status(self):
        for path in HERMITS_DIR.glob("*.md"):
            if path.name == "README.md":
                continue
            p = load_profile(path)
            self.assertIn(p["status"], {"active", "inactive", "unknown"})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCLI(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        """Run main(args) and capture stdout/stderr."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_hermit_grian_exits_0(self):
        rc, _, _ = self._run(["--hermit", "Grian"])
        self.assertEqual(rc, 0)

    def test_hermit_grian_text_contains_name(self):
        _, out, _ = self._run(["--hermit", "Grian"])
        self.assertIn("Grian", out)

    def test_hermit_grian_json_valid(self):
        rc, out, _ = self._run(["--hermit", "Grian", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["name"], "Grian")

    def test_json_has_event_count(self):
        _, out, _ = self._run(["--hermit", "Grian", "--json"])
        data = json.loads(out)
        self.assertIn("event_count", data)
        self.assertGreater(data["event_count"], 0)

    def test_json_has_seasons(self):
        _, out, _ = self._run(["--hermit", "Grian", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data["seasons"], list)

    def test_season_filter_applied(self):
        _, out, _ = self._run(["--hermit", "TangoTek", "--season", "7", "--json"])
        data = json.loads(out)
        for ev in data["events"]:
            self.assertEqual(ev["season"], 7)

    def test_season_stored_in_json(self):
        _, out, _ = self._run(["--hermit", "Grian", "--season", "8", "--json"])
        data = json.loads(out)
        self.assertEqual(data.get("season_filter"), 8)

    def test_not_found_exits_1(self):
        rc, _, err = self._run(["--hermit", "xyz_nobody_999"])
        self.assertEqual(rc, 1)
        self.assertIn("No profile found", err)

    def test_list_exits_0(self):
        rc, _, _ = self._run(["--list"])
        self.assertEqual(rc, 0)

    def test_list_contains_grian(self):
        _, out, _ = self._run(["--list"])
        self.assertIn("grian", out)

    def test_list_json_returns_list(self):
        _, out, _ = self._run(["--list", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data, list)

    def test_list_json_has_handle_and_name(self):
        _, out, _ = self._run(["--list", "--json"])
        data = json.loads(out)
        for item in data:
            self.assertIn("handle", item)
            self.assertIn("name", item)

    def test_partial_name_match(self):
        rc, out, _ = self._run(["--hermit", "tango"])
        self.assertEqual(rc, 0)
        self.assertIn("TangoTek", out)

    def test_case_insensitive_match(self):
        rc, _, _ = self._run(["--hermit", "GRIAN"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
