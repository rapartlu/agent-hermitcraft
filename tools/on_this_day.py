#!/usr/bin/env python3
"""
On This Day in Hermitcraft
==========================
Return Hermitcraft events that happened on or near a given month/day,
across all seasons and years — like a "Hermitcraft history digest".

Usage
-----
  python3 tools/on_this_day.py                          # today's date
  python3 tools/on_this_day.py --month 4 --day 13       # April 13 (server founding!)
  python3 tools/on_this_day.py --month 6 --day 17       # June 17 (Season 7 launch)
  python3 tools/on_this_day.py --window 3               # ±3 day window (default 7)
  python3 tools/on_this_day.py --no-approximate              # exclude approximate-precision events
  python3 tools/on_this_day.py --include-year                # include year-only events
  python3 tools/on_this_day.py --include-hermit-anniversaries  # add hermit join/YT anniversaries
  python3 tools/on_this_day.py --pretty                      # indented JSON array output

Date precision handling
-----------------------
  day          — matched within the ±window
  approximate  — matched within the ±window (included by default; skip with
                  --no-approximate)
  month        — matched if the target month equals the event month
  year         — skipped by default; use --include-year to include all

Output
------
Newline-delimited JSON objects (NDJSON) sorted oldest-year-first.
Use --pretty for a formatted JSON array.

Exit codes
----------
  0  success (≥1 results)
  1  no events match
  2  bad arguments or events file not found
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

EVENTS_FILE = Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"
HERMITS_DIR = Path(__file__).parent.parent / "knowledge" / "hermits"

# Day-of-year matching window in days (default)
DEFAULT_WINDOW = 7


def load_events(path: Path = EVENTS_FILE) -> list[dict]:
    """Load and return the events JSON array."""
    if not path.exists():
        sys.stderr.write(f"[on_this_day] events file not found: {path}\n")
        sys.exit(2)
    try:
        with path.open() as fh:
            events = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[on_this_day] malformed JSON in {path}: {exc}\n")
        sys.exit(2)
    if not isinstance(events, list):
        sys.stderr.write("[on_this_day] events file must be a JSON array\n")
        sys.exit(2)
    return events


def _parse_event_date(event: dict) -> tuple[int | None, int | None, int | None]:
    """
    Return (year, month, day) extracted from the event's date string.
    Missing parts are returned as None.
    """
    raw: str = event.get("date", "")
    parts = raw.split("-")
    year = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else None
    month = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    day = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None
    return year, month, day


def _day_of_year(month: int, day: int, leap: bool = False) -> int:
    """Return the day-of-year (1-based) for a given month/day.

    Raises ValueError for invalid month/day combinations (e.g. month=13,
    day=32, or Feb 30) so callers can decide how to handle bad data.
    """
    # Use a known leap or non-leap year for calculation
    year = 2000 if leap else 2001
    return date(year, month, day).timetuple().tm_yday


def _circular_distance(doy_a: int, doy_b: int, year_len: int = 365) -> int:
    """Minimum circular distance between two day-of-year values."""
    diff = abs(doy_a - doy_b)
    return min(diff, year_len - diff)


def matches_on_this_day(
    event: dict,
    target_month: int,
    target_day: int,
    window: int = DEFAULT_WINDOW,
    include_approximate: bool = True,
    include_year: bool = False,
) -> bool:
    """
    Return True if the event falls within the matching criteria for
    the given (target_month, target_day).
    """
    precision = event.get("date_precision", "day")
    year, month, day = _parse_event_date(event)

    if precision == "year":
        return include_year  # year-only events: opt-in

    if precision == "month":
        # Match if the event month equals the target month
        return month is not None and month == target_month

    if precision == "approximate" and not include_approximate:
        return False

    # For "day" and "approximate" (when included): day-of-year distance
    if month is None or day is None:
        return False

    try:
        event_doy = _day_of_year(month, day)
    except ValueError:
        # Malformed date in event data (e.g. month=13 or Feb 30) — skip
        return False

    try:
        target_doy = _day_of_year(target_month, target_day)
    except ValueError:
        # Invalid target date — skip (main() validates this before calling)
        return False

    return _circular_distance(event_doy, target_doy) <= window


def find_on_this_day(
    events: list[dict],
    target_month: int,
    target_day: int,
    window: int = DEFAULT_WINDOW,
    include_approximate: bool = True,
    include_year: bool = False,
) -> list[dict]:
    """
    Return all events that match the given month/day within window,
    sorted oldest-year-first (then by season, then by id).
    """
    results = [
        e for e in events
        if matches_on_this_day(
            e,
            target_month,
            target_day,
            window=window,
            include_approximate=include_approximate,
            include_year=include_year,
        )
    ]
    # Sort: year ascending, then season, then id
    def sort_key(e: dict) -> tuple:
        year, month, day = _parse_event_date(e)
        return (year or 9999, e.get("season", 0), e.get("id", ""))

    return sorted(results, key=sort_key)


def _parse_frontmatter(content: str) -> dict[str, str]:
    """
    Extract flat scalar fields from YAML frontmatter delimited by ``---``.

    Only handles simple ``key: value`` lines (no lists, no nested mappings).
    Quoted values have their surrounding quotes stripped.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    fm_text = content[4:end]
    result: dict[str, str] = {}
    for line in fm_text.splitlines():
        # Skip list items, indented lines, and blank lines
        if not line or line.startswith(" ") or line.startswith("-"):
            continue
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        value = raw_value.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result


