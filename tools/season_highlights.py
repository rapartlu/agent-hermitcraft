"""
tools/season_highlights.py — Curated top-moments digest per Hermitcraft season.

Ranks every timeline event for a season by a documented significance score and
returns the top N as a shareable highlights list — the fastest way for casual
fans to get the 'best of' a season without reading a full recap.

Significance scoring (fully documented):
  Type bonus:
    milestone  +10  (season-defining moments)
    lore       +8   (major story / roleplay events)
    game       +7   (server-wide game shows and challenges)
    collab     +6   (inter-hermit collaborations)
    build      +5   (notable construction projects)
    meta       +1   (server metadata — lowest casual-fan interest)
  Hermit-count bonus:
    hermits == ["All"]  +3  (server-wide events are broadly significant)
    4+ named hermits    +2  (large group involvement)
    2–3 named hermits   +1  (any collaboration)
  Date-precision bonus:
    date_precision == "day"  +1  (well-documented events tend to be notable)

Ties in significance score are broken chronologically (earlier events first).

Usage:
    python -m tools.season_highlights --season 9
    python -m tools.season_highlights --season 9 --top 5
    python -m tools.season_highlights --season 9 --json
    python -m tools.season_highlights --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SEASONS_DIR = Path(__file__).parent.parent / "knowledge" / "seasons"
EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"
)
VIDEO_EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "video_events.json"
)

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


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

def _load_all_events() -> list[dict]:
    events: list[dict] = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return events


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
# Core ranking
# ---------------------------------------------------------------------------

def rank_season_highlights(season: int, top_n: int = 10) -> list[dict]:
    """
    Return the top *top_n* events for *season*, ranked by significance score.

    Each returned dict contains:
        rank, title, description, date, type, hermits, significance_score

    Ties in significance score are broken chronologically (earlier first).

    Returns an empty list when the season has no events in the data files.
    """
    all_events = _load_all_events()
    season_events = [ev for ev in all_events if ev.get("season") == season]

    # Annotate with (score, chronological_key) for stable sorting
    scored = [
        (significance_score(ev), _event_sort_key(ev), ev)
        for ev in season_events
    ]
    # Highest score first; chronological order breaks ties
    scored.sort(key=lambda x: (-x[0], x[1]))

    highlights: list[dict] = []
    for rank, (score, _, ev) in enumerate(scored[:top_n], start=1):
        highlights.append(
            {
                "rank": rank,
                "title": ev.get("title", "(untitled)"),
                "description": ev.get("description", ""),
                "date": ev.get("date", ""),
                "type": ev.get("type", ""),
                "hermits": ev.get("hermits", []),
                "significance_score": score,
            }
        )
    return highlights


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def build_highlights_output(season: int, highlights: list[dict], top_n: int) -> dict:
    """
    Assemble the structured output dict.

    Mirrors the shape of ``GET /seasons/:id/highlights``:
        {season, highlight_count, top_n_requested, events: [...]}
    """
    return {
        "season": season,
        "highlight_count": len(highlights),
        "top_n_requested": top_n,
        "events": highlights,
    }


def format_highlights_text(season: int, highlights: list[dict], top_n: int) -> str:
    """Format highlights as a human-readable digest."""
    header = f"Season {season} Highlights  (top {top_n})"
    lines: list[str] = [header, "=" * len(header), ""]

    if not highlights:
        lines.append("  No events found for this season.")
        return "\n".join(lines)

    for entry in highlights:
        rank = entry["rank"]
        ev_type = entry.get("type", "")
        title = entry["title"]
        date = entry.get("date", "")
        hermits = entry.get("hermits", [])
        desc = entry.get("description", "")
        score = entry.get("significance_score", 0)

        if hermits == ["All"]:
            hermit_str = "All hermits"
        else:
            hermit_str = ", ".join(hermits[:3]) + (" …" if len(hermits) > 3 else "")

        type_tag = f"[{ev_type}]" if ev_type else ""
        lines.append(f" {rank:2d}. {type_tag}  {title}")
        lines.append(f"     {date}  ·  {hermit_str}  (score: {score})")

        if desc:
            words = desc.split()
            line_buf = "     "
            for word in words:
                if len(line_buf) + len(word) + 1 > 72:
                    lines.append(line_buf.rstrip())
                    line_buf = "     " + word
                else:
                    if line_buf.strip():
                        line_buf = line_buf + " " + word
                    else:
                        line_buf = line_buf + word
            if line_buf.strip():
                lines.append(line_buf.rstrip())

        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.season_highlights",
        description=(
            "Show the top N most significant events for a Hermitcraft season. "
            "Events are ranked by a documented significance score — see module "
            "docstring for the full breakdown."
        ),
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Season number (1–11)",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List available season numbers and exit",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="How many highlights to return (default: 10)",
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

    if args.list:
        print("Available seasons:", ", ".join(str(s) for s in KNOWN_SEASONS))
        return 0

    season = args.season
    if season not in KNOWN_SEASONS:
        print(
            f"[season_highlights] Season {season} not found. "
            f"Available seasons: {', '.join(str(s) for s in KNOWN_SEASONS)}",
            file=sys.stderr,
        )
        return 1

    highlights = rank_season_highlights(season, top_n=args.top)

    if args.json:
        print(
            json.dumps(
                build_highlights_output(season, highlights, args.top), indent=2
            )
        )
    else:
        print(format_highlights_text(season, highlights, args.top))

    return 0


if __name__ == "__main__":
    sys.exit(main())
