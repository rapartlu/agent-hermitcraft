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
  python3 tools/on_this_day.py --all-events                         # enable all event sources (recommended)
  python3 tools/on_this_day.py --no-approximate                # exclude approximate-precision events
  python3 tools/on_this_day.py --include-year                  # include year-only events
  python3 tools/on_this_day.py --include-hermit-anniversaries  # add hermit join/YT/subscriber anniversaries
  python3 tools/on_this_day.py --include-video-events          # add notable video/stream milestone events
  python3 tools/on_this_day.py --digest                        # human-readable text digest (bot/Discord-ready)
  python3 tools/on_this_day.py --pretty                        # indented JSON array output

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
Use --digest for a human-readable text digest suitable for bots or terminals.

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
VIDEO_EVENTS_FILE = Path(__file__).parent.parent / "knowledge" / "timelines" / "video_events.json"
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


def _parse_frontmatter(content: str) -> dict:
    """
    Extract fields from YAML frontmatter delimited by ``---``.

    Handles:
    * Simple ``key: value`` scalar lines.
    * Inline list-of-dicts for ``subscriber_milestones``, e.g.::

        subscriber_milestones:
          - { date: "2019-03", count: "5M" }

    Quoted values have their surrounding quotes stripped.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    fm_text = content[4:end]
    result: dict = {}
    current_list_key: str | None = None
    for line in fm_text.splitlines():
        # Blank line — reset list context
        if not line.strip():
            current_list_key = None
            continue

        # Indented list item under a known list key
        if line.startswith("  ") or line.startswith("\t"):
            stripped = line.strip()
            if current_list_key and stripped.startswith("- {") and stripped.endswith("}"):
                # Parse inline dict: - { key: "val", key2: "val2" }
                inner = stripped[2:].strip().lstrip("{").rstrip("}")
                item: dict[str, str] = {}
                for pair in inner.split(","):
                    pair = pair.strip()
                    if ":" not in pair:
                        continue
                    k, _, v = pair.partition(":")
                    item[k.strip()] = v.strip().strip('"').strip("'")
                if item:
                    result.setdefault(current_list_key, []).append(item)
            continue

        # Top-level list header (``key:`` with no value)
        if ":" not in line:
            current_list_key = None
            continue

        key, _, raw_value = line.partition(":")
        value = raw_value.strip().strip('"').strip("'")
        if value:
            current_list_key = None
            result[key.strip()] = value
        else:
            # No value → could be a list header
            current_list_key = key.strip()

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


def synthesise_hermit_events(profiles: list[dict]) -> list[dict]:
    """
    Build virtual event dicts from hermit profile frontmatter fields:

    * ``join_date``              → "``{Name}`` Joins Hermitcraft" milestone
    * ``yt_channel_start``       → "``{Name}`` Starts YouTube Channel" milestone
    * ``subscriber_milestones``  → "``{Name}`` Reaches {count} Subscribers" milestone
                                   (one event per entry in the list)

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

        sub_milestones = fm.get("subscriber_milestones", [])
        if isinstance(sub_milestones, list):
            for entry in sub_milestones:
                if not isinstance(entry, dict):
                    continue
                ms_date = entry.get("date", "")
                ms_count = entry.get("count", "")
                if not ms_date or not ms_count:
                    continue
                precision = _infer_precision(ms_date)
                count_slug = re.sub(r"[^a-z0-9]", "", ms_count.lower())
                events.append({
                    "id": f"hermit-{slug}-subs-{count_slug}",
                    "date": ms_date,
                    "date_precision": precision,
                    "season": 0,
                    "hermits": [name],
                    "type": "milestone",
                    "title": f"{name} Reaches {ms_count} Subscribers",
                    "description": (
                        f"{name} reaches {ms_count} subscribers on YouTube ({ms_date})."
                    ),
                    "source": "hermit_profile",
                })

    return events


def filter_by_hermit(events: list[dict], hermit_name: str) -> list[dict]:
    """
    Return only those *events* that involve *hermit_name*.

    An event matches when:
    * ``event["hermits"]`` equals ``["All"]`` (server-wide events), OR
    * *hermit_name* appears in ``event["hermits"]`` (case-insensitive).

    An empty hermit list does **not** match, since the event's participants
    are genuinely unknown.
    """
    name_lower = hermit_name.lower()
    result = []
    for ev in events:
        hermits: list = ev.get("hermits", [])
        if hermits == ["All"]:
            result.append(ev)
        elif any(h.lower() == name_lower for h in hermits):
            result.append(ev)
    return result


