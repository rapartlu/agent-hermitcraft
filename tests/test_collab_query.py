"""
Tests for tools/collab_query.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.collab_query import (
    EVENTS_FILE,
    VIDEO_EVENTS_FILE,
    HERMITS_DIR,
    _normalise,
    _resolve_hermit_name,
    _event_sort_key,
    find_shared_events,
    find_top_collaborators,
    build_output,
    format_text,
    format_top_collabs,
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
        self.assertEqual(_normalise("Mumbo Jumbo"), "mumbojumbo")

    def test_strips_underscores(self):
        self.assertEqual(_normalise("etho_slab"), "ethoslab")

    def test_empty_string(self):
        self.assertEqual(_normalise(""), "")


# ---------------------------------------------------------------------------
# _resolve_hermit_name
# ---------------------------------------------------------------------------
class TestResolveHermitName(unittest.TestCase):
    def test_exact_handle(self):
        name = _resolve_hermit_name("grian")
        self.assertEqual(name, "Grian")

    def test_case_insensitive(self):
        name = _resolve_hermit_name("GRIAN")
        self.assertEqual(name, "Grian")

    def test_partial_handle(self):
        name = _resolve_hermit_name("tango")
        self.assertIsNotNone(name)
        self.assertIn("Tango", name)

    def test_display_name_match(self):
        name = _resolve_hermit_name("MumboJumbo")
        self.assertIsNotNone(name)
        self.assertIn("Mumbo", name)

    def test_spaced_name(self):
        name = _resolve_hermit_name("mumbo jumbo")
        self.assertIsNotNone(name)

    def test_not_found_returns_none(self):
        name = _resolve_hermit_name("xyznonexistent999")
        self.assertIsNone(name)

    def test_bdoubleo_by_handle(self):
        name = _resolve_hermit_name("bdoubleo100")
        self.assertIsNotNone(name)

    def test_returns_string(self):
        name = _resolve_hermit_name("grian")
        self.assertIsInstance(name, str)


# ---------------------------------------------------------------------------
# _event_sort_key
# ---------------------------------------------------------------------------
class TestEventSortKey(unittest.TestCase):
    def test_full_date(self):
        ev = {"date": "2020-06-15"}
        self.assertEqual(_event_sort_key(ev), (2020, 6, 15))

    def test_year_month(self):
        ev = {"date": "2019-03"}
        self.assertEqual(_event_sort_key(ev), (2019, 3, 0))

    def test_year_only(self):
        ev = {"date": "2018"}
        self.assertEqual(_event_sort_key(ev), (2018, 0, 0))

    def test_no_date_returns_sentinel(self):
        ev = {}
        self.assertEqual(_event_sort_key(ev)[0], 9999)

    def test_sort_order(self):
        events = [
            {"date": "2021"},
            {"date": "2018"},
            {"date": "2020-06"},
        ]
        events.sort(key=_event_sort_key)
        years = [e["date"][:4] for e in events]
        self.assertEqual(years, ["2018", "2020", "2021"])


# ---------------------------------------------------------------------------
# find_shared_events
# ---------------------------------------------------------------------------
class TestFindSharedEvents(unittest.TestCase):
    def test_grian_mumbo_has_results(self):
        events = find_shared_events("Grian", "MumboJumbo")
        self.assertGreater(len(events), 0)

    def test_both_hermits_in_every_event(self):
        events = find_shared_events("Grian", "MumboJumbo")
        for ev in events:
            normed = [_normalise(h) for h in ev.get("hermits", [])]
            self.assertIn("grian", normed)
            self.assertIn("mumbojumbo", normed)

    def test_all_events_excluded(self):
        events = find_shared_events("Grian", "MumboJumbo")
        for ev in events:
            self.assertNotEqual(ev.get("hermits"), ["All"])

    def test_season_filter(self):
        events = find_shared_events("Grian", "MumboJumbo", season_filter=6)
        for ev in events:
            self.assertEqual(ev.get("season"), 6)

    def test_season_filter_reduces_results(self):
        all_events = find_shared_events("Grian", "MumboJumbo")
        s6_events = find_shared_events("Grian", "MumboJumbo", season_filter=6)
        self.assertLessEqual(len(s6_events), len(all_events))

    def test_type_filter(self):
        events = find_shared_events("Grian", "MumboJumbo", type_filter=["lore"])
        for ev in events:
            self.assertEqual(ev.get("type"), "lore")

    def test_unknown_hermit_returns_empty(self):
        events = find_shared_events("Grian", "XyzNobody999")
        self.assertEqual(events, [])

    def test_sorted_chronologically(self):
        events = find_shared_events("Grian", "MumboJumbo")
        keys = [_event_sort_key(e) for e in events]
        self.assertEqual(keys, sorted(keys))

    def test_same_hermit_returns_empty(self):
        # Grian × Grian should return no events (no event lists Grian twice)
        events = find_shared_events("Grian", "Grian")
        self.assertEqual(events, [])

    def test_tangotek_iskall_season7(self):
        events = find_shared_events("TangoTek", "Iskall85", season_filter=7)
        self.assertGreater(len(events), 0)

    def test_each_event_has_required_fields(self):
        events = find_shared_events("Grian", "MumboJumbo")
        for ev in events:
            self.assertIn("title", ev)
            self.assertIn("season", ev)
            self.assertIn("hermits", ev)


# ---------------------------------------------------------------------------
# build_output
# ---------------------------------------------------------------------------
class TestBuildOutput(unittest.TestCase):
    def setUp(self):
        self.events = find_shared_events("Grian", "MumboJumbo")
        self.output = build_output("Grian", "MumboJumbo", self.events)

    def test_hermit_names_present(self):
        self.assertEqual(self.output["hermit_a"], "Grian")
        self.assertEqual(self.output["hermit_b"], "MumboJumbo")

    def test_event_count_matches(self):
        self.assertEqual(self.output["event_count"], len(self.events))

    def test_seasons_with_collabs_is_sorted_list(self):
        seasons = self.output["seasons_with_collabs"]
        self.assertIsInstance(seasons, list)
        self.assertEqual(seasons, sorted(seasons))

    def test_events_list_present(self):
        self.assertIn("events", self.output)
        self.assertIsInstance(self.output["events"], list)

    def test_season_filter_stored(self):
        out = build_output("Grian", "MumboJumbo", self.events, season_filter=6)
        self.assertEqual(out["season_filter"], 6)

    def test_no_season_filter_key_absent(self):
        out = build_output("Grian", "MumboJumbo", self.events)
        self.assertNotIn("season_filter", out)

    def test_type_filter_stored(self):
        out = build_output("Grian", "MumboJumbo", self.events, type_filter=["lore"])
        self.assertEqual(out["type_filter"], ["lore"])

    def test_empty_events_gives_zero_count(self):
        out = build_output("Grian", "MumboJumbo", [])
        self.assertEqual(out["event_count"], 0)
        self.assertEqual(out["seasons_with_collabs"], [])


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------
class TestFormatText(unittest.TestCase):
    def setUp(self):
        events = find_shared_events("Grian", "MumboJumbo")
        self.output = build_output("Grian", "MumboJumbo", events)
        self.text = format_text(self.output)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_both_names_in_header(self):
        self.assertIn("Grian", self.text)
        self.assertIn("Mumbo", self.text)

    def test_event_count_shown(self):
        count = str(self.output["event_count"])
        self.assertIn(count, self.text)

    def test_season_headers_present(self):
        for s in self.output["seasons_with_collabs"]:
            self.assertIn(f"Season {s}", self.text)

    def test_empty_results_shows_no_events_message(self):
        out = build_output("Grian", "MumboJumbo", [], season_filter=1)
        text = format_text(out)
        self.assertIn("No shared events", text)

    def test_season_filter_label_shown(self):
        events = find_shared_events("Grian", "MumboJumbo", season_filter=6)
        out = build_output("Grian", "MumboJumbo", events, season_filter=6)
        text = format_text(out)
        self.assertIn("Season 6", text)

    def test_type_filter_label_shown(self):
        events = find_shared_events("Grian", "MumboJumbo", type_filter=["lore"])
        out = build_output("Grian", "MumboJumbo", events, type_filter=["lore"])
        text = format_text(out)
        self.assertIn("lore", text)


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------
class TestDataIntegrity(unittest.TestCase):
    def test_events_file_exists(self):
        self.assertTrue(EVENTS_FILE.exists())

    def test_video_events_file_exists(self):
        self.assertTrue(VIDEO_EVENTS_FILE.exists())

    def test_hermits_dir_exists(self):
        self.assertTrue(HERMITS_DIR.exists())

    def test_multi_hermit_events_exist(self):
        events = find_shared_events("Grian", "GoodTimesWithScar")
        self.assertGreater(len(events), 0)

    def test_events_json_parseable(self):
        data = json.loads(EVENTS_FILE.read_text())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


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
        rc, _, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "Mumbo"])
        self.assertEqual(rc, 0)

    def test_output_contains_both_names(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "Mumbo"])
        self.assertIn("Grian", out)
        self.assertIn("Mumbo", out)

    def test_json_output_valid(self):
        rc, out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "Mumbo", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("hermit_a", data)
        self.assertIn("hermit_b", data)
        self.assertIn("events", data)
        self.assertIn("event_count", data)

    def test_json_event_count_positive(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--hermit-b", "Mumbo", "--json"])
        data = json.loads(out)
        self.assertGreater(data["event_count"], 0)

    def test_season_flag(self):
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--hermit-b", "Mumbo", "--season", "6", "--json"]
        )
        data = json.loads(out)
        self.assertEqual(data.get("season_filter"), 6)
        for ev in data["events"]:
            self.assertEqual(ev["season"], 6)

    def test_types_flag(self):
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--hermit-b", "Mumbo", "--types", "lore", "--json"]
        )
        data = json.loads(out)
        for ev in data["events"]:
            self.assertEqual(ev["type"], "lore")

    def test_not_found_hermit_a_exits_1(self):
        rc, _, err = self._run(["--hermit-a", "xyz999", "--hermit-b", "Grian"])
        self.assertEqual(rc, 1)
        self.assertIn("No profile found", err)

    def test_not_found_hermit_b_exits_1(self):
        rc, _, err = self._run(["--hermit-a", "Grian", "--hermit-b", "xyz999"])
        self.assertEqual(rc, 1)
        self.assertIn("No profile found", err)

    def test_same_hermit_exits_1(self):
        rc, _, err = self._run(["--hermit-a", "Grian", "--hermit-b", "Grian"])
        self.assertEqual(rc, 1)
        self.assertIn("same Hermit", err)

    def test_case_insensitive_matching(self):
        rc, _, _ = self._run(["--hermit-a", "grian", "--hermit-b", "MUMBO"])
        self.assertEqual(rc, 0)

    def test_partial_name_matching(self):
        rc, _, _ = self._run(["--hermit-a", "tango", "--hermit-b", "iskall"])
        self.assertEqual(rc, 0)

    def test_no_results_text_message(self):
        # Season 1 — Grian wasn't in season 1, so no collabs
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--hermit-b", "Mumbo", "--season", "1"]
        )
        self.assertIn("No shared events", out)

    def test_etho_bdubs_has_events(self):
        rc, out, _ = self._run(
            ["--hermit-a", "EthosLab", "--hermit-b", "BdoubleO100", "--json"]
        )
        data = json.loads(out)
        self.assertGreater(data["event_count"], 0)


# ---------------------------------------------------------------------------
# find_top_collaborators
# ---------------------------------------------------------------------------
class TestFindTopCollaborators(unittest.TestCase):
    def test_returns_list(self):
        result = find_top_collaborators("Grian")
        self.assertIsInstance(result, list)

    def test_grian_has_results(self):
        result = find_top_collaborators("Grian")
        self.assertGreater(len(result), 0)

    def test_each_entry_has_required_keys(self):
        for entry in find_top_collaborators("Grian"):
            self.assertIn("rank", entry)
            self.assertIn("hermit", entry)
            self.assertIn("event_count", entry)
            self.assertIn("seasons", entry)

    def test_sorted_descending_by_count(self):
        result = find_top_collaborators("Grian")
        counts = [e["event_count"] for e in result]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_ranks_are_sequential_from_1(self):
        result = find_top_collaborators("Grian", top_n=5)
        ranks = [e["rank"] for e in result]
        self.assertEqual(ranks, list(range(1, len(result) + 1)))

    def test_target_hermit_not_in_results(self):
        result = find_top_collaborators("Grian")
        names = [_normalise(e["hermit"]) for e in result]
        self.assertNotIn("grian", names)

    def test_top_n_limits_results(self):
        result = find_top_collaborators("Grian", top_n=3)
        self.assertLessEqual(len(result), 3)

    def test_top_n_1_returns_at_most_1(self):
        result = find_top_collaborators("Grian", top_n=1)
        self.assertEqual(len(result), 1)

    def test_season_filter_applied(self):
        result = find_top_collaborators("Grian", season_filter=7)
        for entry in result:
            self.assertIn(7, entry["seasons"])

    def test_season_filter_reduces_results(self):
        all_result = find_top_collaborators("Grian")
        s7_result = find_top_collaborators("Grian", season_filter=7)
        # Season-filtered can only have <= partners than all-seasons
        all_total = sum(e["event_count"] for e in all_result)
        s7_total = sum(e["event_count"] for e in s7_result)
        self.assertLessEqual(s7_total, all_total)

    def test_type_filter_applied(self):
        result = find_top_collaborators("Grian", type_filter=["lore"])
        # If any events come back, they must be lore
        # (We can't easily assert count without loading events ourselves,
        #  but we can verify the function runs without error and returns a list.)
        self.assertIsInstance(result, list)

    def test_seasons_list_is_sorted(self):
        for entry in find_top_collaborators("Grian"):
            seasons = entry["seasons"]
            self.assertEqual(seasons, sorted(seasons))

    def test_event_count_matches_find_shared_events(self):
        result = find_top_collaborators("Grian", top_n=3)
        for entry in result:
            expected = len(find_shared_events("Grian", entry["hermit"]))
            self.assertEqual(entry["event_count"], expected)

    def test_nonexistent_hermit_returns_empty(self):
        result = find_top_collaborators("xyzNobody999")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# format_top_collabs
# ---------------------------------------------------------------------------
class TestFormatTopCollabs(unittest.TestCase):
    def setUp(self):
        self.ranked = find_top_collaborators("Grian", top_n=5)
        self.text = format_top_collabs("Grian", self.ranked)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_contains_hermit_name(self):
        self.assertIn("Grian", self.text)

    def test_contains_top_collaborator(self):
        if self.ranked:
            top_name = self.ranked[0]["hermit"]
            self.assertIn(top_name, self.text)

    def test_season_label_all_seasons(self):
        self.assertIn("all seasons", self.text)

    def test_season_label_specific_season(self):
        ranked = find_top_collaborators("Grian", season_filter=7, top_n=3)
        text = format_top_collabs("Grian", ranked, season_filter=7)
        self.assertIn("Season 7", text)

    def test_empty_ranked_shows_no_events_message(self):
        text = format_top_collabs("Grian", [])
        self.assertIn("no shared events", text.lower())

    def test_rank_numbers_shown(self):
        for entry in self.ranked:
            self.assertIn(str(entry["rank"]), self.text)


# ---------------------------------------------------------------------------
# CLI — top-collabs mode
# ---------------------------------------------------------------------------
class TestCLITopCollabs(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(args)
        return rc, out.getvalue(), err.getvalue()

    def test_top_collabs_exits_0(self):
        rc, _, _ = self._run(["--hermit-a", "Grian", "--top-collabs"])
        self.assertEqual(rc, 0)

    def test_top_collabs_no_hermit_b_required(self):
        # Must not error because --hermit-b is absent
        rc, _, err = self._run(["--hermit-a", "Grian", "--top-collabs"])
        self.assertEqual(rc, 0)
        self.assertNotIn("required", err)

    def test_top_collabs_output_contains_hermit_a(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs"])
        self.assertIn("Grian", out)

    def test_top_collabs_output_contains_collaborator(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs"])
        # At least one known collaborator should appear
        self.assertIn("Mumbo", out)

    def test_top_collabs_json_valid(self):
        rc, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("leaderboard", data)
        self.assertIn("hermit", data)

    def test_top_collabs_json_leaderboard_is_list(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data["leaderboard"], list)

    def test_top_collabs_json_leaderboard_nonempty(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs", "--json"])
        data = json.loads(out)
        self.assertGreater(len(data["leaderboard"]), 0)

    def test_top_collabs_json_leaderboard_entry_keys(self):
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs", "--json"])
        data = json.loads(out)
        first = data["leaderboard"][0]
        for key in ("rank", "hermit", "event_count", "seasons"):
            self.assertIn(key, first)

    def test_top_flag_limits_results(self):
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--top-collabs", "--top", "3", "--json"]
        )
        data = json.loads(out)
        self.assertLessEqual(len(data["leaderboard"]), 3)

    def test_top_flag_default_is_10(self):
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--top-collabs", "--json"]
        )
        data = json.loads(out)
        self.assertLessEqual(len(data["leaderboard"]), 10)

    def test_season_filter_composable(self):
        _, out, _ = self._run(
            ["--hermit-a", "Grian", "--top-collabs", "--season", "7", "--json"]
        )
        data = json.loads(out)
        self.assertEqual(data.get("season_filter"), 7)
        for entry in data["leaderboard"]:
            self.assertIn(7, entry["seasons"])

    def test_json_season_filter_absent_when_not_set(self):
        # Consistent with pairwise mode: omit key when no filter applied
        _, out, _ = self._run(["--hermit-a", "Grian", "--top-collabs", "--json"])
        data = json.loads(out)
        self.assertNotIn("season_filter", data)

    def test_types_flag_forwarded(self):
        # Should not error; result may be empty but must exit 0
        rc, out, _ = self._run(
            ["--hermit-a", "Grian", "--top-collabs", "--types", "lore", "--json"]
        )
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("leaderboard", data)
        self.assertEqual(data.get("type_filter"), ["lore"])

    def test_not_found_hermit_a_exits_1(self):
        rc, _, err = self._run(["--hermit-a", "xyz999", "--top-collabs"])
        self.assertEqual(rc, 1)
        self.assertIn("No profile found", err)

    def test_case_insensitive_hermit_a(self):
        rc, _, _ = self._run(["--hermit-a", "grian", "--top-collabs"])
        self.assertEqual(rc, 0)

    def test_partial_name_hermit_a(self):
        rc, _, _ = self._run(["--hermit-a", "tango", "--top-collabs"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
