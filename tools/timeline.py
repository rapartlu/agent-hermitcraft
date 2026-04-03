#!/usr/bin/env python3
"""
Hermitcraft Season Timeline & Event Lookup
==========================================
Query structured Hermitcraft timeline events by season, hermit, type,
or free-text keyword search.

Usage
-----
  python3 tools/timeline.py                              # all events, chronological
  python3 tools/timeline.py --season 7                  # Season 7 only
  python3 tools/timeline.py --hermit Grian              # all Grian events
  python3 tools/timeline.py --type build                # all build events
  python3 tools/timeline.py --search "demise"           # keyword search
  python3 tools/timeline.py --season 6 --hermit Iskall85
  python3 tools/timeline.py --season 8 --type milestone
  python3 tools/timeline.py --stats                     # summary stats
  python3 tools/timeline.py --limit 10 --offset 20     # paginated slice

Filters can be combined; all supplied filters must match (AND logic).
Keyword search checks title, description, and hermit names.

Pagination
----------
Use --limit N (default 20, max 100) and --offset N (default 0) to page
through results.  When either flag is given the output is a JSON envelope:
  {"total": <int>, "limit": <int>, "offset": <int>, "items": [...]}
An offset beyond the total returns an empty items array (not an error).

Output
------
Without pagination flags: newline-delimited JSON objects (one per line)
so results pipe cleanly into `jq`.  Use --pretty for indented JSON array.
With pagination flags: always a single JSON envelope object.

Exit codes
----------
  0  success (≥1 results, or paginated response)
  1  no events match the given filters (non-paginated mode only)
  2  bad arguments or events file not found
"""

import argparse
import json
import re
import sys
from pathlib import Path

EVENTS_FILE = Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


def paginate(items: list, limit: int, offset: int) -> dict:
    """
    Return a pagination envelope for *items*.

    Args:
        items:   The full (already-filtered) list to page.
        limit:   Maximum number of items to return (capped at _MAX_LIMIT).
        offset:  Zero-based starting index.  Values beyond len(items) return
                 an empty ``items`` list — never an error.

    Returns::

        {
            "total":  <int>,   # total number of matching items before slicing
            "limit":  <int>,   # effective limit (≤ _MAX_LIMIT)
            "offset": <int>,   # effective offset (≥ 0)
            "items":  [...]    # the sliced page
        }
    """
    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": items[offset: offset + limit],
    }

VALID_TYPES = {"build", "collab", "game", "lore", "meta", "milestone"}


def load_events(path: Path = EVENTS_FILE) -> list[dict]:
    """Load and return the events JSON array."""
    if not path.exists():
        sys.stderr.write(f"[timeline] events file not found: {path}\n")
        sys.exit(2)
    try:
        with path.open() as fh:
            events = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"[timeline] malformed JSON in {path}: {exc}\n")
        sys.exit(2)
    if not isinstance(events, list):
        sys.stderr.write("[timeline] events file must be a JSON array\n")
        sys.exit(2)
    return events


def _sort_key(event: dict) -> str:
    """Return a sortable string from the event date (pads partials to full ISO)."""
    date = event.get("date", "0000")
    # Pad year-only → "YYYY-01-01", year-month → "YYYY-MM-01"
    parts = date.split("-")
    while len(parts) < 3:
        parts.append("01")
    return "-".join(parts)


def filter_events(
    events: list[dict],
    season: int | None = None,
    hermit: str | None = None,
    event_type: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Return events matching all supplied filters, sorted chronologically."""
    result = events

    if season is not None:
        result = [e for e in result if e.get("season") == season]

    if hermit:
        hermit_lower = hermit.lower()
        result = [
            e for e in result
            if any(hermit_lower in h.lower() for h in e.get("hermits", []))
        ]

    if event_type:
        result = [e for e in result if e.get("type") == event_type]

    if search:
        pattern = re.compile(re.escape(search), re.IGNORECASE)
        result = [
            e for e in result
            if pattern.search(e.get("title", ""))
            or pattern.search(e.get("description", ""))
            or any(pattern.search(h) for h in e.get("hermits", []))
        ]

    return sorted(result, key=_sort_key)


def validate_event(e: dict) -> list[str]:
    """Return a list of schema errors for a single event dict."""
    errors: list[str] = []
    required = ("id", "date", "date_precision", "season", "hermits", "type", "title", "description", "source")
    for field in required:
        if field not in e:
            errors.append(f"missing field '{field}'")
    if "type" in e and e["type"] not in VALID_TYPES:
        errors.append(f"type must be one of {sorted(VALID_TYPES)}, got '{e['type']}'")
    if "hermits" in e and not isinstance(e["hermits"], list):
        errors.append("'hermits' must be an array")
    if "season" in e and not isinstance(e["season"], int):
        errors.append("'season' must be an integer")
    return errors


def print_stats(events: list[dict]) -> None:
    by_season: dict[int, int] = {}
    by_type: dict[str, int] = {}
    for e in events:
        s = e.get("season", 0)
        t = e.get("type", "unknown")
        by_season[s] = by_season.get(s, 0) + 1
        by_type[t] = by_type.get(t, 0) + 1
    stats = {
        "total_events": len(events),
        "by_season": {f"season_{k}": v for k, v in sorted(by_season.items())},
        "by_type": by_type,
    }
    print(json.dumps(stats, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hermitcraft Season Timeline & Event Lookup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--season", type=int, metavar="N",
        help="Filter by season number (e.g. --season 7)",
    )
    parser.add_argument(
        "--hermit", metavar="NAME",
        help="Filter by hermit name (case-insensitive, partial match)",
    )
    parser.add_argument(
        "--type", dest="event_type",
        choices=sorted(VALID_TYPES),
        help="Filter by event type",
    )
    parser.add_argument(
        "--search", metavar="QUERY",
        help="Keyword search across title, description, and hermit names",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print event bank statistics and exit",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Output a pretty-printed JSON array instead of NDJSON",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help=(
            f"Page size: max items to return (default {_DEFAULT_LIMIT}, "
            f"max {_MAX_LIMIT}). Activates pagination envelope output."
        ),
    )
    parser.add_argument(
        "--offset", type=int, default=0, metavar="N",
        help="Zero-based starting index for pagination (default 0).",
    )

    args = parser.parse_args(argv)
    events = load_events()

    if args.stats:
        print_stats(events)
        return 0

    results = filter_events(
        events,
        season=args.season,
        hermit=args.hermit,
        event_type=args.event_type,
        search=args.search,
    )

    # Pagination mode: --limit or non-zero --offset activates the envelope
    use_pagination = args.limit is not None or args.offset != 0
    if use_pagination:
        limit = args.limit if args.limit is not None else _DEFAULT_LIMIT
        page = paginate(results, limit=limit, offset=args.offset)
        print(json.dumps(page, indent=2))
        return 0

    if not results:
        sys.stderr.write(
            f"[timeline] no events match filters "
            f"(season={args.season}, hermit={args.hermit!r}, "
            f"type={args.event_type!r}, search={args.search!r})\n"
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
