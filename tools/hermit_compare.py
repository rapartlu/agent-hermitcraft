"""
tools/hermit_compare.py — Head-to-head hermit comparison CLI.

Compares two Hermitcraft members side-by-side: seasons together, shared events,
individual season ranges, first join season, and specialties.

Usage:
    python -m tools.hermit_compare --hermit-a Grian --hermit-b MumboJumbo
    python -m tools.hermit_compare --hermit-a grian --hermit-b mumbo --json
    python -m tools.hermit_compare --hermit-a Iskall85 --hermit-b EthosLab
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
# Frontmatter / markdown helpers (self-contained, no dependency on hermit_profile)
# ---------------------------------------------------------------------------


def _normalise(s: str) -> str:
    """Lowercase and strip spaces, hyphens, and underscores for fuzzy comparison."""
    return re.sub(r"[\s\-_]+", "", s.lower())


def _parse_frontmatter(content: str) -> dict:
    """Lightweight YAML frontmatter parser (handles str, list, inline-dict, int)."""
    result: dict = {}
    if not content.startswith("---"):
        return result
    end = content.find("\n---", 3)
    if end == -1:
        return result
    block = content[3:end].strip()
    current_key: str | None = None
    current_list: list | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        # Block list continuation
        if current_list is not None and re.match(r"^\s+-\s+", line):
            item_raw = re.sub(r"^\s+-\s+", "", line).strip()
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
            if current_list is not None and current_key is not None:
                result[current_key] = current_list
                current_list = None
                current_key = None
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                current_key = key
                current_list = []
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                result[key] = [
                    token.strip().strip('"').strip("'")
                    for token in inner.split(",")
                    if token.strip()
                ]
            else:
                cleaned = val.strip('"').strip("'")
                try:
                    result[key] = int(cleaned)
                except ValueError:
                    result[key] = cleaned
    if current_list is not None and current_key is not None:
        result[current_key] = current_list
    return result


# ---------------------------------------------------------------------------
# Hermit discovery & loading
# ---------------------------------------------------------------------------


def find_hermit_file(query: str) -> Path | None:
    """
    Find the hermit profile file best matching the query.

    Matching order (first match wins):
    1. Exact handle match  (e.g. "grian" → grian.md)
    2. Exact name match from frontmatter
    3. Handle contains the normalised query
    4. Normalised name contains the normalised query
    """
    norm_query = _normalise(query)
    candidates: list[tuple[int, Path]] = []
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
    """Parse a hermit profile markdown file into a structured dict."""
    content = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(content)

    raw_seasons = fm.get("seasons", [])
    seasons: list[int] = []
    for s in raw_seasons:
        try:
            seasons.append(int(s))
        except (ValueError, TypeError):
            pass

    return {
        "handle": path.stem,
        "name": fm.get("name", path.stem),
        "joined_season": fm.get("joined_season"),
        "specialties": fm.get("specialties", []),
        "seasons": sorted(seasons),
        "status": fm.get("status", "unknown"),
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


def _event_involves(event: dict, norm_name: str) -> bool:
    """Return True if the event's hermits list contains the given normalised name."""
    hermits = event.get("hermits", [])
    if hermits == ["All"]:
        return False
    return any(_normalise(h) == norm_name for h in hermits)


