"""
tools/hermit_profile.py — Hermit biography lookup CLI.

Returns a full biography for a named Hermit drawn from the knowledge base:
join date, active seasons, specialties, subscriber milestones, bio paragraph,
notable builds, teams, and related timeline events.

Usage:
    python -m tools.hermit_profile --hermit Grian
    python -m tools.hermit_profile --hermit tangotek --json
    python -m tools.hermit_profile --hermit "mumbo jumbo" --season 7
    python -m tools.hermit_profile --list
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERMITS_DIR = Path(__file__).parent.parent / "knowledge" / "hermits"
EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"
)
VIDEO_EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "video_events.json"
)

# ---------------------------------------------------------------------------
# Frontmatter / markdown helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> dict:
    """Lightweight YAML frontmatter parser (handles str, list, inline-dict, int)."""
    result: dict = {}
    if not content.startswith("---"):
        return result
    end = content.find("\n---", 3)
    if end == -1:
        return result
    block = content[3:end].strip()
    # Handle inline list items: key: [a, b, c]
    # Handle block list items starting with "  -"
    current_key: str | None = None
    current_list: list | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        # Block list continuation
        if current_list is not None and re.match(r"^\s+-\s+", line):
            item_raw = re.sub(r"^\s+-\s+", "", line).strip()
            # Inline dict: { key: val, key: val }
            if item_raw.startswith("{") and item_raw.endswith("}"):
                inner = item_raw[1:-1]
                d: dict = {}
                for part in inner.split(","):
                    part = part.strip()
                    if ":" in part:
                        k, v = part.split(":", 1)
                        d[k.strip()] = v.strip().strip('"')
                current_list.append(d)
            else:
                current_list.append(item_raw.strip('"').strip("'"))
            continue
        # New key
        if ":" in line and not line.startswith(" "):
            # Flush previous list
            if current_list is not None and current_key is not None:
                result[current_key] = current_list
                current_list = None
                current_key = None
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Possibly a block list follows
                current_key = key
                current_list = []
            elif val.startswith("[") and val.endswith("]"):
                # Inline list
                inner = val[1:-1]
                result[key] = [
                    token.strip().strip('"').strip("'")
                    for token in inner.split(",")
                    if token.strip()
                ]
            else:
                # Scalar
                cleaned = val.strip('"').strip("'")
                # Try int
                try:
                    result[key] = int(cleaned)
                except ValueError:
                    result[key] = cleaned
    # Flush trailing list
    if current_list is not None and current_key is not None:
        result[current_key] = current_list
    return result


def _strip_frontmatter(content: str) -> str:
    """Return markdown body without the leading --- block."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content
    return content[end + 4:].lstrip("\n")


def _extract_section(body: str, heading: str) -> str:
    """
    Extract the text content of a ## Heading section.
    Returns everything from that heading up to (but not including) the next ## heading.
    """
    pattern = re.compile(
        r"^##\s+" + re.escape(heading) + r"\s*$", re.MULTILINE | re.IGNORECASE
    )
    m = pattern.search(body)
    if not m:
        return ""
    start = m.end()
    # Find next ## heading
    next_h = re.search(r"^##\s+", body[start:], re.MULTILINE)
    end = start + next_h.start() if next_h else len(body)
    return body[start:end].strip()


def _first_paragraph(text: str) -> str:
    """Return the first non-empty paragraph from a markdown block."""
    for para in text.split("\n\n"):
        clean = para.strip()
        if clean and not clean.startswith("#"):
            # Strip markdown bold/italic markers
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
            clean = re.sub(r"\*(.+?)\*", r"\1", clean)
            return clean
    return ""


# ---------------------------------------------------------------------------
# Hermit discovery & loading
# ---------------------------------------------------------------------------

