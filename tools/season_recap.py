#!/usr/bin/env python3
"""
Season Recap
============
Output a rich digest for a given Hermitcraft season, pulling from
the season markdown file and the shared events timeline.

Usage
-----
  python3 tools/season_recap.py --season 9          # formatted text
  python3 tools/season_recap.py --season 7 --json   # machine-readable JSON
  python3 tools/season_recap.py --list               # list available seasons

Output (text mode)
------------------
  Season header, dates, members, key themes, notable events, major builds,
  and timeline events sourced from knowledge/timelines/events.json.

Output (JSON mode)
------------------
  A single JSON object with all the same fields, suitable for consumption
  by other tools or prompts.

Exit codes
----------
  0  success
  1  season not found or no data available
  2  bad arguments or data file not found
"""

import argparse
import json
import re
import sys
from pathlib import Path

SEASONS_DIR = Path(__file__).parent.parent / "knowledge" / "seasons"
EVENTS_FILE = Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"

# Seasons that have a corresponding markdown file
KNOWN_SEASONS = list(range(1, 12))  # 1–11


# ---------------------------------------------------------------------------
# Frontmatter parser (mirrors on_this_day._parse_frontmatter)
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> dict:
    """Extract scalar fields from YAML frontmatter delimited by ``---``."""
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    fm_text = content[4:end]
    result: dict = {}
    for line in fm_text.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        value = raw_value.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result


# ---------------------------------------------------------------------------
# Markdown section parser
# ---------------------------------------------------------------------------

def _parse_markdown_sections(content: str) -> dict[str, str]:
    """
    Split the markdown body (after frontmatter) into a dict of
    {section_title: section_body} based on ``## `` level-2 headings.
    """
    # Strip frontmatter block
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            content = content[end + 4:]

    sections: dict[str, str] = {}
    current_title: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line)

    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()

    return sections


def _extract_bullet_list(text: str) -> list[str]:
    """
    Return a list of bullet point strings from a markdown section body.
    Handles both ``- `` and ``* `` bullets, stripping leading marker.
    Continuation lines (not starting with ``-``/``*``) are appended to the
    previous item.
    """
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip())
        elif stripped and items:
            # Continuation line — append to previous item
            items[-1] = items[-1] + " " + stripped
    return items


def _extract_members_from_text(text: str) -> list[str]:
    """
    Parse the Members section text into a list of member name strings.
    Handles the comma-separated paragraph format used in season files,
    stripping markdown bold/italic markers and footnotes like *(new)*.

    Strategy: find the line with the most comma-separated tokens that look
    like proper names (capitalised words, ≥3 chars), since prose lines like
    "All 24 Season 7 members returned, plus two new additions:" also contain
    commas but yield very few valid names.
    """
    # Strip markdown formatting
    clean = re.sub(r"\*\([^)]*\)\*", "", text)   # *(returned)*, *(new)*
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)  # **bold**
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)       # *italic*

    def _is_name_like(token: str) -> bool:
        t = token.strip().strip("*").strip()
        if not t or len(t) < 2:
            return False
        # Accept names that start uppercase OR contain at least one uppercase
        # (handles hermit handles like iJevin, xBCrafted that start lowercase)
        return t[0].isupper() or any(c.isupper() for c in t[1:])

    best_line_members: list[str] = []
    for line in clean.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        if "," not in line:
            continue
        candidates = [t.strip() for t in line.split(",")]
        name_candidates = [t for t in candidates if _is_name_like(t)]
        if len(name_candidates) > len(best_line_members):
            best_line_members = name_candidates

    return best_line_members