def _infer_precision(date_str: str) -> str:
    """Infer date_precision from a date string (YYYY, YYYY-MM, or YYYY-MM-DD)."""
    parts = date_str.split("-")
    if len(parts) == 3:
        return "day"
    if len(parts) == 2:
        return "month"
    return "year"


def load_hermit_profiles(directory: Path = HERMITS_DIR) -> list[dict[str, str]]:
    """
    Scan ``knowledge/hermits/*.md`` and return a list of frontmatter dicts
    for profiles that have at least a ``name`` field.
    """
    profiles: list[dict[str, str]] = []
    if not directory.exists():
        return profiles
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            fm = _parse_frontmatter(path.read_text())
        except OSError:
            continue
        if fm.get("name"):
            profiles.append(fm)
    return profiles


def synthesise_hermit_events(profiles: list[dict[str, str]]) -> list[dict]:
    """
    Build virtual event dicts from hermit profile frontmatter fields:

    * ``join_date``         → "``{Name}`` Joins Hermitcraft" milestone
    * ``yt_channel_start``  → "``{Name}`` Starts YouTube Channel" milestone

    Synthesised events carry ``"source": "hermit_profile"`` so callers can
    distinguish them from timeline data.
    """
    events: list[dict] = []
    for fm in profiles:
        name = fm.get("name", "")
        slug = re.sub(r"[^a-z0-9]", "", name.lower())
        joined_season_raw = fm.get("joined_season", "0")
        try:
            joined_season = int(joined_season_raw)
        except ValueError:
            joined_season = 0

        join_date = fm.get("join_date", "")
        if join_date:
            precision = _infer_precision(join_date)
            year_str = join_date.split("-")[0]
            season_label = f"Season {joined_season}" if joined_season else "Hermitcraft"
            events.append({
                "id": f"hermit-{slug}-join",
                "date": join_date,
                "date_precision": precision,
                "season": joined_season,
                "hermits": [name],
                "type": "milestone",
                "title": f"{name} Joins Hermitcraft",
                "description": (
                    f"{name} joins Hermitcraft for the first time in {season_label} ({year_str})."
                ),
                "source": "hermit_profile",
            })

        yt_start = fm.get("yt_channel_start", "")
        if yt_start:
            precision = _infer_precision(yt_start)
            events.append({
                "id": f"hermit-{slug}-yt",
                "date": yt_start,
                "date_precision": precision,
                "season": 0,
                "hermits": [name],
                "type": "milestone",
                "title": f"{name} Starts YouTube Channel",
                "description": (
                    f"{name} creates their YouTube channel ({yt_start}),"
                    " later becoming a member of Hermitcraft."
                ),
                "source": "hermit_profile",
            })

    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="On This Day in Hermitcraft — historical event digest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--month", type=int, metavar="M",
        help="Month number (1–12). Defaults to today's month.",
    )
    parser.add_argument(
        "--day", type=int, metavar="D",
        help="Day of month (1–31). Defaults to today's day.",
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW, metavar="DAYS",
        help=f"Match events within ±DAYS of the target date (default: {DEFAULT_WINDOW}).",
    )
    parser.add_argument(
        "--no-approximate", dest="include_approximate",
        action="store_false", default=True,
        help="Exclude events with approximate date precision.",
    )
    parser.add_argument(
        "--include-year", action="store_true", default=False,
        help="Include events that only have year-level precision.",
    )
    parser.add_argument(
        "--include-hermit-anniversaries", action="store_true", default=False,
        help=(
            "Synthesise hermit join and YouTube-channel anniversary events "
            "from hermit profiles and include them in results."
        ),
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Output a pretty-printed JSON array instead of NDJSON.",
    )

    args = parser.parse_args(argv)

    today = date.today()
    target_month = args.month if args.month is not None else today.month
    target_day = args.day if args.day is not None else today.day

    # Validate month/day using a non-leap year so that Feb 29 is rejected
    # with a clear error. This is intentional: Feb 29 only exists in leap
    # years so a "day of year" comparison against non-leap event dates would
    # be ambiguous. Users can query Feb 28 or Mar 1 instead.
    try:
        date(2001, target_month, target_day)
    except ValueError as exc:
        sys.stderr.write(f"[on_this_day] invalid date: {exc}\n")
        return 2

    events = load_events()

    if args.include_hermit_anniversaries:
        profiles = load_hermit_profiles()
        events = events + synthesise_hermit_events(profiles)

    results = find_on_this_day(
        events,
        target_month=target_month,
        target_day=target_day,
        window=args.window,
        include_approximate=args.include_approximate,
        include_year=args.include_year,
    )

    if not results:
        sys.stderr.write(
            f"[on_this_day] no events found for "
            f"{target_month:02d}-{target_day:02d} (±{args.window} days)\n"
        )
        return 1

    if args.pretty:
        print(json.dumps(results, indent=2))
    else:
        for event in results:
            print(json.dumps(event))

    return 0


if __name__ == "__main__":
    sys.exit(main())