def list_hermits() -> list[dict]:
    """Return [{handle, name}] for every hermit profile file (sorted by handle)."""
    results = []
    for path in sorted(HERMITS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        content = path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        results.append(
            {
                "handle": path.stem,
                "name": fm.get("name", path.stem),
                "status": fm.get("status", "unknown"),
            }
        )
    return results


def _normalise(s: str) -> str:
    """Lowercase, strip spaces and hyphens for fuzzy comparison."""
    return re.sub(r"[\s\-_]+", "", s.lower())


def find_hermit_file(query: str) -> Path | None:
    """
    Find the hermit profile file best matching the query.

    Matching order (first match wins):
    1. Exact handle match (e.g. "grian" → grian.md)
    2. Exact name match from frontmatter
    3. Handle contains the normalised query
    4. Normalised name contains the normalised query
    """
    norm_query = _normalise(query)
    candidates: list[tuple[int, Path]] = []  # (priority, path)
    for path in HERMITS_DIR.glob("*.md"):
        if path.name == "README.md":
            continue
        content = path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        handle = _normalise(path.stem)
        name = _normalise(fm.get("name", ""))
        if handle == norm_query:
            candidates.append((0, path))
        elif name == norm_query:
            candidates.append((1, path))
        elif norm_query in handle:
            candidates.append((2, path))
        elif norm_query in name:
            candidates.append((3, path))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def load_profile(path: Path) -> dict:
    """Parse a hermit profile file into a structured dict."""
    content = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)
    body = _strip_frontmatter(content)

    # Coerce seasons to list[int]
    raw_seasons = fm.get("seasons", [])
    seasons: list[int] = []
    for s in raw_seasons:
        try:
            seasons.append(int(s))
        except (ValueError, TypeError):
            pass

    # Coerce subscriber_milestones
    milestones = []
    for m in fm.get("subscriber_milestones", []):
        if isinstance(m, dict):
            milestones.append({"date": m.get("date", ""), "count": m.get("count", "")})

    return {
        "handle": path.stem,
        "name": fm.get("name", path.stem),
        "real_name": fm.get("real_name", ""),
        "youtube": fm.get("youtube", ""),
        "hermitcraft_page": fm.get("hermitcraft_page", ""),
        "joined_season": fm.get("joined_season"),
        "joined_year": fm.get("joined_year"),
        "join_date": fm.get("join_date", ""),
        "status": fm.get("status", "unknown"),
        "nationality": fm.get("nationality", ""),
        "specialties": fm.get("specialties", []),
        "seasons": seasons,
        "subscriber_milestones": milestones,
        # Markdown sections
        "bio": _first_paragraph(_extract_section(body, "Overview") or body),
        "notable_builds": _extract_section(body, "Notable Builds & Projects"),
        "teams": _extract_section(body, "Teams & Groups"),
        "trivia": _extract_section(body, "Notable In-Jokes / Trivia"),
        "raw_body": body,
    }


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

def _load_event_files() -> list[dict]:
    events: list[dict] = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return events


def load_hermit_events(hermit_name: str, season_filter: int | None = None) -> list[dict]:
    """
    Return events from events.json / video_events.json that involve this hermit.

    Matches on the event's `hermits` list (case-insensitive, after normalising).
    Events with hermits == ["All"] are excluded (too generic).
    """
    norm = _normalise(hermit_name)
    results = []
    for ev in _load_event_files():
        hermits = ev.get("hermits", [])
        if hermits == ["All"]:
            continue
        if season_filter is not None and ev.get("season") != season_filter:
            continue
        match = any(_normalise(h) == norm for h in hermits)
        if match:
            results.append(ev)
    # Sort chronologically
    def _sort_key(ev: dict) -> tuple:
        d = ev.get("date", "")
        parts = d.split("-")
        try:
            return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return (9999, 0, 0)
    results.sort(key=_sort_key)
    return results


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------

def build_output(
    profile: dict,
    events: list[dict],
    season_filter: int | None = None,
) -> dict:
    """Assemble the final output dict from a loaded profile + events."""
    out: dict = {
        "handle": profile["handle"],
        "name": profile["name"],
        "real_name": profile["real_name"],
        "status": profile["status"],
        "nationality": profile["nationality"],
        "youtube": profile["youtube"],
        "hermitcraft_page": profile["hermitcraft_page"],
        "joined_season": profile["joined_season"],
        "joined_year": profile["joined_year"],
        "join_date": profile["join_date"],
        "specialties": profile["specialties"],
        "seasons": profile["seasons"],
        "subscriber_milestones": profile["subscriber_milestones"],
        "bio": profile["bio"],
        "notable_builds_raw": profile["notable_builds"],
        "teams_raw": profile["teams"],
        "trivia_raw": profile["trivia"],
        "events": events,
        "event_count": len(events),
    }
    if season_filter is not None:
        out["season_filter"] = season_filter
    return out


_BULLET_RE = re.compile(r"^[\-\*]\s+\*\*(.+?)\*\*[:\s—–-]*(.*)$")


