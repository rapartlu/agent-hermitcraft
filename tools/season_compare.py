#!/usr/bin/env python3
"""
tools/season_compare.py — Side-by-side season comparison tool.

Compares two Hermitcraft seasons across key dimensions:

  - Participant count & roster changes (joins/departures)
  - Duration
  - Minecraft version
  - Key themes
  - Notable events / collaborations
  - Timeline event counts

Output modes
------------
  --text   (default)  Human-readable side-by-side comparison
  --json              Machine-readable JSON (ideal for API / Discord bot use)

Usage
-----
  python -m tools.season_compare --a 9 --b 10
  python -m tools.season_compare --a 7 --b 8 --json
  python -m tools.season_compare --list

HTTP API
--------
  GET /seasons/compare?a=9&b=10
  Returns a JSON response with the comparison dict (same structure as --json).
  Query params:
    a   (required) first season number
    b   (required) second season number

Exit codes
----------
  0   success
  1   one or both seasons not found
  2   bad arguments
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap sys.path so that ``python season_compare.py`` and
# ``python -m tools.season_compare`` both work.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.season_recap import build_recap, KNOWN_SEASONS  # noqa: E402


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

def _set_diff(
    set_a: list[str],
    set_b: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """
    Return (common, only_in_a, only_in_b) for two lists treated as sets.
    All comparisons are case-insensitive; output preserves original casing
    from set_a / set_b respectively.
    """
    lower_a = {m.lower(): m for m in set_a}
    lower_b = {m.lower(): m for m in set_b}

    common_keys = lower_a.keys() & lower_b.keys()
    common = sorted(lower_a[k] for k in common_keys)
    only_a = sorted(lower_a[k] for k in lower_a.keys() - lower_b.keys())
    only_b = sorted(lower_b[k] for k in lower_b.keys() - lower_a.keys())
    return common, only_a, only_b


def _duration_to_days(duration_str: str) -> int | None:
    """
    Very rough duration parser.  Understands strings like:
      "~21.5 months", "~13 months", "~18 months (longest…)"
    Returns an approximate day count, or None if unparseable.
    """
    import re

    m = re.search(r"([\d.]+)\s*month", duration_str, re.IGNORECASE)
    if m:
        return int(float(m.group(1)) * 30)
    m = re.search(r"([\d.]+)\s*year", duration_str, re.IGNORECASE)
    if m:
        return int(float(m.group(1)) * 365)
    return None


def build_comparison(season_a: int, season_b: int) -> dict[str, Any]:
    """
    Build and return a comparison dict for two seasons.

    Keys
    ----
    seasons               [a, b] — the two season numbers
    season_a / season_b   full recap dicts (from build_recap)
    participant_count     {a: N, b: N, delta: N}
    duration              {a: str, b: str, longer: int|None}
    minecraft_version     {a: str, b: str}
    roster_changes        {common: [...], left_after_a: [...], joined_for_b: [...]}
    themes                {a: [...], b: [...], shared: [...]}
    notable_events        {a: [...], b: [...]}
    timeline_event_count  {a: N, b: N}
    """
    recap_a = build_recap(season_a)
    recap_b = build_recap(season_b)

    members_a = recap_a.get("members", [])
    members_b = recap_b.get("members", [])
    common_members, left_after_a, joined_for_b = _set_diff(members_a, members_b)

    # Participant count & delta
    count_a = recap_a.get("member_count") or len(members_a)
    count_b = recap_b.get("member_count") or len(members_b)

    # Duration comparison
    dur_a = recap_a.get("duration", "")
    dur_b = recap_b.get("duration", "")
    days_a = _duration_to_days(dur_a)
    days_b = _duration_to_days(dur_b)
    longer: int | None = None
    if days_a is not None and days_b is not None:
        if days_a > days_b:
            longer = season_a
        elif days_b > days_a:
            longer = season_b
        else:
            longer = None  # tied

    # Themes: shared vs unique
    themes_a = recap_a.get("key_themes", [])
    themes_b = recap_b.get("key_themes", [])
    # Find rough shared themes by lowercased first-word match (fuzzy but useful)
    def _theme_key(t: str) -> str:
        return t.split()[0].strip("*").lower() if t else ""

    keys_a = {_theme_key(t) for t in themes_a if t}
    keys_b = {_theme_key(t) for t in themes_b if t}
    shared_theme_keys = keys_a & keys_b
    shared_themes = [t for t in themes_a if _theme_key(t) in shared_theme_keys]

    timeline_count_a = len(recap_a.get("timeline_events", []))
    timeline_count_b = len(recap_b.get("timeline_events", []))

    return {
        "seasons": [season_a, season_b],
        "season_a": recap_a,
        "season_b": recap_b,
        "participant_count": {
            "a": count_a,
            "b": count_b,
            "delta": count_b - count_a,
        },
        "duration": {
            "a": dur_a,
            "b": dur_b,
            "longer": longer,
        },
        "minecraft_version": {
            "a": recap_a.get("minecraft_version", ""),
            "b": recap_b.get("minecraft_version", ""),
        },
        "roster_changes": {
            "common": common_members,
            "left_after_a": left_after_a,
            "joined_for_b": joined_for_b,
        },
        "themes": {
            "a": themes_a,
            "b": themes_b,
            "shared": shared_themes,
        },
        "notable_events": {
            "a": recap_a.get("notable_events", []),
            "b": recap_b.get("notable_events", []),
        },
        "timeline_event_count": {
            "a": timeline_count_a,
            "b": timeline_count_b,
        },
    }


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 64) -> str:
    return char * width


def _col(label: str, value: str, width: int = 30) -> str:
    """Left-pad label, right-pad value."""
    return f"  {label:<28}  {value}"


def _bullet_list(items: list[str], indent: str = "    • ", max_items: int = 6) -> str:
    shown = items[:max_items]
    lines = [f"{indent}{item}" for item in shown]
    if len(items) > max_items:
        lines.append(f"{indent}… and {len(items) - max_items} more")
    return "\n".join(lines) if lines else f"{indent}(none)"


def format_text(cmp: dict) -> str:
    """Return a human-readable side-by-side comparison string."""
    sa, sb = cmp["seasons"]
    ra = cmp["season_a"]
    rb = cmp["season_b"]

    lines: list[str] = []
    lines.append(_hr("═"))
    lines.append(f"  HERMITCRAFT SEASON {sa}  vs  SEASON {sb}")
    lines.append(_hr("═"))

    # Quick stats table
    lines.append("")
    lines.append(f"  {'':28}  S{sa:<8}  S{sb}")
    lines.append(f"  {_hr('-', 60)}")

    def row(label: str, val_a: Any, val_b: Any) -> str:
        return f"  {label:<28}  {str(val_a):<18}  {val_b}"

    lines.append(row("Start date", ra.get("start_date", "?"), rb.get("start_date", "?")))
    lines.append(row("End date", ra.get("end_date", "?"), rb.get("end_date", "?")))
    lines.append(row("Duration", cmp["duration"]["a"] or "?", cmp["duration"]["b"] or "?"))
    lines.append(row("Minecraft version", cmp["minecraft_version"]["a"] or "?",
                     cmp["minecraft_version"]["b"] or "?"))
    lines.append(row("Participants", cmp["participant_count"]["a"],
                     cmp["participant_count"]["b"]))
    lines.append(row("Theme", (ra.get("theme") or "?")[:40], (rb.get("theme") or "?")[:40]))
    lines.append(row("Timeline events", cmp["timeline_event_count"]["a"],
                     cmp["timeline_event_count"]["b"]))

    # Duration winner callout
    longer = cmp["duration"]["longer"]
    if longer is not None:
        lines.append("")
        lines.append(f"  ⏱  Season {longer} ran longer.")

    # Participant delta
    delta = cmp["participant_count"]["delta"]
    if delta > 0:
        lines.append(f"  👥 Season {sb} had {delta} more participant(s).")
    elif delta < 0:
        lines.append(f"  👥 Season {sa} had {abs(delta)} more participant(s).")

    lines.append("")

    # Roster changes
    rc = cmp["roster_changes"]
    lines.append(_hr())
    lines.append(f"  ROSTER CHANGES  (S{sa} → S{sb})")
    lines.append(_hr())
    if rc["left_after_a"]:
        lines.append(f"\n  Left after Season {sa} ({len(rc['left_after_a'])}):")
        lines.append(_bullet_list(rc["left_after_a"]))
    else:
        lines.append(f"\n  No departures between Season {sa} and Season {sb}.")

    if rc["joined_for_b"]:
        lines.append(f"\n  New in Season {sb} ({len(rc['joined_for_b'])}):")
        lines.append(_bullet_list(rc["joined_for_b"]))
    else:
        lines.append(f"\n  No new members joined for Season {sb}.")

    lines.append(f"\n  Returning hermits: {len(rc['common'])}")

    lines.append("")

    # Themes
    lines.append(_hr())
    lines.append("  KEY THEMES")
    lines.append(_hr())
    lines.append(f"\n  Season {sa}:")
    lines.append(_bullet_list(cmp["themes"]["a"]))
    lines.append(f"\n  Season {sb}:")
    lines.append(_bullet_list(cmp["themes"]["b"]))
    if cmp["themes"]["shared"]:
        lines.append("\n  Shared themes:")
        lines.append(_bullet_list(cmp["themes"]["shared"]))

    lines.append("")

    # Notable events
    lines.append(_hr())
    lines.append("  NOTABLE EVENTS")
    lines.append(_hr())
    lines.append(f"\n  Season {sa}:")
    lines.append(_bullet_list(cmp["notable_events"]["a"]))
    lines.append(f"\n  Season {sb}:")
    lines.append(_bullet_list(cmp["notable_events"]["b"]))

    lines.append("")
    lines.append(_hr("═"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="season_compare",
        description="Compare two Hermitcraft seasons side-by-side.",
    )
    p.add_argument("--a", type=int, metavar="SEASON_A",
                   help="First season number (e.g. 9)")
    p.add_argument("--b", type=int, metavar="SEASON_B",
                   help="Second season number (e.g. 10)")
    p.add_argument("--json", action="store_true",
                   help="Output machine-readable JSON")
    p.add_argument("--list", action="store_true",
                   help="List available seasons and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print("Available seasons:", ", ".join(str(s) for s in KNOWN_SEASONS))
        return 0

    if args.a is None or args.b is None:
        parser.error("Both --a and --b are required (e.g. --a 9 --b 10)")
        return 2

    if args.a not in KNOWN_SEASONS:
        print(f"Error: season {args.a} not found. Available: {KNOWN_SEASONS}", file=sys.stderr)
        return 1

    if args.b not in KNOWN_SEASONS:
        print(f"Error: season {args.b} not found. Available: {KNOWN_SEASONS}", file=sys.stderr)
        return 1

    try:
        cmp = build_comparison(args.a, args.b)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        # Omit the large recap sub-dicts from JSON output by default for brevity;
        # callers wanting full recaps should call build_recap directly.
        output = {k: v for k, v in cmp.items() if k not in ("season_a", "season_b")}
        print(json.dumps(output, indent=2))
    else:
        print(format_text(cmp))

    return 0


if __name__ == "__main__":
    sys.exit(main())