def load_shared_events(name_a: str, name_b: str) -> list[dict]:
    """
    Return events that involve BOTH hermit A and hermit B.

    Events with hermits == ["All"] are excluded (too generic).
    """
    norm_a = _normalise(name_a)
    norm_b = _normalise(name_b)
    results = []
    for ev in _load_event_files():
        if ev.get("hermits") == ["All"]:
            continue
        if _event_involves(ev, norm_a) and _event_involves(ev, norm_b):
            results.append(ev)
    # Sort chronologically
    def _sort_key(ev: dict) -> tuple:
        d = ev.get("date", "")
        parts = d.split("-")
        try:
            return (
                int(parts[0]),
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except (ValueError, IndexError):
            return (9999, 0, 0)

    results.sort(key=_sort_key)
    return results


# ---------------------------------------------------------------------------
# Season range helpers
# ---------------------------------------------------------------------------


def _season_range(seasons: list[int]) -> str:
    """
    Compact season-range string, e.g. [2,3,4,5,6,7,8,9,10,11] → "S2–S11".

    Non-consecutive seasons are listed individually: "S1, S3, S5".
    """
    if not seasons:
        return "none"
    s = sorted(seasons)
    if len(s) == 1:
        return f"S{s[0]}"
    # Check if consecutive
    if s[-1] - s[0] == len(s) - 1:
        return f"S{s[0]}–S{s[-1]}"
    return ", ".join(f"S{n}" for n in s)


def _seasons_label(seasons: list[int]) -> str:
    """e.g. S6, S7, S8 (3 seasons)"""
    if not seasons:
        return "none"
    return f"{_season_range(seasons)}  ({len(seasons)} season{'s' if len(seasons) != 1 else ''})"


# ---------------------------------------------------------------------------
# Comparison builder
# ---------------------------------------------------------------------------


def build_comparison(profile_a: dict, profile_b: dict, events: list[dict]) -> dict:
    """
    Assemble a structured comparison dict from two loaded profiles + shared events.
    """
    seasons_a = set(profile_a["seasons"])
    seasons_b = set(profile_b["seasons"])
    seasons_together = sorted(seasons_a & seasons_b)

    return {
        "hermit_a": {
            "handle": profile_a["handle"],
            "name": profile_a["name"],
            "seasons": profile_a["seasons"],
            "seasons_label": _seasons_label(profile_a["seasons"]),
            "season_range": _season_range(profile_a["seasons"]),
            "first_joined": f"S{profile_a['joined_season']}" if profile_a.get("joined_season") else "unknown",
            "joined_season": profile_a.get("joined_season"),
            "specialties": profile_a["specialties"],
            "status": profile_a["status"],
        },
        "hermit_b": {
            "handle": profile_b["handle"],
            "name": profile_b["name"],
            "seasons": profile_b["seasons"],
            "seasons_label": _seasons_label(profile_b["seasons"]),
            "season_range": _season_range(profile_b["seasons"]),
            "first_joined": f"S{profile_b['joined_season']}" if profile_b.get("joined_season") else "unknown",
            "joined_season": profile_b.get("joined_season"),
            "specialties": profile_b["specialties"],
            "status": profile_b["status"],
        },
        "seasons_together": seasons_together,
        "seasons_together_count": len(seasons_together),
        "seasons_together_label": _season_range(seasons_together) if seasons_together else "none",
        "shared_events": events,
        "shared_event_count": len(events),
    }


# ---------------------------------------------------------------------------
# Formatted text output
# ---------------------------------------------------------------------------

_COL = 20  # label column width


def _row(label: str, val_a: str, val_b: str) -> str:
    return f"  {label:<{_COL}} {val_a:<30} {val_b}"


def format_comparison_text(cmp: dict) -> str:
    """Render the comparison as a human-readable text block."""
    a = cmp["hermit_a"]
    b = cmp["hermit_b"]
    name_a = a["name"]
    name_b = b["name"]

    header = f"{name_a} vs {name_b}"
    lines: list[str] = [
        header,
        "=" * len(header),
        "",
    ]

    # Seasons together
    st = cmp["seasons_together"]
    if st:
        st_str = ", ".join(f"S{s}" for s in st)
        lines.append(f"  Seasons together   : {st_str}  ({cmp['seasons_together_count']} season{'s' if cmp['seasons_together_count'] != 1 else ''})")
    else:
        lines.append("  Seasons together   : none")

    # Shared events
    ev_count = cmp["shared_event_count"]
    if ev_count > 0:
        ev_titles = [ev.get("title", "?") for ev in cmp["shared_events"][:3]]
        ev_preview = ", ".join(ev_titles)
        if ev_count > 3:
            ev_preview += f", … (+{ev_count - 3} more)"
        lines.append(f"  Shared events      : {ev_count}  ({ev_preview})")
    else:
        lines.append("  Shared events      : 0")

    lines.append("")

    # Column headers
    lines.append(f"  {'':20} {name_a:<30} {name_b}")
    lines.append(f"  {'':20} {'-'*len(name_a):<30} {'-'*len(name_b)}")

    lines.append(_row("Seasons", a["seasons_label"], b["seasons_label"]))
    lines.append(_row("First joined", a["first_joined"], b["first_joined"]))
    lines.append(_row("Status", a["status"], b["status"]))

    # Specialties
    spec_a = ", ".join(a["specialties"]) if a["specialties"] else "—"
    spec_b = ", ".join(b["specialties"]) if b["specialties"] else "—"
    lines.append(_row("Specialties", spec_a, spec_b))

    # Shared events details
    if cmp["shared_events"]:
        lines.append("")
        lines.append("  Shared events:")
        for ev in cmp["shared_events"]:
            season_str = f"S{ev['season']}" if ev.get("season") else ""
            date_str = ev.get("date", "")
            when = f"{season_str} {date_str}".strip()
            title = ev.get("title", "?")
            lines.append(f"    • [{when}] {title}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Head-to-head comparison between two Hermitcraft members."
    )
    parser.add_argument(
        "--hermit-a",
        required=True,
        metavar="NAME",
        help="First hermit (partial/case-insensitive match)",
    )
    parser.add_argument(
        "--hermit-b",
        required=True,
        metavar="NAME",
        help="Second hermit (partial/case-insensitive match)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of human-readable text",
    )
    args = parser.parse_args(argv)

    # Resolve hermit A
    path_a = find_hermit_file(args.hermit_a)
    if path_a is None:
        print(
            f"Error: no hermit profile found matching '{args.hermit_a}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve hermit B
    path_b = find_hermit_file(args.hermit_b)
    if path_b is None:
        print(
            f"Error: no hermit profile found matching '{args.hermit_b}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Guard: same hermit
    if path_a.resolve() == path_b.resolve():
        print(
            "Error: --hermit-a and --hermit-b resolved to the same profile. "
            "Please specify two different hermits.",
            file=sys.stderr,
        )
        sys.exit(1)

    profile_a = load_profile(path_a)
    profile_b = load_profile(path_b)

    shared_events = load_shared_events(profile_a["name"], profile_b["name"])
    cmp = build_comparison(profile_a, profile_b, shared_events)

    if args.json:
        print(json.dumps(cmp, indent=2))
    else:
        print(format_comparison_text(cmp))


if __name__ == "__main__":
    main()