def _extract_first_paragraph(text: str) -> str:
    """Return the first non-empty, non-heading paragraph from a markdown block."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("|"):
            return stripped
    return ""


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_season_file(season: int) -> tuple[dict, dict[str, str]]:
    """
    Load ``knowledge/seasons/season-N.md`` and return
    ``(frontmatter_dict, sections_dict)``.

    Raises ``FileNotFoundError`` if the file does not exist.
    """
    path = SEASONS_DIR / f"season-{season}.md"
    if not path.exists():
        raise FileNotFoundError(f"Season file not found: {path}")
    content = path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(content)
    sections = _parse_markdown_sections(content)
    return frontmatter, sections


def load_events_for_season(season: int) -> list[dict]:
    """
    Load ``knowledge/timelines/events.json`` and return only events
    whose ``season`` field equals *season*.
    """
    if not EVENTS_FILE.exists():
        return []
    try:
        with EVENTS_FILE.open(encoding="utf-8") as fh:
            all_events: list[dict] = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    return [e for e in all_events if e.get("season") == season]


# ---------------------------------------------------------------------------
# Recap assembler
# ---------------------------------------------------------------------------

def build_recap(season: int) -> dict:
    """
    Build and return the full recap dict for *season*.

    Keys
    ----
    season, start_date, end_date, duration, minecraft_version,
    member_count, seed, theme, status, overview, members,
    key_themes, notable_events, major_builds, sources, timeline_events
    """
    frontmatter, sections = load_season_file(season)

    overview_text = sections.get("Overview", "")
    overview = _extract_first_paragraph(overview_text)

    members_text = sections.get("Members", "")
    members = _extract_members_from_text(members_text)

    key_themes = _extract_bullet_list(sections.get("Key Themes", ""))
    notable_events = _extract_bullet_list(sections.get("Notable Events", ""))
    major_builds = _extract_bullet_list(sections.get("Major Builds", ""))

    # Sources: extract URLs from the Sources section
    sources_text = sections.get("Sources", "")
    sources = re.findall(r"https?://[^\s\)]+", sources_text)

    # Duration: parse from the dates table if present; fall back to frontmatter
    duration = ""
    dates_text = sections.get("Dates", "")
    duration_match = re.search(r"\|\s*\*\*Duration\*\*\s*\|\s*([^|]+)\|", dates_text)
    if duration_match:
        duration = duration_match.group(1).strip()

    timeline_events = load_events_for_season(season)

    seed = frontmatter.get("seed", "")
    if seed.lower() == "unknown":
        seed = None

    return {
        "season": season,
        "start_date": frontmatter.get("start_date", ""),
        "end_date": frontmatter.get("end_date", ""),
        "duration": duration,
        "minecraft_version": frontmatter.get("minecraft_version", ""),
        "member_count": int(frontmatter.get("member_count", 0) or 0),
        "seed": seed,
        "theme": frontmatter.get("theme", ""),
        "status": frontmatter.get("status", ""),
        "overview": overview,
        "members": members,
        "key_themes": key_themes,
        "notable_events": notable_events,
        "major_builds": major_builds,
        "sources": sources,
        "timeline_events": timeline_events,
    }


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 60) -> str:
    return char * width


def format_text(recap: dict) -> str:
    """Return a human-readable multi-line string summarising the season."""
    lines: list[str] = []
    season = recap["season"]

    lines.append(_hr("═"))
    lines.append(f"  HERMITCRAFT SEASON {season} RECAP")
    lines.append(_hr("═"))

    # Dates + metadata
    lines.append("")
    start = recap.get("start_date") or "unknown"
    end = recap.get("end_date") or "ongoing"
    duration = recap.get("duration", "")
    mc_ver = recap.get("minecraft_version", "")
    count = recap.get("member_count", 0)
    seed = recap.get("seed") or "not publicly known"
    status = recap.get("status", "")

    lines.append(f"  Start:    {start}")
    lines.append(f"  End:      {end}" + (f"  ({duration})" if duration else ""))
    lines.append(f"  MC:       {mc_ver}")
    lines.append(f"  Members:  {count}")
    lines.append(f"  Seed:     {seed}")
    lines.append(f"  Status:   {status}")

    theme = recap.get("theme", "")
    if theme:
        lines.append(f"  Theme:    {theme}")

    # Overview
    overview = recap.get("overview", "")
    if overview:
        lines.append("")
        lines.append(_hr())
        lines.append("OVERVIEW")
        lines.append(_hr())
        # Word-wrap to ~80 chars
        words = overview.split()
        row = ""
        for w in words:
            if len(row) + len(w) + 1 > 78:
                lines.append("  " + row)
                row = w
            else:
                row = (row + " " + w).strip()
        if row:
            lines.append("  " + row)

    # Members
    members = recap.get("members", [])
    if members:
        lines.append("")
        lines.append(_hr())
        lines.append(f"MEMBERS  ({len(members)})")
        lines.append(_hr())
        # Format in 3 columns
        col_width = 22
        for i in range(0, len(members), 3):
            row_items = members[i:i + 3]
            lines.append("  " + "".join(m.ljust(col_width) for m in row_items))

    # Key themes
    themes = recap.get("key_themes", [])
    if themes:
        lines.append("")
        lines.append(_hr())
        lines.append("KEY THEMES")
        lines.append(_hr())
        for t in themes:
            lines.append(f"  • {t}")

    # Notable events
    events = recap.get("notable_events", [])
    if events:
        lines.append("")
        lines.append(_hr())
        lines.append("NOTABLE EVENTS")
        lines.append(_hr())
        for e in events:
            lines.append(f"  • {e}")

    # Major builds
    builds = recap.get("major_builds", [])
    if builds:
        lines.append("")
        lines.append(_hr())
        lines.append("MAJOR BUILDS")
        lines.append(_hr())
        for b in builds:
            lines.append(f"  • {b}")

    # Timeline events from events.json
    tl_events = recap.get("timeline_events", [])
    if tl_events:
        lines.append("")
        lines.append(_hr())
        lines.append(f"TIMELINE  ({len(tl_events)} events)")
        lines.append(_hr())
        for ev in tl_events:
            date_str = ev.get("date", "")
            title = ev.get("title", "")
            lines.append(f"  {date_str:<12} {title}")

    # Sources
    sources = recap.get("sources", [])
    if sources:
        lines.append("")
        lines.append(_hr())
        lines.append("SOURCES")
        lines.append(_hr())
        for s in sources:
            lines.append(f"  {s}")

    lines.append("")
    lines.append(_hr("═"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="season_recap",
        description="Rich digest for a given Hermitcraft season.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Season number (1–11)",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List available seasons and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output a machine-readable JSON object instead of text",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list:
        available = [s for s in KNOWN_SEASONS if (SEASONS_DIR / f"season-{s}.md").exists()]
        if args.as_json:
            print(json.dumps({"available_seasons": available}))
        else:
            print("Available seasons: " + ", ".join(str(s) for s in available))
        return 0

    season = args.season
    if season not in KNOWN_SEASONS:
        sys.stderr.write(f"[season_recap] unknown season: {season}. "
                         f"Valid range: {KNOWN_SEASONS[0]}–{KNOWN_SEASONS[-1]}\n")
        return 2

    try:
        recap = build_recap(season)
    except FileNotFoundError as exc:
        sys.stderr.write(f"[season_recap] {exc}\n")
        return 1

    if args.as_json:
        print(json.dumps(recap, indent=2, ensure_ascii=False))
    else:
        print(format_text(recap))

    return 0


if __name__ == "__main__":
    sys.exit(main())
