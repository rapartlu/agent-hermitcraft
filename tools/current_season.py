#!/usr/bin/env python3
"""
tools/current_season.py — "What's happening now in Hermitcraft?" summary.

Returns the active season's metadata, the 5 most recent timeline events,
and a one-paragraph narrative summary — all without requiring any input
parameters.

HTTP API
--------
  GET /seasons/current
  Returns JSON with the same structure as --json output.

CLI usage
---------
  python -m tools.current_season
  python -m tools.current_season --json
  python -m tools.current_season --top 10

Output
------
  Text (default):
    ═══ HERMITCRAFT — WHAT'S HAPPENING NOW ═══
    Season 11 · Minecraft 1.21.11 · ONGOING
    Started: November 8, 2025  (N weeks in)
    Members: 25

    Recent events (latest first):
      …

    Summary:
      …

  JSON (--json):
    {
      "season": 11,
      "status": "ongoing",
      "start_date": "2025-11-08",
      "weeks_in": N,
      "minecraft_version": "…",
      "member_count": 25,
      "theme": "…",
      "members": […],
      "recent_events": […],
      "narrative": "…"
    }

Exit codes
----------
  0   success
  1   no ongoing season found (all seasons have ended)
  2   data files missing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.season_recap import (  # noqa: E402
    build_recap,
    KNOWN_SEASONS,
    SEASONS_DIR,
    _parse_frontmatter,
)

EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "events.json"
VIDEO_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "video_events.json"

# Injected today's date — override in tests via current_season._TODAY
_TODAY: date | None = None


def _today() -> date:
    return _TODAY if _TODAY is not None else date.today()


# ---------------------------------------------------------------------------
# Season detection
# ---------------------------------------------------------------------------

def find_current_season() -> int | None:
    """
    Return the season number of the currently *ongoing* season, or the most
    recently ended season if none is ongoing.

    Scans ``knowledge/seasons/season-N.md`` frontmatter for ``status: ongoing``.
    Falls back to the season with the latest ``start_date`` if no ongoing
    season is found.

    Returns None only if the seasons directory is empty or unreadable.
    """
    ongoing: list[tuple[str, int]] = []   # (start_date, season_num)
    ended: list[tuple[str, int]] = []

    for path in SEASONS_DIR.glob("season-*.md"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(content)
        try:
            season_num = int(fm.get("season", "0"))
        except ValueError:
            continue
        status = fm.get("status", "").lower()
        start = fm.get("start_date", "")
        if "ongoing" in status:
            ongoing.append((start, season_num))
        else:
            ended.append((start, season_num))

    if ongoing:
        # If multiple ongoing (shouldn't happen), pick the one that started latest
        ongoing.sort(reverse=True)
        return ongoing[0][1]

    if ended:
        ended.sort(reverse=True)
        return ended[0][1]

    return None


# ---------------------------------------------------------------------------
# Weeks-in calculation
# ---------------------------------------------------------------------------

def _weeks_in(start_date_str: str) -> int | None:
    """Return the number of complete weeks since the season started, or None."""
    if not start_date_str:
        return None
    try:
        start = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
        delta = _today() - start
        return max(0, delta.days // 7)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Recent events
# ---------------------------------------------------------------------------

def _load_season_events(season: int) -> list[dict]:
    """Load and return events for *season*, sorted newest-first."""
    all_events: list[dict] = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                all_events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass

    season_events = [e for e in all_events if e.get("season") == season]

    def _sort_key(ev: dict) -> tuple:
        parts = ev.get("date", "").split("-")
        try:
            return (
                int(parts[0]) if len(parts) > 0 else 0,
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except (ValueError, IndexError):
            return (0, 0, 0)

    season_events.sort(key=_sort_key, reverse=True)
    return season_events


# ---------------------------------------------------------------------------
# Narrative builder
# ---------------------------------------------------------------------------

def _build_narrative(recap: dict, recent_events: list[dict]) -> str:
    """
    Synthesise a one-paragraph narrative from available season data.
    No external calls — uses only the knowledge base.
    """
    season = recap.get("season", "?")
    status = recap.get("status", "")
    theme = recap.get("theme", "")
    member_count = recap.get("member_count", 0)
    start_date = recap.get("start_date", "")
    themes = recap.get("key_themes", [])
    notable = recap.get("notable_events", [])
    weeks = _weeks_in(start_date)

    parts: list[str] = []

    # Opening
    if "ongoing" in status.lower():
        time_ctx = f"{weeks} weeks in" if weeks else "currently running"
        parts.append(
            f"Hermitcraft Season {season} is live and {time_ctx}, "
            f"with {member_count} Hermits on the server."
        )
    else:
        parts.append(
            f"Hermitcraft Season {season} has ended, "
            f"with {member_count} participants."
        )

    # Theme / headline
    if theme:
        # Pull first meaningful phrase before a semicolon
        headline = theme.split(";")[0].strip()
        parts.append(f"The headline project this season is {headline}.")

    # Key themes (first 2)
    if themes:
        clean = [re.sub(r"\*\*([^*]+)\*\*", r"\1", t).split("—")[0].strip()
                 for t in themes[:2]]
        parts.append("Active storylines include " + " and ".join(clean) + ".")

    # Recent events (first 2)
    if recent_events:
        ev_titles = [e.get("title", "") for e in recent_events[:2] if e.get("title")]
        if ev_titles:
            parts.append(
                "Most recently: " + "; ".join(ev_titles) + "."
            )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main data builder
# ---------------------------------------------------------------------------

def get_current_season_status(top_events: int = 5) -> dict | None:
    """
    Return a dict describing the current (or most recent) Hermitcraft season.

    Keys:
        season, status, start_date, end_date, weeks_in,
        minecraft_version, member_count, theme, members,
        key_themes, notable_events, recent_events, narrative

    Returns None if no season data is found.
    """
    season_num = find_current_season()
    if season_num is None:
        return None

    recap = build_recap(season_num)
    recent = _load_season_events(season_num)[:top_events]

    # Slim down recent events for the output (drop large description blobs)
    slim_events = [
        {
            "date": e.get("date", ""),
            "title": e.get("title", ""),
            "type": e.get("type", ""),
            "hermits": e.get("hermits", []),
            "description": (e.get("description") or "")[:200],
        }
        for e in recent
    ]

    narrative = _build_narrative(recap, recent)

    return {
        "season": season_num,
        "status": recap.get("status", ""),
        "start_date": recap.get("start_date", ""),
        "end_date": recap.get("end_date") or None,
        "weeks_in": _weeks_in(recap.get("start_date", "")),
        "minecraft_version": recap.get("minecraft_version", ""),
        "member_count": recap.get("member_count", 0),
        "theme": recap.get("theme", ""),
        "members": recap.get("members", []),
        "key_themes": recap.get("key_themes", []),
        "notable_events": recap.get("notable_events", []),
        "recent_events": slim_events,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def _hr(char: str = "═", width: int = 60) -> str:
    return char * width


def format_status(status: dict) -> str:
    """Return a human-readable current-season summary."""
    lines: list[str] = []
    season = status["season"]
    mc = status.get("minecraft_version", "?")
    stat = status.get("status", "").upper()
    start = status.get("start_date", "?")
    weeks = status.get("weeks_in")
    members = status.get("member_count", 0)
    theme = status.get("theme", "")

    lines.append(_hr())
    lines.append(f"  HERMITCRAFT — WHAT'S HAPPENING NOW")
    lines.append(_hr())
    lines.append("")
    lines.append(f"  Season {season}  ·  Minecraft {mc}  ·  {stat}")
    lines.append(f"  Started: {start}" + (f"  ({weeks} weeks in)" if weeks else ""))
    lines.append(f"  Members: {members}")
    if theme:
        lines.append(f"  Theme:   {theme}")

    # Recent events
    events = status.get("recent_events", [])
    if events:
        lines.append("")
        lines.append(f"  Recent events (latest first):")
        for ev in events:
            date_str = ev.get("date", "?")
            title = ev.get("title", "(untitled)")
            ev_type = ev.get("type", "")
            hermits = ev.get("hermits", [])
            tag = f"[{ev_type}] " if ev_type else ""
            hermit_str = (
                "  — " + ", ".join(hermits[:3])
                + (" +more" if len(hermits) > 3 else "")
                if hermits and hermits != ["All"]
                else ""
            )
            lines.append(f"    {date_str}  {tag}{title}{hermit_str}")

    # Narrative
    narrative = status.get("narrative", "")
    if narrative:
        lines.append("")
        lines.append("  Summary:")
        # Word-wrap at 72 chars
        words = narrative.split()
        row = "    "
        for word in words:
            if len(row) + len(word) + 1 > 74:
                lines.append(row.rstrip())
                row = "    " + word
            else:
                row = (row + " " + word) if row.strip() else "    " + word
        if row.strip():
            lines.append(row.rstrip())

    lines.append("")
    lines.append(_hr())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="current_season",
        description="Show what's currently happening in Hermitcraft.",
    )
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="Output machine-readable JSON.")
    p.add_argument("--top", type=int, default=5, metavar="N",
                   help="Number of recent events to include (default: 5).")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    status = get_current_season_status(top_events=args.top)
    if status is None:
        print("[current_season] No season data found.", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(format_status(status))

    return 0


if __name__ == "__main__":
    sys.exit(main())
