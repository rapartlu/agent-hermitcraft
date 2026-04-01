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
    _DISCORD_EMBED_TOTAL_LIMIT,
    _DISCORD_FIELD_VALUE_LIMIT,
    _DISCORD_TITLE_LIMIT,
    _SEASON_COLOURS,
    _significance_score,
    _truncate,
    build_collaborations,
    build_digest,
    build_discord_embed,
    build_highlights,
    build_most_active_hermits,
    build_notable_builds,
    build_peak_moment,
    build_stats,
    build_arc_summary,
    render_discord,
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


# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------

class TestTruncate(unittest.TestCase):

    def test_short_string_unchanged(self):
        self.assertEqual(_truncate("hello", 20), "hello")

    def test_exact_length_unchanged(self):
        self.assertEqual(_truncate("hello", 5), "hello")

    def test_long_string_truncated(self):
        result = _truncate("hello world foo bar", 10)
        self.assertLessEqual(len(result), 10)

    def test_suffix_appended_when_cut(self):
        result = _truncate("hello world", 8)
        self.assertTrue(result.endswith(" …"))

    def test_word_boundary_respected(self):
        # "hello world" → should cut after "hello" not mid-"world"
        result = _truncate("hello world this is long", 12)
        self.assertNotIn("wor", result.split(" …")[0].split()[-1][:3])

    def test_custom_suffix(self):
        result = _truncate("hello world", 8, suffix="...")
        self.assertTrue(result.endswith("..."))

    def test_empty_string(self):
        self.assertEqual(_truncate("", 10), "")


# ---------------------------------------------------------------------------
# build_discord_embed
# ---------------------------------------------------------------------------

class TestBuildDiscordEmbed(unittest.TestCase):

    def _embed(self, season: int = 9) -> dict:
        return build_discord_embed(build_digest(season))

    # Structure ---------------------------------------------------------------

    def test_returns_dict(self):
        self.assertIsInstance(self._embed(), dict)

    def test_has_title(self):
        self.assertIn("title", self._embed())

    def test_has_color(self):
        self.assertIn("color", self._embed())

    def test_has_fields_list(self):
        embed = self._embed()
        self.assertIn("fields", embed)
        self.assertIsInstance(embed["fields"], list)

    def test_has_footer(self):
        self.assertIn("footer", self._embed())

    def test_footer_has_text(self):
        self.assertIn("text", self._embed()["footer"])

    def test_title_contains_season_number(self):
        self.assertIn("9", self._embed(9)["title"])

    def test_footer_contains_season_number(self):
        self.assertIn("9", self._embed(9)["footer"]["text"])

    # Limits ------------------------------------------------------------------

    def test_title_within_limit(self):
        self.assertLessEqual(len(self._embed()["title"]), _DISCORD_TITLE_LIMIT)

    def test_all_field_values_within_limit(self):
        for field in self._embed()["fields"]:
            self.assertLessEqual(
                len(field["value"]),
                _DISCORD_FIELD_VALUE_LIMIT,
                f"Field '{field['name']}' exceeds value limit",
            )

    def test_total_embed_chars_within_limit(self):
        embed = self._embed()
        total = len(embed.get("title", ""))
        for f in embed.get("fields", []):
            total += len(f.get("name", "")) + len(f.get("value", ""))
        total += len(embed.get("footer", {}).get("text", ""))
        self.assertLessEqual(total, _DISCORD_EMBED_TOTAL_LIMIT)

    def test_limits_hold_for_all_seasons(self):
        for s in KNOWN_SEASONS:
            embed = self._embed(s)
            # title limit
            self.assertLessEqual(len(embed["title"]), _DISCORD_TITLE_LIMIT,
                                 f"Season {s} title over limit")
            # field value limits
            for f in embed["fields"]:
                self.assertLessEqual(len(f["value"]), _DISCORD_FIELD_VALUE_LIMIT,
                                     f"Season {s} field '{f['name']}' over limit")
            # total limit
            total = len(embed.get("title", ""))
            for f in embed.get("fields", []):
                total += len(f.get("name", "")) + len(f.get("value", ""))
            total += len(embed.get("footer", {}).get("text", ""))
            self.assertLessEqual(total, _DISCORD_EMBED_TOTAL_LIMIT,
                                 f"Season {s} total embed over limit")

    # Content -----------------------------------------------------------------

    def test_fields_nonempty(self):
        self.assertGreater(len(self._embed()["fields"]), 0)

    def test_quick_stats_field_present(self):
        names = [f["name"] for f in self._embed()["fields"]]
        self.assertTrue(any("Stats" in n for n in names))

    def test_season_arc_field_present(self):
        names = [f["name"] for f in self._embed()["fields"]]
        self.assertTrue(any("Arc" in n for n in names))

    def test_peak_moment_field_present_when_data_exists(self):
        names = [f["name"] for f in self._embed(9)["fields"]]
        self.assertTrue(any("Peak" in n for n in names))

    def test_highlights_field_present(self):
        names = [f["name"] for f in self._embed(9)["fields"]]
        self.assertTrue(any("Highlight" in n for n in names))

    def test_collaborations_field_present(self):
        names = [f["name"] for f in self._embed()["fields"]]
        self.assertTrue(any("Collab" in n for n in names))

    def test_colour_distinct_per_season(self):
        # Each season should get a unique colour integer
        colours = [build_discord_embed(build_digest(s))["color"]
                   for s in KNOWN_SEASONS]
        self.assertEqual(len(colours), len(set(colours)),
                         "Two seasons share the same embed colour")

    def test_all_fields_have_inline_key(self):
        for field in self._embed()["fields"]:
            self.assertIn("inline", field)

    def test_field_name_within_limit(self):
        for field in self._embed()["fields"]:
            self.assertLessEqual(len(field["name"]), _DISCORD_FIELD_VALUE_LIMIT)

    def test_no_empty_field_values(self):
        for field in self._embed()["fields"]:
            self.assertGreater(len(field["value"].strip()), 0,
                               f"Field '{field['name']}' has empty value")

    def test_json_serialisable(self):
        serialised = json.dumps(self._embed())
        self.assertIsInstance(serialised, str)

    # Season with no peak moment (all-empty digest) ---------------------------

    def test_no_peak_moment_no_crash(self):
        digest = build_digest(9)
        digest["peak_moment"] = None
        embed = build_discord_embed(digest)
        self.assertIsInstance(embed, dict)

    def test_empty_digest_no_crash(self):
        digest = {
            "season": 9, "stats": {}, "highlights": [],
            "peak_moment": None, "collaborations": [], "arc_summary": "",
        }
        embed = build_discord_embed(digest)
        self.assertIsInstance(embed, dict)