def _extract_build_bullets(raw: str) -> list[dict]:
    """Parse '- **Title:** description' lines from the notable builds section."""
    results = []
    for line in raw.splitlines():
        m = _BULLET_RE.match(line.strip())
        if m:
            results.append({"title": m.group(1).strip(), "description": m.group(2).strip()})
    return results


def format_profile_text(output: dict) -> str:
    """Format the profile output as a human-readable text digest."""
    lines: list[str] = []

    name = output["name"]
    status = output["status"].upper()
    nationality = output["nationality"]
    joined = f"Season {output['joined_season']}" if output.get("joined_season") else ""
    joined_year = f" ({output['joined_year']})" if output.get("joined_year") else ""
    seasons_str = ", ".join(str(s) for s in (output.get("seasons") or []))

    lines.append("=" * 60)
    lines.append(f"  {name}  [{status}]")
    lines.append("=" * 60)

    header_parts = []
    if nationality:
        header_parts.append(nationality)
    if joined:
        header_parts.append(f"Joined {joined}{joined_year}")
    if seasons_str:
        header_parts.append(f"Seasons: {seasons_str}")
    if header_parts:
        lines.append("  " + " · ".join(header_parts))

    specialties = output.get("specialties") or []
    if specialties:
        lines.append(f"  Known for: {', '.join(specialties)}")

    if output.get("real_name"):
        lines.append(f"  Real name: {output['real_name']}")
    if output.get("youtube"):
        lines.append(f"  YouTube: {output['youtube']}")

    lines.append("")

    # Bio
    if output.get("bio"):
        lines.append("ABOUT")
        lines.append("-" * 40)
        # Word-wrap at ~72 chars
        bio = output["bio"]
        words = bio.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 > 72:
                lines.append(current_line)
                current_line = word
            else:
                current_line = (current_line + " " + word).strip()
        if current_line:
            lines.append(current_line)
        lines.append("")

    # Notable builds
    builds = _extract_build_bullets(output.get("notable_builds_raw") or "")
    if builds:
        lines.append("NOTABLE BUILDS & PROJECTS")
        lines.append("-" * 40)
        for b in builds:
            desc = f" — {b['description']}" if b["description"] else ""
            lines.append(f"  • {b['title']}{desc}")
        lines.append("")

    # Subscriber milestones
    milestones = output.get("subscriber_milestones") or []
    if milestones:
        lines.append("SUBSCRIBER MILESTONES")
        lines.append("-" * 40)
        for m in milestones:
            lines.append(f"  • {m['count']}  ({m['date']})")
        lines.append("")

    # Timeline events
    events = output.get("events") or []
    season_filter = output.get("season_filter")
    if events:
        header = "TIMELINE EVENTS"
        if season_filter is not None:
            header += f" (Season {season_filter})"
        lines.append(header)
        lines.append("-" * 40)
        for ev in events:
            date = ev.get("date", "unknown date")
            season = ev.get("season", "?")
            title = ev.get("title", "(untitled)")
            ev_type = ev.get("type", "")
            tag = f"[S{season}·{ev_type}]" if ev_type else f"[S{season}]"
            lines.append(f"  {date}  {tag}  {title}")
        lines.append("")

    # Season filter note if no events
    if season_filter is not None and not events:
        lines.append(f"  (No recorded events for Season {season_filter})")
        lines.append("")

    lines.append(f"  hermitcraft_page: {output.get('hermitcraft_page', 'N/A')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.hermit_profile",
        description="Look up a Hermit's full profile from the knowledge base.",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--hermit",
        metavar="NAME",
        help="Hermit name or handle to look up (case-insensitive, partial match ok)",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="List all available hermit handles and names",
    )
    p.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Restrict timeline events shown to this season number",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # --list
    if args.list:
        hermits = list_hermits()
        if getattr(args, "json", False):
            print(json.dumps(hermits, indent=2))
        else:
            print(f"{'Handle':<22}  {'Name':<25}  Status")
            print("-" * 60)
            for h in hermits:
                print(f"  {h['handle']:<20}  {h['name']:<25}  {h['status']}")
        return 0

    # --hermit NAME
    path = find_hermit_file(args.hermit)
    if path is None:
        print(
            f"[hermit_profile] No profile found for '{args.hermit}'. "
            f"Use --list to see available hermits.",
            file=sys.stderr,
        )
        return 1

    profile = load_profile(path)
    events = load_hermit_events(profile["name"], season_filter=args.season)
    output = build_output(profile, events, season_filter=args.season)

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(format_profile_text(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
