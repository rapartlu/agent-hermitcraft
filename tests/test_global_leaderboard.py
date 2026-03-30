"""
Tests for the --global-leaderboard feature in tools/collab_query.py.

Covers:
  - build_global_leaderboard() core logic
  - format_global_leaderboard() output formatting
  - CLI --global-leaderboard flag (text + JSON modes)
  - Composability with --season, --top, --json
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.collab_query import (
    build_global_leaderboard,
    format_global_leaderboard,
    main,
)


# ---------------------------------------------------------------------------
# build_global_leaderboard — unit tests
# ---------------------------------------------------------------------------

class TestBuildGlobalLeaderboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Build once; all tests share the result."""
        cls.leaderboard = build_global_leaderboard()

    def test_returns_list(self):
        self.assertIsInstance(self.leaderboard, list)

    def test_non_empty(self):
        self.assertGreater(len(self.leaderboard), 0)

    def test_each_entry_has_required_keys(self):
        for entry in self.leaderboard:
            for key in ("rank", "hermit", "total_events", "partner_count", "seasons"):
                self.assertIn(key, entry, f"Missing key '{key}' in {entry}")

    def test_ranks_are_sequential(self):
        ranks = [e["rank"] for e in self.leaderboard]
        self.assertEqual(ranks, list(range(1, len(self.leaderboard) + 1)))

    def test_sorted_by_total_events_descending(self):
        totals = [e["total_events"] for e in self.leaderboard]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_total_events_positive(self):
        for entry in self.leaderboard:
            self.assertGreater(entry["total_events"], 0,
                               f"{entry['hermit']} has 0 events but is in leaderboard")

    def test_partner_count_positive(self):
        for entry in self.leaderboard:
            self.assertGreater(entry["partner_count"], 0)

    def test_partner_count_lte_total_hermits(self):
        from tools.collab_query import _all_hermit_names
        n_hermits = len(_all_hermit_names())
        for entry in self.leaderboard:
            self.assertLessEqual(entry["partner_count"], n_hermits - 1)

    def test_seasons_is_sorted_list(self):
        for entry in self.leaderboard:
            seasons = entry["seasons"]
            self.assertIsInstance(seasons, list)
            self.assertEqual(seasons, sorted(seasons))

    def test_no_duplicate_hermits(self):
        names = [e["hermit"] for e in self.leaderboard]
        self.assertEqual(len(names), len(set(names)))

    def test_top_n_respected(self):
        top3 = build_global_leaderboard(top_n=3)
        self.assertLessEqual(len(top3), 3)

    def test_top_n_1(self):
        top1 = build_global_leaderboard(top_n=1)
        self.assertEqual(len(top1), 1)
        self.assertEqual(top1[0]["rank"], 1)

    def test_season_filter(self):
        result_s9 = build_global_leaderboard(season_filter=9)
        # All returned events should only be from season 9
        for entry in result_s9:
            seasons = entry["seasons"]
            for s in seasons:
                self.assertEqual(s, 9,
                                 f"{entry['hermit']} has season {s} with season_filter=9")

    def test_season_filter_result_smaller_than_all(self):
        all_result = build_global_leaderboard()
        s9_result = build_global_leaderboard(season_filter=9)
        # S9-filtered result should have ≤ total events per hermit
        all_map = {e["hermit"]: e["total_events"] for e in all_result}
        for entry in s9_result:
            if entry["hermit"] in all_map:
                self.assertLessEqual(
                    entry["total_events"], all_map[entry["hermit"]],
                    msg=f"{entry['hermit']} has MORE events in S9 than overall"
                )

    def test_first_place_has_most_events(self):
        lb = build_global_leaderboard()
        if len(lb) >= 2:
            self.assertGreaterEqual(lb[0]["total_events"], lb[1]["total_events"])


# ---------------------------------------------------------------------------
# format_global_leaderboard — output tests
# ---------------------------------------------------------------------------

