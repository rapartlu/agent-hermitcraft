"""
Tests for tools/season_vs.py
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.season_vs import (
    KNOWN_SEASONS,
    _significance_score,
    _dim_winner,
    _event_count,
    _member_count,
    _build_count,
    _collab_count,
    _highlight_score,
    build_vs,
    render_text,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 0
    return rc, out.getvalue(), err.getvalue()


def _make_event(**kw) -> dict:
    base = {
        "season": 9,
        "type": "milestone",
        "title": "Test",
        "description": "",
        "date": "2022-01-01",
        "date_precision": "month",
        "hermits": ["Grian"],
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# _significance_score
# ---------------------------------------------------------------------------

class TestSignificanceScore(unittest.TestCase):

    def test_milestone_score(self):
        self.assertEqual(_significance_score(_make_event(type="milestone")), 10)

    def test_meta_score(self):
        self.assertEqual(_significance_score(_make_event(type="meta")), 1)

    def test_all_hermits_bonus(self):
        self.assertEqual(_significance_score(_make_event(type="milestone", hermits=["All"])), 13)

    def test_pair_bonus(self):
        self.assertEqual(_significance_score(_make_event(type="build", hermits=["A", "B"])), 6)

    def test_day_bonus(self):
        self.assertEqual(_significance_score(
            _make_event(type="build", hermits=["A"], date_precision="day")), 6)

    def test_unknown_type_zero(self):
        self.assertEqual(_significance_score(_make_event(type="xyzunknown")), 0)


# ---------------------------------------------------------------------------
# _dim_winner
# ---------------------------------------------------------------------------

class TestDimWinner(unittest.TestCase):

    def test_a_wins(self):
        self.assertEqual(_dim_winner(10, 5), "a")

    def test_b_wins(self):
        self.assertEqual(_dim_winner(3, 7), "b")

    def test_tie(self):
        self.assertEqual(_dim_winner(5, 5), "tie")

    def test_zeros_tie(self):
        self.assertEqual(_dim_winner(0, 0), "tie")


# ---------------------------------------------------------------------------
# Dimension extractors
# ---------------------------------------------------------------------------

class TestEventCount(unittest.TestCase):

    def test_empty_is_zero(self):
        self.assertEqual(_event_count([]), 0)

    def test_counts_all(self):
        events = [_make_event(), _make_event(), _make_event()]
        self.assertEqual(_event_count(events), 3)


class TestMemberCount(unittest.TestCase):

    def _events(self):
        return [
            _make_event(hermits=["Grian", "Scar"]),
            _make_event(hermits=["Mumbo"]),
            _make_event(hermits=["All"]),
        ]

    def test_excludes_all(self):
        result = _member_count(self._events())
        self.assertEqual(result, 3)  # Grian, Scar, Mumbo

    def test_deduplicates(self):
        events = [_make_event(hermits=["Grian"]), _make_event(hermits=["Grian"])]
        self.assertEqual(_member_count(events), 1)

    def test_empty_is_zero(self):
        self.assertEqual(_member_count([]), 0)


class TestBuildCount(unittest.TestCase):

    def _events(self):
        return [
            _make_event(type="build"),
            _make_event(type="build"),
            _make_event(type="milestone"),
        ]

    def test_counts_build_events(self):
        self.assertEqual(_build_count(self._events(), []), 2)

    def test_adds_major_builds(self):
        self.assertEqual(_build_count(self._events(), ["Build A", "Build B"]), 4)

    def test_empty_is_zero(self):
        self.assertEqual(_build_count([], []), 0)

    def test_non_build_types_excluded(self):
        events = [_make_event(type="milestone"), _make_event(type="lore")]
        self.assertEqual(_build_count(events, []), 0)


class TestCollabCount(unittest.TestCase):

    def _events(self):
        return [
            _make_event(hermits=["Grian", "Scar"]),       # collab
            _make_event(hermits=["Grian", "Scar", "Mumbo"]),  # collab
            _make_event(hermits=["Solo"]),                  # not collab
            _make_event(hermits=["All"]),                   # not collab (All)
        ]

    def test_counts_two_or_more(self):
        self.assertEqual(_collab_count(self._events()), 2)

    def test_all_excluded(self):
        events = [_make_event(hermits=["All"])]
        self.assertEqual(_collab_count(events), 0)

    def test_solo_excluded(self):
        events = [_make_event(hermits=["Grian"])]
        self.assertEqual(_collab_count(events), 0)

    def test_empty_is_zero(self):
        self.assertEqual(_collab_count([]), 0)


class TestHighlightScore(unittest.TestCase):

    def _events(self):
        return [
            _make_event(type="milestone", hermits=["All"]),   # score 13
            _make_event(type="lore", hermits=["Grian"]),       # score 8
            _make_event(type="meta", hermits=["Grian"]),       # score 1
        ]

    def test_sum_of_top_n(self):
        # top 2: 13 + 8 = 21
        self.assertEqual(_highlight_score(self._events(), top_n=2), 21)

    def test_all_events(self):
        # all 3: 13 + 8 + 1 = 22
        self.assertEqual(_highlight_score(self._events(), top_n=3), 22)

    def test_empty_is_zero(self):
        self.assertEqual(_highlight_score([]), 0)

    def test_top_n_caps(self):
        events = [_make_event(type="milestone", hermits=["All"])] * 10
        # only top 5 counted: 13 * 5 = 65
        self.assertEqual(_highlight_score(events, top_n=5), 65)


# ---------------------------------------------------------------------------
# build_vs
# ---------------------------------------------------------------------------

class TestBuildVs(unittest.TestCase):

    def _result(self, a=9, b=10):
        return build_vs(a, b)

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_top_level_keys(self):
        required = {"season_a", "season_b", "comparison", "winner",
                    "winner_season", "rationale", "metadata"}
        self.assertTrue(required.issubset(self._result().keys()))

    def test_season_a_correct(self):
        self.assertEqual(self._result()["season_a"], 9)

    def test_season_b_correct(self):
        self.assertEqual(self._result()["season_b"], 10)

    def test_comparison_has_all_dimensions(self):
        dims = self._result()["comparison"]
        for key in ("event_count", "member_count", "build_count",
                    "collab_count", "highlight_score"):
            self.assertIn(key, dims)

    def test_each_dimension_has_a_b_winner(self):
        for dim, d in self._result()["comparison"].items():
            self.assertIn("a", d, f"dim {dim} missing 'a'")
            self.assertIn("b", d, f"dim {dim} missing 'b'")
            self.assertIn("winner", d, f"dim {dim} missing 'winner'")

    def test_dimension_winner_valid(self):
        for dim, d in self._result()["comparison"].items():
            self.assertIn(d["winner"], ("a", "b", "tie"))

    def test_overall_winner_valid(self):
        self.assertIn(self._result()["winner"], ("a", "b", "tie"))

    def test_winner_season_is_int_or_none(self):
        ws = self._result()["winner_season"]
        self.assertTrue(ws is None or isinstance(ws, int))

    def test_winner_season_matches_winner(self):
        r = self._result()
        if r["winner"] == "a":
            self.assertEqual(r["winner_season"], 9)
        elif r["winner"] == "b":
            self.assertEqual(r["winner_season"], 10)
        else:
            self.assertIsNone(r["winner_season"])

    def test_rationale_is_string(self):
        self.assertIsInstance(self._result()["rationale"], str)

    def test_rationale_nonempty(self):
        self.assertGreater(len(self._result()["rationale"]), 0)

    def test_metadata_has_a_and_b(self):
        meta = self._result()["metadata"]
        self.assertIn("a", meta)
        self.assertIn("b", meta)

    def test_metadata_has_season_key(self):
        meta = self._result()["metadata"]
        self.assertEqual(meta["a"]["season"], 9)
        self.assertEqual(meta["b"]["season"], 10)

    def test_json_serialisable(self):
        self.assertIsInstance(json.dumps(self._result()), str)

    def test_all_season_pairs_no_crash(self):
        # Test a variety of pairs without full cross-product
        pairs = [(1, 2), (7, 9), (9, 11), (5, 10), (3, 8)]
        for a, b in pairs:
            try:
                result = build_vs(a, b)
            except Exception as e:
                self.fail(f"build_vs({a}, {b}) raised {e}")
            self.assertIn("winner", result)

    def test_symmetric_winner_flips(self):
        """build_vs(9, 10) winner='a' ↔ build_vs(10, 9) winner='b'."""
        r1 = build_vs(9, 10)
        r2 = build_vs(10, 9)
        if r1["winner"] == "a":
            self.assertEqual(r2["winner"], "b")
        elif r1["winner"] == "b":
            self.assertEqual(r2["winner"], "a")
        else:
            self.assertEqual(r2["winner"], "tie")

    def test_dimension_values_are_ints(self):
        for dim, d in self._result()["comparison"].items():
            self.assertIsInstance(d["a"], int, f"dim {dim}['a'] not int")
            self.assertIsInstance(d["b"], int, f"dim {dim}['b'] not int")

    def test_sparse_season_no_crash(self):
        result = build_vs(1, 2)
        self.assertIn("winner", result)

    def test_rationale_contains_season_number(self):
        r = self._result()
        rationale = r["rationale"]
        # Should mention at least one season number
        self.assertTrue(
            "9" in rationale or "10" in rationale or "tie" in rationale.lower()
        )


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------

class TestRenderText(unittest.TestCase):

    def _result(self):
        return build_vs(9, 10)

    def test_returns_string(self):
        self.assertIsInstance(render_text(self._result()), str)

    def test_contains_season_numbers(self):
        text = render_text(self._result())
        self.assertIn("9", text)
        self.assertIn("10", text)

    def test_contains_result_line(self):
        text = render_text(self._result())
        self.assertIn("RESULT", text)

    def test_contains_dimension_labels(self):
        text = render_text(self._result())
        self.assertIn("Timeline events", text)
        self.assertIn("Active hermits", text)

    def test_contains_rationale(self):
        r = self._result()
        text = render_text(r)
        # rationale is included verbatim
        self.assertIn(r["rationale"], text)

    def test_tie_shows_tie(self):
        r = build_vs(9, 10)
        r["winner"] = "tie"
        r["winner_season"] = None
        text = render_text(r)
        self.assertIn("TIE", text)

    def test_all_season_pairs_render(self):
        for a, b in [(1, 2), (7, 9), (9, 11)]:
            text = render_text(build_vs(a, b))
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def test_valid_pair_exits_0(self):
        rc, _, _ = _run(["--a", "9", "--b", "10"])
        self.assertEqual(rc, 0)

    def test_list_exits_0(self):
        rc, out, _ = _run(["--list"])
        self.assertEqual(rc, 0)
        self.assertIn("1", out)
        self.assertIn("11", out)

    def test_invalid_season_a_exits_1(self):
        rc, _, err = _run(["--a", "999", "--b", "10"])
        self.assertEqual(rc, 1)
        self.assertIn("999", err)

    def test_invalid_season_b_exits_1(self):
        rc, _, err = _run(["--a", "9", "--b", "999"])
        self.assertEqual(rc, 1)
        self.assertIn("999", err)

    def test_same_season_exits_1(self):
        rc, _, err = _run(["--a", "9", "--b", "9"])
        self.assertEqual(rc, 1)

    def test_missing_b_exits_1(self):
        rc, _, err = _run(["--a", "9"])
        self.assertEqual(rc, 1)

    def test_no_args_exits_nonzero(self):
        rc, _, _ = _run([])
        self.assertNotEqual(rc, 0)

    def test_text_output_has_result(self):
        _, out, _ = _run(["--a", "9", "--b", "10"])
        self.assertIn("RESULT", out)

    def test_json_valid(self):
        rc, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_json_has_winner(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        self.assertIn("winner", data)

    def test_json_has_rationale(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        self.assertIn("rationale", data)
        self.assertIsInstance(data["rationale"], str)
        self.assertGreater(len(data["rationale"]), 0)

    def test_json_has_comparison(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        self.assertIn("comparison", data)

    def test_json_has_metadata(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        self.assertIn("metadata", data)

    def test_json_winner_valid_value(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        self.assertIn(data["winner"], ("a", "b", "tie"))

    def test_json_winner_season_9_10(self):
        _, out, _ = _run(["--a", "9", "--b", "10", "--json"])
        data = json.loads(out)
        if data["winner"] in ("a", "b"):
            self.assertIsNotNone(data["winner_season"])
            self.assertIn(data["winner_season"], (9, 10))

    def test_all_known_season_pairs_exit_0(self):
        pairs = [(1, 11), (7, 9), (8, 10), (5, 6), (2, 4)]
        for a, b in pairs:
            rc, _, _ = _run(["--a", str(a), "--b", str(b)])
            self.assertEqual(rc, 0, f"Pair ({a},{b}) exited nonzero")

    def test_json_season_fields_correct(self):
        _, out, _ = _run(["--a", "7", "--b", "9", "--json"])
        data = json.loads(out)
        self.assertEqual(data["season_a"], 7)
        self.assertEqual(data["season_b"], 9)

    def test_json_serialisable_all_pairs(self):
        for a, b in [(9, 10), (7, 11), (1, 11)]:
            _, out, _ = _run(["--a", str(a), "--b", str(b), "--json"])
            data = json.loads(out)
            self.assertIsInstance(data, dict)

    def test_text_contains_dimension_names(self):
        _, out, _ = _run(["--a", "9", "--b", "10"])
        self.assertIn("Timeline events", out)
        self.assertIn("Active hermits", out)
        self.assertIn("Notable builds", out)

    def test_sparse_season_pair_no_crash(self):
        rc, _, _ = _run(["--a", "1", "--b", "2"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