_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def format_digest(events: list[dict], month: int, day: int) -> str:
    """
    Return a human-readable "On This Day" digest string.

    Suitable for terminal output, daily bots, or Discord posts.
    Each event block shows: year, season, type, title, hermits,
    and a word-wrapped description.

    If *events* is empty a friendly "quiet day" message is returned;
    the caller is still responsible for returning exit code 1.
    """
    hr_heavy = "═" * 60
    hr_light = "─" * 58

    month_name = _MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
    date_label = f"{month_name} {day}"

    lines: list[str] = []
    lines.append(hr_heavy)
    lines.append("  ON THIS DAY IN HERMITCRAFT")
    lines.append(f"  {date_label}")
    lines.append(hr_heavy)

    if not events:
        lines.append("")
        lines.append("  Nothing recorded in Hermitcraft history for this date.")
        lines.append("  (Try --all-events or widen with --window)")
        lines.append("")
        lines.append(hr_heavy)
        return "\n".join(lines)

    for ev in events:
        year, *_ = ev.get("date", "").split("-") + [""]
        season = ev.get("season", 0)
        ev_type = ev.get("type", "")
        title = ev.get("title", "")
        hermits: list = ev.get("hermits", [])
        description = ev.get("description", "")

        year_label = f"[{year}]" if year and year.isdigit() else "[?]"
        season_label = f"Season {season}" if season else "pre-Hermitcraft"
        type_label = ev_type if ev_type else "event"
        hermit_str = ", ".join(hermits) if hermits else "unknown"

        lines.append("")
        lines.append(f"  {year_label}  {season_label}  ·  {type_label}")
        lines.append(f"  {title}")
        lines.append(f"  Hermits: {hermit_str}")
        lines.append("  " + hr_light)

        # Word-wrap description to ~76 chars
        if description:
            words = description.split()
            row = ""
            for w in words:
                if len(row) + len(w) + 1 > 74:
                    lines.append("  " + row)
                    row = w
                else:
                    row = (row + " " + w).strip()
            if row:
                lines.append("  " + row)

        lines.append("  " + hr_light)

    lines.append("")
    count = len(events)
    lines.append(hr_heavy)
    lines.append(f"  {count} event{'s' if count != 1 else ''} found")
    lines.append(hr_heavy)
    return "\n".join(lines)


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
            "Synthesise hermit join, YouTube-channel, and subscriber-milestone "
            "anniversary events from hermit profiles and include them in results."
        ),
    )
    parser.add_argument(
        "--include-video-events", action="store_true", default=False,
        help=(
            "Include notable per-hermit video and stream milestone events "
            "(e.g. first season episodes, iconic builds, major server events). "
            "Loaded from knowledge/timelines/video_events.json."
        ),
    )
    parser.add_argument(
        "--all-events", action="store_true", default=False,
        help=(
            "Enable all event sources (recommended for first use). "
            "Sets --include-year, --include-hermit-anniversaries, and "
            "--include-video-events to True."
        ),
    )
    parser.add_argument(
        "--hermit", metavar="NAME", default=None,
        help=(
            "Filter results to events involving a specific hermit (case-insensitive). "
            "Server-wide events (hermits=[All]) are always included."
        ),
    )
    parser.add_argument(
        "--digest", action="store_true",
        help=(
            "Output a human-readable text digest instead of JSON. "
            "Suitable for terminal display, daily bots, or Discord posts. "
            "Prints a friendly 'nothing found' message (exit 1) on empty results."
        ),
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Output a pretty-printed JSON array instead of NDJSON.",
    )

    args = parser.parse_args(argv)

    # --all-events overrides individual include flags
    if args.all_events:
        args.include_year = True
        args.include_hermit_anniversaries = True
        args.include_video_events = True

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

    if args.include_video_events:
        events = events + load_events(VIDEO_EVENTS_FILE)

    results = find_on_this_day(
        events,
        target_month=target_month,
        target_day=target_day,
        window=args.window,
        include_approximate=args.include_approximate,
        include_year=args.include_year,
    )

    if args.hermit is not None:
        results = filter_by_hermit(results, args.hermit)

    if not results:
        if args.digest:
            print(format_digest([], target_month, target_day))
        else:
            sys.stderr.write(
                f"[on_this_day] no events found for "
                f"{target_month:02d}-{target_day:02d} (±{args.window} days)\n"
            )
        return 1

    if args.digest:
        print(format_digest(results, target_month, target_day))
    elif args.pretty:
        print(json.dumps(results, indent=2))
    else:
        for event in results:
            print(json.dumps(event))

    return 0


if __name__ == "__main__":
    sys.exit(main())