# ---------------------------------------------------------------------------
# render_discord
# ---------------------------------------------------------------------------

class TestRenderDiscord(unittest.TestCase):

    def _payload(self, season: int = 9) -> dict:
        return json.loads(render_discord(build_digest(season)))

    def test_returns_string(self):
        self.assertIsInstance(render_discord(build_digest(9)), str)

    def test_valid_json(self):
        raw = render_discord(build_digest(9))
        self.assertIsInstance(json.loads(raw), dict)

    def test_outer_key_is_embeds(self):
        payload = self._payload()
        self.assertIn("embeds", payload)

    def test_embeds_is_list(self):
        self.assertIsInstance(self._payload()["embeds"], list)

    def test_exactly_one_embed(self):
        self.assertEqual(len(self._payload()["embeds"]), 1)

    def test_embed_has_title(self):
        self.assertIn("title", self._payload()["embeds"][0])

    def test_embed_has_fields(self):
        self.assertIn("fields", self._payload()["embeds"][0])


# ---------------------------------------------------------------------------
# CLI — --discord flag
# ---------------------------------------------------------------------------

class TestCLIDiscord(unittest.TestCase):

    def test_discord_exits_0(self):
        rc, _, _ = _run(["--season", "9", "--discord"])
        self.assertEqual(rc, 0)

    def test_discord_produces_valid_json(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        data = json.loads(out)
        self.assertIsInstance(data, dict)

    def test_discord_outer_key_embeds(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        data = json.loads(out)
        self.assertIn("embeds", data)

    def test_discord_embed_title_present(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        data = json.loads(out)
        self.assertIn("title", data["embeds"][0])

    def test_discord_season_in_title(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        data = json.loads(out)
        self.assertIn("9", data["embeds"][0]["title"])

    def test_discord_field_values_within_limit(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        data = json.loads(out)
        for field in data["embeds"][0]["fields"]:
            self.assertLessEqual(len(field["value"]), _DISCORD_FIELD_VALUE_LIMIT)

    def test_discord_total_chars_within_limit(self):
        _, out, _ = _run(["--season", "9", "--discord"])
        embed = json.loads(out)["embeds"][0]
        total = len(embed.get("title", ""))
        for f in embed.get("fields", []):
            total += len(f.get("name", "")) + len(f.get("value", ""))
        total += len(embed.get("footer", {}).get("text", ""))
        self.assertLessEqual(total, _DISCORD_EMBED_TOTAL_LIMIT)

    def test_discord_mutually_exclusive_with_json(self):
        rc, _, _ = _run(["--season", "9", "--discord", "--json"])
        self.assertNotEqual(rc, 0)

    def test_discord_mutually_exclusive_with_markdown(self):
        rc, _, _ = _run(["--season", "9", "--discord", "--markdown"])
        self.assertNotEqual(rc, 0)

    def test_discord_top_flag_respected(self):
        _, out, _ = _run(["--season", "9", "--discord", "--top", "2"])
        data = json.loads(out)
        fields = data["embeds"][0]["fields"]
        highlight_field = next(
            (f for f in fields if "Highlight" in f["name"]), None
        )
        if highlight_field:
            # At most 2 numbered entries; "…" is allowed as a trailing line
            numbered = [ln for ln in highlight_field["value"].splitlines()
                        if ln and ln[0].isdigit()]
            self.assertLessEqual(len(numbered), 2)

    def test_discord_unknown_season_exits_1(self):
        rc, _, err = _run(["--season", "999", "--discord"])
        self.assertEqual(rc, 1)

    def test_discord_all_seasons_exit_0(self):
        for s in KNOWN_SEASONS:
            rc, _, _ = _run(["--season", str(s), "--discord"])
            self.assertEqual(rc, 0, f"Season {s} exited nonzero with --discord")

    def test_discord_sparse_season_no_crash(self):
        rc, out, _ = _run(["--season", "1", "--discord"])
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIn("embeds", data)

    # Season colours ----------------------------------------------------------

    def test_season_colour_all_11_defined(self):
        self.assertEqual(len(_SEASON_COLOURS), 11)

    def test_all_season_colours_positive_ints(self):
        for s, c in _SEASON_COLOURS.items():
            self.assertIsInstance(c, int)
            self.assertGreater(c, 0, f"Season {s} colour must be positive")

    def test_season_colours_all_distinct(self):
        colours = list(_SEASON_COLOURS.values())
        self.assertEqual(len(colours), len(set(colours)))


# ---------------------------------------------------------------------------
# build_most_active_hermits
# ---------------------------------------------------------------------------

class TestBuildMostActiveHermits(unittest.TestCase):

    def _events(self):
        return [
            _make_event(hermits=["Grian", "Scar"], title="Event A"),
            _make_event(hermits=["Grian", "Mumbo"], title="Event B"),
            _make_event(hermits=["Grian"], title="Event C"),
            _make_event(hermits=["Scar"], title="Event D"),
            _make_event(hermits=["All"], title="Server Event"),
        ]

    def test_returns_list(self):
        self.assertIsInstance(build_most_active_hermits(9, self._events()), list)

    def test_top_n_limits(self):
        result = build_most_active_hermits(9, self._events(), top_n=2)
        self.assertLessEqual(len(result), 2)

    def test_grian_is_most_active(self):
        result = build_most_active_hermits(9, self._events(), top_n=5)
        self.assertEqual(result[0]["hermit"], "Grian")

    def test_grian_event_count_is_3(self):
        result = build_most_active_hermits(9, self._events(), top_n=5)
        grian = next(r for r in result if r["hermit"] == "Grian")
        self.assertEqual(grian["event_count"], 3)

    def test_all_excluded(self):
        result = build_most_active_hermits(9, self._events(), top_n=10)
        names = [r["hermit"] for r in result]
        self.assertNotIn("All", names)

    def test_ranks_sequential(self):
        result = build_most_active_hermits(9, self._events(), top_n=5)
        for i, entry in enumerate(result, start=1):
            self.assertEqual(entry["rank"], i)

    def test_required_keys(self):
        required = {"rank", "hermit", "event_count"}
        for entry in build_most_active_hermits(9, self._events(), top_n=5):
            self.assertTrue(required.issubset(entry.keys()))

    def test_sorted_by_count_desc(self):
        result = build_most_active_hermits(9, self._events(), top_n=5)
        counts = [r["event_count"] for r in result]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_empty_events_returns_empty(self):
        self.assertEqual(build_most_active_hermits(9, []), [])

    def test_only_all_events_returns_empty(self):
        events = [_make_event(hermits=["All"]) for _ in range(3)]
        self.assertEqual(build_most_active_hermits(9, events), [])

    def test_default_top_n_is_5(self):
        events = [_make_event(hermits=[f"Hermit{i}"]) for i in range(10)]
        result = build_most_active_hermits(9, events)
        self.assertLessEqual(len(result), 5)

    def test_event_count_is_int(self):
        result = build_most_active_hermits(9, self._events(), top_n=5)
        for entry in result:
            self.assertIsInstance(entry["event_count"], int)


# ---------------------------------------------------------------------------
# build_notable_builds
# ---------------------------------------------------------------------------

class TestBuildNotableBuilds(unittest.TestCase):

    def _events(self):
        return [
            _make_event(type="build", title="Epic Base", hermits=["Grian", "Scar"],
                        date_precision="day"),
            _make_event(type="build", title="Small Hut", hermits=["Mumbo"]),
            _make_event(type="build", title="Mega Farm", hermits=["A", "B", "C", "D"]),
            _make_event(type="milestone", title="Season Start", hermits=["All"]),
            _make_event(type="lore", title="Lore Event", hermits=["Grian"]),
        ]

    def test_returns_list(self):
        self.assertIsInstance(build_notable_builds(9, self._events()), list)

    def test_top_n_limits(self):
        self.assertLessEqual(len(build_notable_builds(9, self._events(), top_n=2)), 2)

    def test_only_build_events(self):
        result = build_notable_builds(9, self._events(), top_n=10)
        # No milestone or lore events should be present
        titles = [r["title"] for r in result]
        self.assertNotIn("Season Start", titles)
        self.assertNotIn("Lore Event", titles)

    def test_sorted_by_score_desc(self):
        result = build_notable_builds(9, self._events(), top_n=3)
        scores = [r["significance_score"] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranks_sequential(self):
        result = build_notable_builds(9, self._events(), top_n=3)
        for i, entry in enumerate(result, start=1):
            self.assertEqual(entry["rank"], i)

    def test_required_keys(self):
        required = {"rank", "title", "description", "date", "hermits",
                    "significance_score"}
        for entry in build_notable_builds(9, self._events(), top_n=3):
            self.assertTrue(required.issubset(entry.keys()))

    def test_empty_events_returns_empty(self):
        self.assertEqual(build_notable_builds(9, []), [])

    def test_no_build_events_returns_empty(self):
        events = [_make_event(type="milestone"), _make_event(type="lore")]
        self.assertEqual(build_notable_builds(9, events), [])

    def test_hermits_is_list(self):
        result = build_notable_builds(9, self._events(), top_n=3)
        for entry in result:
            self.assertIsInstance(entry["hermits"], list)

    def test_score_is_int(self):
        result = build_notable_builds(9, self._events(), top_n=3)
        for entry in result:
            self.assertIsInstance(entry["significance_score"], int)

    def test_default_top_n_is_3(self):
        events = [_make_event(type="build", title=f"Build {i}") for i in range(10)]
        result = build_notable_builds(9, events)
        self.assertLessEqual(len(result), 3)


# ---------------------------------------------------------------------------
# build_digest — new keys
# ---------------------------------------------------------------------------

class TestBuildDigestNewKeys(unittest.TestCase):

    def test_most_active_hermits_present(self):
        d = build_digest(9)
        self.assertIn("most_active_hermits", d)

    def test_notable_builds_present(self):
        d = build_digest(9)
        self.assertIn("notable_builds", d)

    def test_most_active_hermits_is_list(self):
        self.assertIsInstance(build_digest(9)["most_active_hermits"], list)

    def test_notable_builds_is_list(self):
        self.assertIsInstance(build_digest(9)["notable_builds"], list)

    def test_most_active_hermits_entries_have_rank(self):
        for entry in build_digest(9)["most_active_hermits"]:
            self.assertIn("rank", entry)

    def test_notable_builds_entries_have_rank(self):
        for entry in build_digest(9)["notable_builds"]:
            self.assertIn("rank", entry)

    def test_json_serialisable_with_new_keys(self):
        import json
        d = build_digest(9)
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)

    def test_sparse_season_no_crash(self):
        d = build_digest(1)
        self.assertIn("most_active_hermits", d)
        self.assertIn("notable_builds", d)


# ---------------------------------------------------------------------------
# render_markdown — new sections
# ---------------------------------------------------------------------------

class TestRenderMarkdownNewSections(unittest.TestCase):

    def _digest(self):
        return build_digest(9, top_n=3)

    def test_has_most_active_section(self):
        self.assertIn("## Most Active Hermits", render_markdown(self._digest()))

    def test_has_notable_builds_section(self):
        self.assertIn("## Notable Builds", render_markdown(self._digest()))

    def test_empty_active_no_crash(self):
        d = self._digest()
        d["most_active_hermits"] = []
        md = render_markdown(d)
        self.assertIsInstance(md, str)
        self.assertIn("Most Active Hermits", md)

    def test_empty_builds_no_crash(self):
        d = self._digest()
        d["notable_builds"] = []
        md = render_markdown(d)
        self.assertIsInstance(md, str)
        self.assertIn("Notable Builds", md)

    def test_word_count_under_800(self):
        md = render_markdown(self._digest())
        # Strip markdown punctuation then count words
        import re
        plain = re.sub(r"[#*>`\-_]", " ", md)
        word_count = len(plain.split())
        self.assertLessEqual(
            word_count, 800,
            f"Digest markdown exceeds 800 words: {word_count} words",
        )

    def test_active_hermit_name_in_output(self):
        d = self._digest()
        if d["most_active_hermits"]:
            top_hermit = d["most_active_hermits"][0]["hermit"]
            self.assertIn(top_hermit, render_markdown(d))

    def test_notable_build_title_in_output(self):
        d = self._digest()
        if d["notable_builds"]:
            top_build_title = d["notable_builds"][0]["title"]
            self.assertIn(top_build_title, render_markdown(d))


# ---------------------------------------------------------------------------
# Discord embed — new fields
# ---------------------------------------------------------------------------

class TestDiscordEmbedNewFields(unittest.TestCase):

    def _embed(self, season: int = 9) -> dict:
        return build_discord_embed(build_digest(season))

    def test_most_active_field_present(self):
        names = [f["name"] for f in self._embed()["fields"]]
        self.assertTrue(any("Active" in n for n in names),
                        f"No 'Active' field in: {names}")

    def test_limits_still_hold_with_new_fields(self):
        embed = self._embed()
        total = len(embed.get("title", ""))
        for f in embed.get("fields", []):
            self.assertLessEqual(len(f["value"]), _DISCORD_FIELD_VALUE_LIMIT,
                                 f"Field '{f['name']}' over limit")
            total += len(f.get("name", "")) + len(f.get("value", ""))
        total += len(embed.get("footer", {}).get("text", ""))
        self.assertLessEqual(total, _DISCORD_EMBED_TOTAL_LIMIT)

    def test_all_seasons_limits_hold(self):
        for s in KNOWN_SEASONS:
            embed = self._embed(s)
            for f in embed["fields"]:
                self.assertLessEqual(
                    len(f["value"]), _DISCORD_FIELD_VALUE_LIMIT,
                    f"Season {s} field '{f['name']}' over limit",
                )
            total = len(embed.get("title", ""))
            for f in embed.get("fields", []):
                total += len(f.get("name", "")) + len(f.get("value", ""))
            total += len(embed.get("footer", {}).get("text", ""))
            self.assertLessEqual(total, _DISCORD_EMBED_TOTAL_LIMIT,
                                 f"Season {s} total embed over limit")

    def test_empty_active_no_crash(self):
        digest = build_digest(9)
        digest["most_active_hermits"] = []
        embed = build_discord_embed(digest)
        self.assertIsInstance(embed, dict)

    def test_empty_builds_no_crash(self):
        digest = build_digest(9)
        digest["notable_builds"] = []
        embed = build_discord_embed(digest)
        self.assertIsInstance(embed, dict)


if __name__ == "__main__":
    unittest.main()