class TestFormatGlobalLeaderboard(unittest.TestCase):
    def setUp(self):
        self.ranked = build_global_leaderboard(top_n=5)
        self.text = format_global_leaderboard(self.ranked)

    def test_returns_string(self):
        self.assertIsInstance(self.text, str)

    def test_non_empty(self):
        self.assertGreater(len(self.text), 50)

    def test_contains_header(self):
        self.assertIn("Most-connected Hermits", self.text)

    def test_contains_rank_numbers(self):
        self.assertIn("1.", self.text)

    def test_contains_collab_partners_label(self):
        self.assertIn("collab partners", self.text)

    def test_season_filter_in_header(self):
        text = format_global_leaderboard(self.ranked, season_filter=9)
        self.assertIn("Season 9", text)

    def test_empty_ranked_shows_no_data(self):
        text = format_global_leaderboard([])
        self.assertIn("no collaboration", text.lower())

    def test_all_hermits_appear(self):
        for entry in self.ranked:
            self.assertIn(entry["hermit"], self.text)

    def test_total_events_shown(self):
        # The first entry's count should appear somewhere in the output
        if self.ranked:
            count = str(self.ranked[0]["total_events"])
            self.assertIn(count, self.text)


# ---------------------------------------------------------------------------
# CLI — global-leaderboard flag
# ---------------------------------------------------------------------------

class TestGlobalLeaderboardCLI(unittest.TestCase):
    def test_global_leaderboard_flag_exits_0(self):
        rc = main(["--global-leaderboard"])
        self.assertEqual(rc, 0)

    def test_global_leaderboard_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--global-leaderboard", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["mode"], "global_leaderboard")
        self.assertIn("leaderboard", data)
        self.assertIn("top_n", data)
        self.assertIsInstance(data["leaderboard"], list)
        for entry in data["leaderboard"]:
            self.assertIn("rank", entry)
            self.assertIn("hermit", entry)
            self.assertIn("total_events", entry)
            self.assertIn("partner_count", entry)

    def test_global_leaderboard_top_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--global-leaderboard", "--top", "5", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertLessEqual(len(data["leaderboard"]), 5)
        self.assertEqual(data["top_n"], 5)

    def test_global_leaderboard_season_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--global-leaderboard", "--season", "9", "--json"])
        self.assertIn(rc, (0, 1))
        if rc == 0:
            data = json.loads(buf.getvalue())
            self.assertEqual(data.get("season_filter"), 9)
            for entry in data["leaderboard"]:
                for s in entry["seasons"]:
                    self.assertEqual(s, 9)

    def test_global_leaderboard_json_has_season_filter_key(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--global-leaderboard", "--season", "7", "--json"])
        data = json.loads(buf.getvalue())
        self.assertIn("season_filter", data)
        self.assertEqual(data["season_filter"], 7)

    def test_global_leaderboard_text_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--global-leaderboard"])
        self.assertEqual(rc, 0)
        output = buf.getvalue()
        self.assertIn("Most-connected Hermits", output)
        self.assertIn("collab partners", output)

    def test_global_leaderboard_no_hermit_a_required(self):
        """--global-leaderboard should not require --hermit-a."""
        rc = main(["--global-leaderboard", "--top", "3"])
        self.assertEqual(rc, 0)

    def test_hermit_a_still_works_with_top_collabs(self):
        """Existing --top-collabs mode should be unaffected."""
        rc = main(["--hermit-a", "Grian", "--top-collabs", "--top", "3"])
        self.assertEqual(rc, 0)

    def test_subprocess_global_leaderboard(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.collab_query",
             "--global-leaderboard", "--top", "5"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Most-connected Hermits", proc.stdout)

    def test_subprocess_global_leaderboard_json(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.collab_query",
             "--global-leaderboard", "--json", "--top", "3"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertIn("leaderboard", data)
        self.assertLessEqual(len(data["leaderboard"]), 3)


if __name__ == "__main__":
    unittest.main()
