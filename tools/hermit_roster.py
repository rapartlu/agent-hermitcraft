"""
tools/hermit_roster.py — Hermitcraft roster browser.

Answers the most common new-fan question: "Who are all the Hermitcraft
members, and which seasons were they active?"

Data source: YAML frontmatter in knowledge/hermits/*.md profile files.
Each file must have at minimum a ``name`` field and a ``seasons`` list.

Four query modes:

  --all              Every hermit ever, sorted by first season, with
                     their active season range (e.g. "Grian: S6–S11")
  --season N         Who was active in season N
  --hermit Name      Which seasons a specific hermit appeared in
                     (case-insensitive, partial-name match)
  --changes          Per-season join / departure deltas — who joined and
                     who stepped back between each consecutive pair of
                     seasons

All modes support --json for machine-readable output.

Usage:
    python -m tools.hermit_roster --all
    python -m tools.hermit_roster --all --json
    python -m tools.hermit_roster --season 9
    python -m tools.hermit_roster --hermit Grian
    python -m tools.hermit_roster --hermit mumbo
    python -m tools.hermit_roster --changes
    python -m tools.hermit_roster --changes --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_HERMITS_DIR = Path(__file__).parent.parent / "knowledge" / "hermits"
KNOWN_SEASONS: list[int] = list(range(1, 12))  # seasons 1–11


# ---------------------------------------------------------------------------
# Frontmatter parser (no external deps)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
    """
    Extract the YAML frontmatter block from *text* and return a flat dict.

    Handles the fields used in hermit profiles:
      name, status, joined_season, seasons (list[int]), and string scalars.

    Returns an empty dict when no frontmatter is present.
    """
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = match.group(1)

    result: dict = {}

    # ── seasons: [6, 7, 8] ──────────────────────────────────────────────────
    seasons_match = re.search(r"^seasons:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if seasons_match:
        raw = seasons_match.group(1)
        result["seasons"] = [
            int(s.strip()) for s in raw.split(",") if s.strip().isdigit()
        ]

    # ── scalar fields — skip list/nested lines ───────────────────────────────
    for line in fm.splitlines():
        if line.startswith(" ") or line.startswith("-") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key in result:          # already handled (e.g. seasons)
            continue
        val = val.strip().strip('"').strip("'")
        result[key] = val

    # ── coerce integer fields ────────────────────────────────────────────────
    for int_field in ("joined_season", "joined_year"):
        if int_field in result:
            try:
                result[int_field] = int(result[int_field])
            except (ValueError, TypeError):
                pass

    return result


# ---------------------------------------------------------------------------
# Roster loading
# ---------------------------------------------------------------------------

def load_roster() -> list[dict]:
    """
    Load all hermit profiles from ``knowledge/hermits/*.md``.

    Returns a list of dicts, each with at minimum:
        name (str), seasons (list[int])

    Optional fields (present when the profile has them):
        status, joined_season, joined_year, nationality, youtube

    Profiles with no parseable frontmatter are silently skipped.
    Profiles with no ``seasons`` field are included with ``seasons: []``.
    """
    roster: list[dict] = []
    for path in sorted(_HERMITS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        if not fm or "name" not in fm:
            continue
        fm.setdefault("seasons", [])
        fm["_file"] = path.name
        roster.append(fm)

    # Sort by first season ascending (hermits with no seasons sort last)
    roster.sort(key=lambda h: (min(h["seasons"]) if h["seasons"] else 999,
                               h["name"].lower()))
    return roster


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    return re.sub(r"[\s_-]", "", s).lower()


def _resolve_hermit(roster: list[dict], query: str) -> dict | None:
    """
    Find the best-matching hermit in *roster* for *query*.

    Tries exact name match first, then prefix match, then substring match.
    Returns None when no match is found.
    """
    q = _normalise(query)
    candidates = []
    for h in roster:
        n = _normalise(h["name"])
        if n == q:
            return h                       # exact match — return immediately
        if n.startswith(q) or q in n:
            candidates.append(h)
    return candidates[0] if len(candidates) == 1 else (
        # If multiple candidates, prefer the one whose normalised name starts
        # with the query — disambiguates e.g. "grian" vs "grain"
        next((c for c in candidates if _normalise(c["name"]).startswith(q)),
             candidates[0] if candidates else None)
    )


def all_hermits(roster: list[dict]) -> list[dict]:
    """
    Return every hermit with their season range summary.

    Each entry:
        name, seasons (list), season_range (str), status, joined_season
    """
    result = []
    for h in roster:
        seasons = sorted(h.get("seasons", []))
        if seasons:
            if len(seasons) == 1:
                season_range = f"S{seasons[0]}"
            elif seasons == list(range(seasons[0], seasons[-1] + 1)):
                season_range = f"S{seasons[0]}–S{seasons[-1]}"
            else:
                # Non-consecutive seasons — list explicitly
                season_range = ", ".join(f"S{s}" for s in seasons)
        else:
            season_range = "unknown"
        result.append(
            {
                "name": h["name"],
                "seasons": seasons,
                "season_range": season_range,
                "status": h.get("status", "unknown"),
                "joined_season": h.get("joined_season"),
            }
        )
    return result


def hermits_for_season(roster: list[dict], season: int) -> list[dict]:
    """
    Return every hermit active in *season*, sorted alphabetically by name.

    Each entry:
        name, seasons (full list), status
    """
    active = [
        {
            "name": h["name"],
            "seasons": sorted(h.get("seasons", [])),
            "status": h.get("status", "unknown"),
        }
        for h in roster
        if season in h.get("seasons", [])
    ]
    active.sort(key=lambda h: h["name"].lower())
    return active


def hermit_timeline(roster: list[dict], query: str) -> dict | None:
    """
    Return the season timeline for the hermit best-matching *query*.

    Returns None if no hermit matches.

    Result:
        name, seasons (list), season_range (str), status, joined_season,
        total_seasons (int)
    """
    h = _resolve_hermit(roster, query)
    if h is None:
        return None
    seasons = sorted(h.get("seasons", []))
    if seasons:
        if len(seasons) == 1:
            season_range = f"S{seasons[0]}"
        elif seasons == list(range(seasons[0], seasons[-1] + 1)):
            season_range = f"S{seasons[0]}–S{seasons[-1]}"
        else:
            season_range = ", ".join(f"S{s}" for s in seasons)
    else:
        season_range = "unknown"
    return {
        "name": h["name"],
        "seasons": seasons,
        "season_range": season_range,
        "status": h.get("status", "unknown"),
        "joined_season": h.get("joined_season"),
        "total_seasons": len(seasons),
    }


def roster_changes(roster: list[dict]) -> list[dict]:
    """
    Compute per-season join / departure deltas.

    Iterates over consecutive season pairs drawn from the union of all
    seasons represented in *roster*.  For each transition S(N-1) → S(N):

        joined    — hermits in S(N) but not S(N-1)
        departed  — hermits in S(N-1) but not S(N)

    Returns a list of dicts (one per season that has at least one change),
    sorted by season number:
        season, joined (list[str]), departed (list[str])
    """
    # Build season → hermit-name set from roster
    season_map: dict[int, set[str]] = {}
    for h in roster:
        for s in h.get("seasons", []):
            season_map.setdefault(s, set()).add(h["name"])

    if not season_map:
        return []

    all_seasons = sorted(season_map)
    changes: list[dict] = []

    # Season 1 — everyone is "joining" (no prior season to compare against)
    first = all_seasons[0]
    if first in season_map:
        changes.append(
            {
                "season": first,
                "joined": sorted(season_map[first]),
                "departed": [],
            }
        )

    for prev_s, curr_s in zip(all_seasons, all_seasons[1:]):
        prev_set = season_map.get(prev_s, set())
        curr_set = season_map.get(curr_s, set())
        joined = sorted(curr_set - prev_set)
        departed = sorted(prev_set - curr_set)
        if joined or departed:
            changes.append(
                {
                    "season": curr_s,
                    "joined": joined,
                    "departed": departed,
                }
            )

    return changes


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def format_all_text(entries: list[dict]) -> str:
    if not entries:
        return "No hermit profiles found."
    lines = [f"Hermitcraft All-Time Roster  ({len(entries)} hermits)", ""]
    col_w = max(len(e["name"]) for e in entries) + 2
    for e in entries:
        status_tag = " [inactive]" if e.get("status") == "inactive" else ""
        lines.append(
            f"  {e['name']:<{col_w}} {e['season_range']}{status_tag}"
        )
    return "\n".join(lines)


def format_season_text(season: int, active: list[dict]) -> str:
    header = f"Season {season} Roster  ({len(active)} hermits)"
    lines = [header, "=" * len(header), ""]
    if not active:
        lines.append("  No hermit profiles found for this season.")
        return "\n".join(lines)
    for h in active:
        seasons_str = ", ".join(f"S{s}" for s in h["seasons"])
        lines.append(f"  {h['name']:<24} ({seasons_str})")
    return "\n".join(lines)


def format_timeline_text(info: dict) -> str:
    lines = [
        f"{info['name']} — Season Timeline",
        "",
        f"  Active seasons : {info['season_range']}",
        f"  Total seasons  : {info['total_seasons']}",
        f"  Status         : {info['status']}",
    ]
    if info.get("joined_season"):
        lines.append(f"  Joined season  : S{info['joined_season']}")
    return "\n".join(lines)


def format_changes_text(changes: list[dict]) -> str:
    if not changes:
        return "No roster change data available."
    lines = ["Hermitcraft Roster Changes by Season", ""]
    for entry in changes:
        season = entry["season"]
        joined = entry["joined"]
        departed = entry["departed"]
        lines.append(f"  Season {season}:")
        if joined:
            lines.append(f"    + Joined  : {', '.join(joined)}")
        if departed:
            lines.append(f"    - Departed: {', '.join(departed)}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.hermit_roster",
        description=(
            "Browse the Hermitcraft roster: who has been on the server and "
            "which seasons they were active.  Data drawn from hermit profile "
            "files in knowledge/hermits/."
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--all",
        action="store_true",
        help="List every hermit with their active season range",
    )
    mode.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="List hermits active in season N",
    )
    mode.add_argument(
        "--hermit",
        metavar="NAME",
        help="Show which seasons a specific hermit was active (partial match ok)",
    )
    mode.add_argument(
        "--changes",
        action="store_true",
        help="Show per-season join / departure deltas",
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

    roster = load_roster()

    # ── --all ──────────────────────────────────────────────────────────────
    if args.all:
        entries = all_hermits(roster)
        if args.json:
            print(json.dumps({"hermit_count": len(entries), "hermits": entries},
                             indent=2))
        else:
            print(format_all_text(entries))
        return 0

    # ── --season ───────────────────────────────────────────────────────────
    if args.season is not None:
        active = hermits_for_season(roster, args.season)
        if args.json:
            print(json.dumps(
                {"season": args.season, "hermit_count": len(active),
                 "hermits": active},
                indent=2,
            ))
        else:
            print(format_season_text(args.season, active))
        return 0

    # ── --hermit ───────────────────────────────────────────────────────────
    if args.hermit is not None:
        info = hermit_timeline(roster, args.hermit)
        if info is None:
            print(
                f"[hermit_roster] No profile found matching '{args.hermit}'. "
                "Run --all to see available hermits.",
                file=sys.stderr,
            )
            return 1
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(format_timeline_text(info))
        return 0

    # ── --changes ──────────────────────────────────────────────────────────
    changes = roster_changes(roster)
    if args.json:
        print(json.dumps({"changes": changes}, indent=2))
    else:
        print(format_changes_text(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
