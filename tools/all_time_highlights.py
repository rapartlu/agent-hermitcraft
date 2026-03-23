"""
tools/all_time_highlights.py — Cross-season Hermitcraft highlights comparison.

Answers the question every new fan asks first: "What are the most iconic
moments across ALL of Hermitcraft's history?"

Two complementary views:

  1. All-time top N  (--top-events)
     Ranks every event from every season simultaneously by significance score
     and returns the best N, with season labels.  Good for an event timeline
     deep-dive or a shareable "best 20 moments in Hermitcraft history" list.

  2. Hall of Fame  (--hall-of-fame)
     Returns exactly the #1 ranked event from each season — 11 entries sorted
     chronologically.  Gives a quick mental map of how the server evolved.

Both modes support --types to focus on a subset of event types and --json
for machine-readable output.

Significance scoring (fully documented):
  Type bonus:
    milestone  +10   lore  +8   game  +7
    collab     +6    build +5   meta  +1
  Hermit-count bonus:
    hermits == ["All"]  +3   (server-wide events are broadly significant)
    4+ named hermits    +2   (large group involvement)
    2–3 named hermits   +1   (any collaboration)
  Date-precision bonus:
    date_precision == "day"  +1   (well-documented events tend to be notable)
  Maximum possible score: 14

Usage:
    python -m tools.all_time_highlights --top-events
    python -m tools.all_time_highlights --top-events --top 20 --types milestone lore
    python -m tools.all_time_highlights --top-events --json
    python -m tools.all_time_highlights --hall-of-fame
    python -m tools.all_time_highlights --hall-of-fame --json
    python -m tools.all_time_highlights --hall-of-fame --types milestone lore
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "events.json"
_VIDEO_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "video_events.json"

KNOWN_SEASONS: list[int] = list(range(1, 12))  # seasons 1–11

# ---------------------------------------------------------------------------
# Significance scoring
# ---------------------------------------------------------------------------

#: Per-type base scores — higher = more interesting to casual fans.
_TYPE_SCORE: dict[str, int] = {
    "milestone": 10,
    "lore": 8,
    "game": 7,
    "collab": 6,
    "build": 5,
    "meta": 1,
}

_DEFAULT_TOP_N = 10


def significance_score(event: dict) -> int:
    """
    Compute a significance score for *event*.

    Higher scores indicate events more likely to appear in a 'best of' list
    for casual Hermitcraft fans.  See module docstring for full breakdown.
    """
    score = _TYPE_SCORE.get(event.get("type", ""), 0)

    hermits = event.get("hermits", [])
    if hermits == ["All"]:
        score += 3          # server-wide events are broadly significant
    elif len(hermits) >= 4:
        score += 2          # large group involvement
    elif len(hermits) >= 2:
        score += 1          # any collaboration

    if event.get("date_precision") == "day":
        score += 1          # well-documented events tend to be more notable

    return score


def _event_sort_key(ev: dict) -> tuple[int, int, int]:
    parts = ev.get("date", "").split("-")
    try:
        return (
            int(parts[0]) if len(parts) > 0 else 9999,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )
    except (ValueError, IndexError):
        return (9999, 0, 0)


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

def _load_all_events() -> list[dict]:
    events: list[dict] = []
    for path in (_EVENTS_FILE, _VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return events


def _filter_events(
    events: list[dict],
    types: list[str] | None = None,
) -> list[dict]:
    """Return *events* optionally filtered to *types*."""
    if not types:
        return events
    type_set = set(types)
    return [ev for ev in events if ev.get("type") in type_set]


# ---------------------------------------------------------------------------
# Core ranking helpers
# ---------------------------------------------------------------------------

def rank_all_time_highlights(
    top_n: int = _DEFAULT_TOP_N,
    types: list[str] | None = None,
) -> list[dict]:
    """
    Return the top *top_n* events across **all** Hermitcraft seasons.

    Each returned dict contains:
        rank, season, title, description, date, type, hermits,
        significance_score

    Ties are broken chronologically (earlier events first).
    Unknown seasons (season == 0 or not in KNOWN_SEASONS) are included so
    no data is silently dropped — callers can filter further if desired.
    """
    all_events = _load_all_events()
    filtered = _filter_events(all_events, types)

    scored = [
        (significance_score(ev), _event_sort_key(ev), ev)
        for ev in filtered
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))

    results: list[dict] = []
    for rank, (score, _, ev) in enumerate(scored[:top_n], start=1):
        results.append(
            {
                "rank": rank,
                "season": ev.get("season"),
                "title": ev.get("title", "(untitled)"),
                "description": ev.get("description", ""),
                "date": ev.get("date", ""),
                "type": ev.get("type", ""),
                "hermits": ev.get("hermits", []),
                "significance_score": score,
            }
        )
    return results


def build_hall_of_fame(
    types: list[str] | None = None,
) -> list[dict]:
    """
    Return one entry per known season: the highest-scoring event for that
    season.  Results are sorted chronologically by season number.

    Seasons with no qualifying events (after optional type filtering) are
    omitted from the output list.

    Each returned dict contains:
        season, title, description, date, type, hermits, significance_score
    """
    all_events = _load_all_events()
    filtered = _filter_events(all_events, types)

    # Build per-season best
    best_by_season: dict[int, tuple[int, tuple, dict]] = {}
    for ev in filtered:
        season = ev.get("season")
        if season not in KNOWN_SEASONS:
            continue
        score = significance_score(ev)
        sort_key = _event_sort_key(ev)
        existing = best_by_season.get(season)
        if existing is None or score > existing[0]:
            best_by_season[season] = (score, sort_key, ev)
        elif score == existing[0] and sort_key < existing[1]:
            # Tie: prefer chronologically earlier
            best_by_season[season] = (score, sort_key, ev)

    results: list[dict] = []
    for season in sorted(best_by_season):
        score, _, ev = best_by_season[season]
        results.append(
            {
                "season": season,
                "title": ev.get("title", "(untitled)"),
                "description": ev.get("description", ""),
                "date": ev.get("date", ""),
                "type": ev.get("type", ""),
                "hermits": ev.get("hermits", []),
                "significance_score": score,
            }
        )
    return results


# ---------------------------------------------------------------------------
# JSON output builders
# ---------------------------------------------------------------------------

def build_top_events_output(
    highlights: list[dict],
    top_n: int,
    types: list[str] | None,
) -> dict:
    """Structured JSON output for the --top-events mode."""
    result: dict = {
        "mode": "top_events",
        "top_n_requested": top_n,
        "result_count": len(highlights),
        "events": highlights,
    }
    if types:
        result["type_filter"] = sorted(types)
    return result


def build_hall_of_fame_output(
    entries: list[dict],
    types: list[str] | None,
) -> dict:
    """Structured JSON output for the --hall-of-fame mode."""
    result: dict = {
        "mode": "hall_of_fame",
        "season_count": len(entries),
        "entries": entries,
    }
    if types:
        result["type_filter"] = sorted(types)
    return result


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def _hermit_str(hermits: list[str]) -> str:
    if hermits == ["All"]:
        return "All hermits"
    return ", ".join(hermits[:3]) + (" …" if len(hermits) > 3 else "")


def _wrap_desc(desc: str, indent: str = "     ") -> list[str]:
    """Wrap description text at 72 columns with a leading indent."""
    if not desc:
        return []
    words = desc.split()
    lines = []
    buf = indent
    for word in words:
        if len(buf) + len(word) + 1 > 72:
            lines.append(buf.rstrip())
            buf = indent + word
        else:
            buf = (buf + " " + word) if buf.strip() else (buf + word)
    if buf.strip():
        lines.append(buf.rstrip())
    return lines


def format_top_events_text(
    highlights: list[dict],
    top_n: int,
    types: list[str] | None,
) -> str:
    """Human-readable all-time top-events digest."""
    type_note = f" [{', '.join(sorted(types))}]" if types else ""
    header = f"Hermitcraft All-Time Top {top_n} Events{type_note}"
    lines: list[str] = [header, "=" * len(header), ""]

    if not highlights:
        lines.append("  No events found.")
        return "\n".join(lines)

    for entry in highlights:
        rank = entry["rank"]
        season = entry.get("season", "?")
        ev_type = entry.get("type", "")
        title = entry["title"]
        date = entry.get("date", "")
        hermits = entry.get("hermits", [])
        desc = entry.get("description", "")
        score = entry.get("significance_score", 0)

        type_tag = f"[{ev_type}]" if ev_type else ""
        lines.append(f" {rank:2d}. {type_tag}  S{season}  {title}")
        lines.append(
            f"     {date}  ·  {_hermit_str(hermits)}  (score: {score})"
        )
        lines.extend(_wrap_desc(desc))
        lines.append("")

    return "\n".join(lines).rstrip()


def format_hall_of_fame_text(
    entries: list[dict],
    types: list[str] | None,
) -> str:
    """Human-readable Hall of Fame — one peak event per season."""
    type_note = f" [{', '.join(sorted(types))}]" if types else ""
    header = f"Hermitcraft Hall of Fame — Best Event Per Season{type_note}"
    lines: list[str] = [header, "=" * len(header), ""]

    if not entries:
        lines.append("  No events found.")
        return "\n".join(lines)

    for entry in entries:
        season = entry["season"]
        ev_type = entry.get("type", "")
        title = entry["title"]
        date = entry.get("date", "")
        hermits = entry.get("hermits", [])
        desc = entry.get("description", "")
        score = entry.get("significance_score", 0)

        type_tag = f"[{ev_type}]" if ev_type else ""
        lines.append(f"  S{season:2d}  {type_tag}  {title}")
        lines.append(
            f"       {date}  ·  {_hermit_str(hermits)}  (score: {score})"
        )
        lines.extend(_wrap_desc(desc, indent="       "))
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.all_time_highlights",
        description=(
            "Cross-season Hermitcraft highlights: all-time top events or "
            "Hall of Fame (best event per season).  Events are ranked by a "
            "documented significance score — see module docstring."
        ),
    )
    mode_group = p.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--top-events",
        action="store_true",
        help="Show the top N events ranked across ALL seasons simultaneously",
    )
    mode_group.add_argument(
        "--hall-of-fame",
        action="store_true",
        help=(
            "Show the single best event for each season (one per season, "
            "sorted chronologically)"
        ),
    )
    p.add_argument(
        "--top",
        type=int,
        default=_DEFAULT_TOP_N,
        metavar="N",
        help=f"Number of results for --top-events (default: {_DEFAULT_TOP_N})",
    )
    p.add_argument(
        "--types",
        nargs="+",
        metavar="TYPE",
        choices=list(_TYPE_SCORE.keys()),
        help=(
            "Filter to specific event types: "
            + ", ".join(_TYPE_SCORE.keys())
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    types: list[str] | None = args.types or None

    if args.top_events:
        highlights = rank_all_time_highlights(top_n=args.top, types=types)
        if args.json:
            print(
                json.dumps(
                    build_top_events_output(highlights, args.top, types),
                    indent=2,
                )
            )
        else:
            print(format_top_events_text(highlights, args.top, types))

    else:  # --hall-of-fame
        entries = build_hall_of_fame(types=types)
        if args.json:
            print(
                json.dumps(
                    build_hall_of_fame_output(entries, types),
                    indent=2,
                )
            )
        else:
            print(format_hall_of_fame_text(entries, types))

    return 0


if __name__ == "__main__":
    sys.exit(main())
