"""
Tests for tools/season_digest.py
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.season_digest import (
    KNOWN_SEASONS,
    _significance_score,
    build_stats,
    build_highlights,
    build_peak_moment,
    build_collaborations,
    build_arc_summary,
    build_digest,
    render_markdown,
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


def _make_event(**kwargs) -> dict:
    """Minimal synthetic event for unit tests.

    Defaults date_precision to "month" so no day-precision bonus (+1) is
    applied unless a test explicitly passes date_precision="day".
    """
    base: dict = {
        "season": 9,
        "type": "milestone",
        "title": "Test Event",
        "description": "A test event description.",
        "date": "2022-06-01",
        "date_precision": "month",
        "hermits": ["Grian"],
        "source": "test",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _significance_score
# ---------------------------------------------------------------------------

class TestSignificanceScore(unittest.TestCase):

    def test_milestone_scores_highest_type(self):
        ev = _make_event(type="milestone", hermits=["Grian"])
        self.assertEqual(_significance_score(ev), 10)

    def test_meta_scores_lowest_type(self):
        ev = _make_event(type="meta", hermits=["Grian"])
        self.assertEqual(_significance_score(ev), 1)

    def test_all_hermits_bonus(self):
        ev = _make_event(type="milestone", hermits=["All"])
        self.assertEqual(_significance_score(ev), 13)

    def test_four_hermits_bonus(self):
        ev = _make_event(type="build", hermits=["A", "B", "C", "D"])
        self.assertEqual(_significance_score(ev), 7)  # 5 + 2

    def test_pair_bonus(self):
        ev = _make_event(type="build", hermits=["A", "B"])
        self.assertEqual(_significance_score(ev), 6)  # 5 + 1

    def test_day_precision_bonus(self):
        ev = _make_event(type="build", hermits=["A"], date_precision="day")
        self.assertEqual(_significance_score(ev), 6)  # 5 + 1

    def test_max_score_14(self):
        ev = _make_event(
            type="milestone", hermits=["All"], date_precision="day"
        )
        self.assertEqual(_significance_score(ev), 14)

    def test_unknown_type_returns_int(self):
        ev = _make_event(type="xyzunknown")
        self.assertIsInstance(_significance_score(ev), int)


# ---------------------------------------------------------------------------
# build_stats
# ---------------------------------------------------------------------------

class TestBuildStats(unittest.TestCase):

    def _events(self):
        return [
            _make_event(hermits=["Grian", "Scar"], type="build", date="2022-03-01"),
            _make_event(hermits=["Mumbo"], type="milestone", date="2022-06-15"),
            _make_event(hermits=["All"], type="meta", date="2023-01-10"),
        ]

    def test_returns_dict(self):
        self.assertIsInstance(build_stats(9, self._events()), dict)

    def test_season_key(self):
        self.assertEqual(build_stats(9, self._events())["season"], 9)

    def test_event_count(self):
        self.assertEqual(build_stats(9, self._events())["event_count"], 3)

    def test_hermit_count_excludes_all(self):
        stats = build_stats(9, self._events())
        # Grian, Scar, Mumbo — "All" not counted
        self.assertEqual(stats["hermit_count"], 3)

    def test_hermits_sorted(self):
        stats = build_stats(9, self._events())
        self.assertEqual(stats["hermits"], sorted(stats["hermits"]))

    def test_date_range(self):
        stats = build_stats(9, self._events())
        self.assertEqual(stats["date_start"], "2022-03-01")
        self.assertEqual(stats["date_end"], "2023-01-10")

    def test_type_breakdown_is_dict(self):
        self.assertIsInstance(build_stats(9, self._events())["type_breakdown"], dict)

    def test_type_breakdown_counts(self):
        stats = build_stats(9, self._events())
        bd = stats["type_breakdown"]
        self.assertEqual(bd.get("build"), 1)
        self.assertEqual(bd.get("milestone"), 1)
        self.assertEqual(bd.get("meta"), 1)

    def test_empty_events_no_crash(self):
        stats = build_stats(9, [])
        self.assertEqual(stats["event_count"], 0)
        self.assertIsNone(stats["date_start"])
        self.assertIsNone(stats["date_end"])
        self.assertEqual(stats["hermit_count"], 0)


# ---------------------------------------------------------------------------
# build_highlights
# ---------------------------------------------------------------------------

class TestBuildHighlights(unittest.TestCase):

    def _events(self):
        return [
            _make_event(type="milestone", hermits=["All"], date_precision="day"),
            _make_event(type="build", hermits=["A", "B"], title="Build One"),
            _make_event(type="lore", hermits=["X"], title="Lore Event"),
            _make_event(type="meta", hermits=["Y"], title="Meta Event"),
        ]

    def test_returns_list(self):
        self.assertIsInstance(build_highlights(9, self._events(), 3), list)

    def test_top_n_limits(self):
        self.assertLessEqual(len(build_highlights(9, self._events(), 2)), 2)

    def test_sorted_desc_by_score(self):
        results = build_highlights(9, self._events(), 10)
        scores = [e["significance_score"] for e in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranks_sequential(self):
        results = build_highlights(9, self._events(), 4)
        for i, e in enumerate(results, 1):
            self.assertEqual(e["rank"], i)

    def test_required_keys(self):
        required = {"rank", "title", "description", "date", "type",
                    "hermits", "significance_score"}
        for entry in build_highlights(9, self._events(), 4):
            self.assertTrue(required.issubset(entry.keys()))

    def test_empty_events_returns_empty(self):
        self.assertEqual(build_highlights(9, [], 5), [])

    def test_hermits_is_list(self):
        for entry in build_highlights(9, self._events(), 4):
            self.assertIsInstance(entry["hermits"], list)


# ---------------------------------------------------------------------------
# build_peak_moment
# ---------------------------------------------------------------------------

class TestBuildPeakMoment(unittest.TestCase):

    def _events(self):
        return [
            _make_event(type="milestone", hermits=["All"], date_precision="day",
                        title="Top Event"),
            _make_event(type="build", hermits=["A"], title="Lesser Event"),
        ]

    def test_returns_dict_or_none(self):
        result = build_peak_moment(9, self._events())
        self.assertIsInstance(result, dict)

    def test_returns_none_for_empty(self):
        self.assertIsNone(build_peak_moment(9, []))

    def test_highest_scored_is_returned(self):
        result = build_peak_moment(9, self._events())
        self.assertEqual(result["title"], "Top Event")

    def test_required_keys(self):
        required = {"title", "description", "date", "type", "hermits",
                    "significance_score"}
        result = build_peak_moment(9, self._events())
        self.assertTrue(required.issubset(result.keys()))

    def test_no_rank_key(self):
        result = build_peak_moment(9, self._events())
        self.assertNotIn("rank", result)

    def test_score_is_int(self):
        result = build_peak_moment(9, self._events())
        self.assertIsInstance(result["significance_score"], int)


# ---------------------------------------------------------------------------
# build_collaborations
# ---------------------------------------------------------------------------

class TestBuildCollaborations(unittest.TestCase):

    def _events(self):
        return [
            _make_event(hermits=["Grian", "Scar"], title="Collab A"),
            _make_event(hermits=["Grian", "Scar"], title="Collab B"),
            _make_event(hermits=["Mumbo", "Grian"], title="Collab C"),
            _make_event(hermits=["Solo"], title="Solo Event"),
            _make_event(hermits=["All"], title="Server Event"),
        ]

    def test_returns_list(self):
        self.assertIsInstance(build_collaborations(9, self._events(), 3), list)

    def test_top_n_limits(self):
        self.assertLessEqual(len(build_collaborations(9, self._events(), 2)), 2)

    def test_sorted_by_count_desc(self):
        results = build_collaborations(9, self._events(), 3)
        counts = [e["shared_event_count"] for e in results]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_grian_scar_is_top_pair(self):
        results = build_collaborations(9, self._events(), 3)
        top = results[0]
        pair = {top["hermit_a"], top["hermit_b"]}
        self.assertEqual(pair, {"Grian", "Scar"})

    def test_grian_scar_count_is_2(self):
        results = build_collaborations(9, self._events(), 3)
        top = results[0]
        self.assertEqual(top["shared_event_count"], 2)

    def test_all_excluded_from_pairs(self):
        results = build_collaborations(9, self._events(), 5)
        for entry in results:
            self.assertNotIn("All", [entry["hermit_a"], entry["hermit_b"]])

    def test_solo_events_excluded(self):
        results = build_collaborations(9, self._events(), 5)
        for entry in results:
            self.assertNotEqual(entry["hermit_a"], entry["hermit_b"])

    def test_required_keys(self):
        required = {"hermit_a", "hermit_b", "shared_event_count", "event_titles"}
        for entry in build_collaborations(9, self._events(), 3):
            self.assertTrue(required.issubset(entry.keys()))

    def test_empty_events_returns_empty(self):
        self.assertEqual(build_collaborations(9, [], 3), [])

    def test_only_solo_events_returns_empty(self):
        solo = [_make_event(hermits=["Solo"]) for _ in range(5)]
        self.assertEqual(build_collaborations(9, solo, 3), [])


# ---------------------------------------------------------------------------
# build_arc_summary
# ---------------------------------------------------------------------------

class TestBuildArcSummary(unittest.TestCase):

    def _stats(self, **kw) -> dict:
        base = {
            "season": 9,
            "hermit_count": 16,
            "date_start": "2022-03-05",
            "date_end": "2023-12-20",
            "type_breakdown": {"milestone": 3, "build": 5},
        }
        base.update(kw)
        return base

    def _highlights(self):
        return [
            {
                "rank": 1, "type": "milestone", "title": "Season 9 Launches",
                "description": "The server goes live with 26 hermits.",
                "date": "2022-03-05", "hermits": ["All"], "significance_score": 14,
            },
            {
                "rank": 2, "type": "lore", "title": "Big Lore Thing",
                "description": "A major roleplay event unfolds.",
                "date": "2022-07-01", "hermits": ["Grian", "Scar"],
                "significance_score": 9,
            },
        ]

    def test_returns_string(self):
        self.assertIsInstance(
            build_arc_summary(9, self._stats(), self._highlights()), str
        )

    def test_contains_season_number(self):
        arc = build_arc_summary(9, self._stats(), self._highlights())
        self.assertIn("9", arc)

    def test_contains_hermit_count(self):
        arc = build_arc_summary(9, self._stats(), self._highlights())
        self.assertIn("16", arc)

    def test_contains_date_range(self):
        arc = build_arc_summary(9, self._stats(), self._highlights())
        self.assertIn("2022", arc)

    def test_empty_highlights_no_crash(self):
        arc = build_arc_summary(9, self._stats(), [])
        self.assertIsInstance(arc, str)
        self.assertGreater(len(arc), 0)

    def test_no_milestone_falls_back_gracefully(self):
        highlights = [
            {
                "rank": 1, "type": "build", "title": "Big Build",
                "description": "A huge structure.",
                "date": "2022-05-01", "hermits": ["Grian"], "significance_score": 5,
            }
        ]
        arc = build_arc_summary(9, self._stats(), highlights)
        self.assertIsInstance(arc, str)
        self.assertGreater(len(arc), 0)

    def test_sparse_stats_no_crash(self):
        sparse = {"season": 1, "hermit_count": 0, "date_start": None,
                  "date_end": None, "type_breakdown": {}}
        arc = build_arc_summary(1, sparse, [])
        self.assertIsInstance(arc, str)


# ---------------------------------------------------------------------------
# build_digest
# ---------------------------------------------------------------------------

class TestBuildDigest(unittest.TestCase):

    def test_returns_dict(self):
        self.assertIsInstance(build_digest(9), dict)

    def test_top_level_keys(self):
        required = {"season", "stats", "highlights", "peak_moment",
                    "collaborations", "arc_summary"}
        self.assertTrue(required.issubset(build_digest(9).keys()))

    def test_season_key_correct(self):
        self.assertEqual(build_digest(9)["season"], 9)

    def test_highlights_respects_top_n(self):
        self.assertLessEqual(len(build_digest(9, top_n=3)["highlights"]), 3)

    def test_highlights_is_list(self):
        self.assertIsInstance(build_digest(9)["highlights"], list)

    def test_collaborations_is_list(self):
        self.assertIsInstance(build_digest(9)["collaborations"], list)

    def test_arc_summary_is_str(self):
        self.assertIsInstance(build_digest(9)["arc_summary"], str)

    def test_sparse_season_no_crash(self):
        d = build_digest(1)
        self.assertEqual(d["season"], 1)
        self.assertIsInstance(d["stats"], dict)

    def test_json_serialisable(self):
        serialised = json.dumps(build_digest(9))
        self.assertIsInstance(serialised, str)

    def test_stats_subkeys_present(self):
        stats = build_digest(9)["stats"]
        for key in ("event_count", "hermit_count", "date_start", "date_end",
                    "type_breakdown"):
            self.assertIn(key, stats)

    def test_collaborations_top_pairs_respected(self):
        d = build_digest(9, top_pairs=2)
        self.assertLessEqual(len(d["collaborations"]), 2)


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

class TestRenderMarkdown(unittest.TestCase):

    def _digest(self):
        return build_digest(9, top_n=3)

    def test_returns_string(self):
        self.assertIsInstance(render_markdown(self._digest()), str)

    def test_has_h1_title(self):
        md = render_markdown(self._digest())
        self.assertRegex(md, r"^# Hermitcraft Season 9")

    def test_has_quick_stats_section(self):
        self.assertIn("## Quick Stats", render_markdown(self._digest()))

    def test_has_peak_moment_section(self):
        self.assertIn("## Peak Moment", render_markdown(self._digest()))

    def test_has_highlights_section(self):
        self.assertIn("## Top", render_markdown(self._digest()))

    def test_has_collaborations_section(self):
        self.assertIn("## Notable Collaborations", render_markdown(self._digest()))

    def test_has_arc_section(self):
        self.assertIn("## Season Arc", render_markdown(self._digest()))

    def test_date_range_present(self):
        md = render_markdown(self._digest())
        self.assertIn("Date range", md)

    def test_hermit_count_present(self):
        md = render_markdown(self._digest())
        self.assertIn("Hermits", md)

    def test_peak_moment_title_in_output(self):
        digest = self._digest()
        peak_title = digest["peak_moment"]["title"]
        self.assertIn(peak_title, render_markdown(digest))

    def test_no_peak_moment_no_crash(self):
        digest = self._digest()
        digest["peak_moment"] = None
        md = render_markdown(digest)
        self.assertIsInstance(md, str)
        self.assertIn("Peak Moment", md)

    def test_empty_highlights_no_crash(self):
        digest = self._digest()
        digest["highlights"] = []
        md = render_markdown(digest)
        self.assertIsInstance(md, str)

    def test_empty_collabs_no_crash(self):
        digest = self._digest()
        digest["collaborations"] = []
        md = render_markdown(digest)
        self.assertIsInstance(md, str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def test_season_exits_0(self):
        rc, _, _ = _run(["--season", "9"])
        self.assertEqual(rc, 0)

    def test_list_exits_0(self):
        rc, out, _ = _run(["--list"])
        self.assertEqual(rc, 0)
        self.assertIn("1", out)
        self.assertIn("11", out)

    def test_unknown_season_exits_1(self):
        rc, _, err = _run(["--season", "999"])
        self.assertEqual(rc, 1)
        self.assertIn("999", err)

    def test_markdown_default_has_h1(self):
        _, out, _ = _run(["--season", "9"])
        self.assertRegex(out, r"^# Hermitcraft Season 9")

    def test_markdown_flag_explicit(self):
        _, out, _ = _run(["--season", "9", "--markdown"])
        self.assertIn("# Hermitcraft Season 9", out)

    def test_json_flag_valid_json(self):
        rc, out, _ = _run(["--season", "9", "--json"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_json_has_required_keys(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        for key in ("season", "stats", "highlights", "peak_moment",
                    "collaborations", "arc_summary"):
            self.assertIn(key, data)

    def test_json_season_field_correct(self):
        _, out, _ = _run(["--season", "7", "--json"])
        data = json.loads(out)
        self.assertEqual(data["season"], 7)

    def test_top_flag_limits_highlights(self):
        _, out, _ = _run(["--season", "9", "--json", "--top", "2"])
        data = json.loads(out)
        self.assertLessEqual(len(data["highlights"]), 2)

    def test_top_flag_default_is_5(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        self.assertLessEqual(len(data["highlights"]), 5)

    def test_all_known_seasons_exit_0(self):
        for s in KNOWN_SEASONS:
            rc, _, _ = _run(["--season", str(s)])
            self.assertEqual(rc, 0, f"Season {s} exited nonzero")

    def test_json_and_markdown_mutually_exclusive(self):
        rc, _, _ = _run(["--season", "9", "--json", "--markdown"])
        self.assertNotEqual(rc, 0)

    def test_no_args_exits_nonzero(self):
        rc, _, _ = _run([])
        self.assertNotEqual(rc, 0)

    def test_json_arc_summary_is_string(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        self.assertIsInstance(data["arc_summary"], str)
        self.assertGreater(len(data["arc_summary"]), 0)

    def test_json_stats_has_hermit_count(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        self.assertGreater(data["stats"]["hermit_count"], 0)

    def test_json_highlights_sorted_by_score(self):
        _, out, _ = _run(["--season", "9", "--json"])
        data = json.loads(out)
        scores = [e["significance_score"] for e in data["highlights"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_sparse_season_no_crash(self):
        rc, _, _ = _run(["--season", "1"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
