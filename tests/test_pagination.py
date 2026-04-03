"""
Tests for pagination support across tools/timeline.py and tools/hermit_roster.py.

Covers:
  - The paginate() utility function in both tools (identical contract)
  - --limit / --offset CLI flags on timeline.py
  - --limit / --offset CLI flags on hermit_roster.py --all and --season modes
  - Acceptance criteria from issue #100:
      * limit default 20, max 100
      * response includes total, limit, offset
      * out-of-range offsets return empty items — not errors
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.timeline import paginate as timeline_paginate, main as timeline_main
from tools.hermit_roster import paginate as roster_paginate, main as roster_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_timeline(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = timeline_main(argv)
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 0
    return rc, out.getvalue(), err.getvalue()


def _run_roster(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = roster_main(argv)
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 0
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# paginate() — shared contract tested via both importers
# ---------------------------------------------------------------------------

class TestPaginateContract(unittest.TestCase):
    """Run identical assertions on both paginate() implementations."""

    def _fns(self):
        return [timeline_paginate, roster_paginate]

    def test_returns_dict(self):
        items = list(range(50))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                self.assertIsInstance(fn(items, 10, 0), dict)

    def test_envelope_keys(self):
        required = {"total", "limit", "offset", "items"}
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(list(range(30)), 10, 0)
                self.assertTrue(required.issubset(result.keys()))

    def test_total_is_full_length(self):
        items = list(range(50))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                self.assertEqual(fn(items, 10, 0)["total"], 50)

    def test_items_respects_limit(self):
        items = list(range(50))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                self.assertEqual(len(fn(items, 5, 0)["items"]), 5)

    def test_items_respects_offset(self):
        items = list(range(10))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, 3)
                self.assertEqual(result["items"], [3, 4, 5, 6, 7])

    def test_offset_beyond_total_returns_empty(self):
        items = list(range(10))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, 999)
                self.assertEqual(result["items"], [])

    def test_offset_beyond_total_is_not_error(self):
        items = list(range(5))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, 100)
                self.assertIsInstance(result, dict)
                self.assertEqual(result["total"], 5)

    def test_limit_capped_at_max(self):
        items = list(range(200))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 9999, 0)
                self.assertLessEqual(result["limit"], 100)
                self.assertLessEqual(len(result["items"]), 100)

    def test_limit_minimum_is_1(self):
        items = list(range(10))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 0, 0)
                self.assertGreaterEqual(result["limit"], 1)

    def test_negative_offset_treated_as_zero(self):
        items = list(range(10))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, -10)
                self.assertEqual(result["offset"], 0)
                self.assertEqual(result["items"], items[:5])

    def test_empty_items(self):
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn([], 10, 0)
                self.assertEqual(result["total"], 0)
                self.assertEqual(result["items"], [])

    def test_limit_and_offset_stored_in_envelope(self):
        items = list(range(50))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 7, 3)
                self.assertEqual(result["limit"], 7)
                self.assertEqual(result["offset"], 3)

    def test_last_page_has_fewer_items(self):
        items = list(range(12))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, 10)
                self.assertEqual(len(result["items"]), 2)  # only 2 left
                self.assertEqual(result["total"], 12)

    def test_exact_last_page(self):
        items = list(range(10))
        for fn in self._fns():
            with self.subTest(fn=fn.__module__):
                result = fn(items, 5, 5)
                self.assertEqual(len(result["items"]), 5)
                self.assertEqual(result["items"], [5, 6, 7, 8, 9])


# ---------------------------------------------------------------------------
# timeline.py -- --limit / --offset CLI flags
# ---------------------------------------------------------------------------

class TestTimelinePagination(unittest.TestCase):

    def test_limit_returns_envelope(self):
        rc, out, _ = _run_timeline(["--limit", "5"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("total", data)
        self.assertIn("limit", data)
        self.assertIn("offset", data)
        self.assertIn("items", data)

    def test_limit_restricts_items(self):
        _, out, _ = _run_timeline(["--limit", "3"])
        data = json.loads(out)
        self.assertLessEqual(len(data["items"]), 3)

    def test_offset_skips_items(self):
        _, out1, _ = _run_timeline(["--limit", "5", "--offset", "0"])
        _, out2, _ = _run_timeline(["--limit", "5", "--offset", "5"])
        data1 = json.loads(out1)
        data2 = json.loads(out2)
        # pages must not overlap
        ids1 = {e["id"] for e in data1["items"] if "id" in e}
        ids2 = {e["id"] for e in data2["items"] if "id" in e}
        self.assertEqual(ids1 & ids2, set())

    def test_offset_only_activates_envelope(self):
        rc, out, _ = _run_timeline(["--offset", "2"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("total", data)

    def test_out_of_range_offset_exit_0(self):
        rc, out, _ = _run_timeline(["--limit", "10", "--offset", "99999"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["items"], [])
        self.assertGreater(data["total"], 0)

    def test_total_is_correct(self):
        # total in paginated mode must equal total events in database
        _, out_all, _ = _run_timeline(["--pretty"])
        all_events = json.loads(out_all)
        _, out_page, _ = _run_timeline(["--limit", "1"])
        page = json.loads(out_page)
        self.assertEqual(page["total"], len(all_events))

    def test_limit_100_is_allowed(self):
        rc, _, _ = _run_timeline(["--limit", "100"])
        self.assertEqual(rc, 0)

    def test_limit_exceeding_max_is_capped(self):
        _, out, _ = _run_timeline(["--limit", "99999"])
        data = json.loads(out)
        self.assertLessEqual(data["limit"], 100)

    def test_pagination_with_season_filter(self):
        _, out, _ = _run_timeline(["--season", "9", "--limit", "3"])
        data = json.loads(out)
        self.assertIn("total", data)
        for item in data["items"]:
            self.assertEqual(item.get("season"), 9)

    def test_pagination_with_type_filter(self):
        _, out, _ = _run_timeline(["--type", "milestone", "--limit", "5"])
        data = json.loads(out)
        for item in data["items"]:
            self.assertEqual(item.get("type"), "milestone")

    def test_envelope_is_valid_json(self):
        _, out, _ = _run_timeline(["--limit", "10"])
        self.assertIsInstance(json.loads(out), dict)

    def test_no_pagination_flags_still_works(self):
        # without --limit/--offset, old NDJSON behaviour is preserved
        rc, out, _ = _run_timeline(["--season", "9"])
        self.assertEqual(rc, 0)
        # NDJSON: each line should be a valid JSON object
        for line in out.strip().splitlines():
            obj = json.loads(line)
            self.assertIsInstance(obj, dict)

    def test_combined_filters_and_pagination(self):
        _, out, _ = _run_timeline(
            ["--season", "9", "--type", "milestone", "--limit", "2"]
        )
        data = json.loads(out)
        self.assertIn("total", data)
        for item in data["items"]:
            self.assertEqual(item.get("season"), 9)
            self.assertEqual(item.get("type"), "milestone")


# ---------------------------------------------------------------------------
# hermit_roster.py -- --all mode pagination
# ---------------------------------------------------------------------------

class TestRosterAllPagination(unittest.TestCase):

    def test_limit_returns_envelope(self):
        rc, out, _ = _run_roster(["--all", "--json", "--limit", "5"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("total", data)
        self.assertIn("limit", data)
        self.assertIn("offset", data)
        self.assertIn("items", data)

    def test_limit_restricts_items(self):
        _, out, _ = _run_roster(["--all", "--json", "--limit", "3"])
        data = json.loads(out)
        self.assertLessEqual(len(data["items"]), 3)

    def test_total_reflects_full_roster(self):
        _, out_all, _ = _run_roster(["--all", "--json"])
        all_data = json.loads(out_all)
        _, out_page, _ = _run_roster(["--all", "--json", "--limit", "2"])
        page = json.loads(out_page)
        self.assertEqual(page["total"], all_data["hermit_count"])

    def test_offset_skips_hermits(self):
        _, out1, _ = _run_roster(["--all", "--json", "--limit", "5", "--offset", "0"])
        _, out2, _ = _run_roster(["--all", "--json", "--limit", "5", "--offset", "5"])
        names1 = {h["name"] for h in json.loads(out1)["items"]}
        names2 = {h["name"] for h in json.loads(out2)["items"]}
        self.assertEqual(names1 & names2, set())

    def test_out_of_range_offset_empty_items(self):
        rc, out, _ = _run_roster(["--all", "--json", "--limit", "5", "--offset", "9999"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["items"], [])

    def test_no_pagination_preserves_old_format(self):
        _, out, _ = _run_roster(["--all", "--json"])
        data = json.loads(out)
        self.assertIn("hermit_count", data)
        self.assertIn("hermits", data)

    def test_limit_without_json_still_exits_0(self):
        # text mode ignores pagination flags gracefully
        rc, _, _ = _run_roster(["--all", "--limit", "5"])
        self.assertEqual(rc, 0)

    def test_envelope_limit_stored(self):
        _, out, _ = _run_roster(["--all", "--json", "--limit", "7"])
        data = json.loads(out)
        self.assertEqual(data["limit"], 7)

    def test_envelope_offset_stored(self):
        _, out, _ = _run_roster(["--all", "--json", "--limit", "5", "--offset", "2"])
        data = json.loads(out)
        self.assertEqual(data["offset"], 2)


# ---------------------------------------------------------------------------
# hermit_roster.py -- --season mode pagination
# ---------------------------------------------------------------------------

class TestRosterSeasonPagination(unittest.TestCase):

    def test_season_limit_returns_envelope(self):
        rc, out, _ = _run_roster(["--season", "9", "--json", "--limit", "3"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("total", data)
        self.assertIn("items", data)

    def test_season_envelope_contains_season_key(self):
        _, out, _ = _run_roster(["--season", "9", "--json", "--limit", "3"])
        data = json.loads(out)
        self.assertEqual(data["season"], 9)

    def test_season_items_are_hermit_dicts(self):
        _, out, _ = _run_roster(["--season", "9", "--json", "--limit", "5"])
        data = json.loads(out)
        for item in data["items"]:
            self.assertIn("name", item)
            self.assertIn("seasons", item)

    def test_season_out_of_range_offset_empty(self):
        rc, out, _ = _run_roster(["--season", "9", "--json", "--limit", "5", "--offset", "9999"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["items"], [])

    def test_season_no_pagination_preserves_old_format(self):
        _, out, _ = _run_roster(["--season", "9", "--json"])
        data = json.loads(out)
        self.assertIn("season", data)
        self.assertIn("hermit_count", data)
        self.assertIn("hermits", data)


if __name__ == "__main__":
    unittest.main()
