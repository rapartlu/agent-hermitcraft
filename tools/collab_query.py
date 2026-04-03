"""
tools/collab_query.py — Hermit-vs-hermit collaboration query CLI.

Finds shared events between two named Hermits across all seasons, answering
questions like "when did Grian and Mumbo interact?" or "what did TangoTek and
Iskall build together in Season 7?".

Also supports a leaderboard mode that ranks all hermits by shared-event count
with a single target hermit.

HTTP API contract
-----------------
GET /hermits/:name/collaborators
    Returns a ranked list of hermits that collaborated most with :name.
    Query params (optional):
        season=N       Restrict to a specific season
        type=TYPE,...  Restrict to event types (e.g. build,collab,lore)
        top=N          Max results (default 10)

    Response (JSON):
        {
            "hermit": "Grian",
            "top_n": 10,
            "leaderboard": [
                {"rank": 1, "hermit": "Mumbo", "event_count": 8,
                 "seasons": [6, 7, 8]},
                ...
            ]
        }

GET /collaborations?a=<hermit>&b=<hermit>
    Returns all timestamped shared events between two specific hermits.
    Query params (optional):
        season=N       Restrict to a specific season
        type=TYPE,...  Restrict to event types

    Response (JSON):
        {
            "hermit_a": "Grian",
            "hermit_b": "MumboJumbo",
            "event_count": 8,
            "seasons_with_collabs": [6, 7, 8],
            "events": [
                {"date": "2019-04-20", "season": 6, "type": "collab",
                 "title": "...", "description": "..."},
                ...
            ]
        }

    404 (exit 1): if either hermit name is not found in the knowledge base.

Usage:
    python -m tools.collab_query --hermit-a Grian --hermit-b Mumbo
    python -m tools.collab_query --hermit-a TangoTek --hermit-b Iskall85 --season 7
    python -m tools.collab_query --hermit-a EthosLab --hermit-b BdoubleO100 --json
    python -m tools.collab_query --hermit-a Grian --hermit-b Scar --types lore build

    # Top-collaborators / GET /hermits/:name/collaborators:
    python -m tools.collab_query --hermit-a Grian --top-collabs
    python -m tools.collab_query --hermit-a TangoTek --top-collabs --top 5
    python -m tools.collab_query --hermit-a Iskall85 --top-collabs --season 8
    python -m tools.collab_query --hermit-a Grian --top-collabs --json
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
EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "events.json"
)
VIDEO_EVENTS_FILE = (
    Path(__file__).parent.parent / "knowledge" / "timelines" / "video_events.json"
)
HERMITS_DIR = Path(__file__).parent.parent / "knowledge" / "hermits"

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    """Lowercase, remove spaces/hyphens/underscores for fuzzy comparison."""
    return re.sub(r"[\s\-_]+", "", s.lower())


def _resolve_hermit_name(query: str) -> str | None:
    """
    Return the canonical display name for a hermit by fuzzy-matching against
    profile filenames and YAML ``name`` fields.

    Returns None if no profile matches.
    """
    norm_q = _normalise(query)
    candidates: list[tuple[int, str]] = []
    for path in HERMITS_DIR.glob("*.md"):
        if path.name == "README.md":
            continue
        content = path.read_text(encoding="utf-8")
        # Extract name from frontmatter
        fm_name = ""
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    if line.startswith("name:"):
                        fm_name = line.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        handle = _normalise(path.stem)
        name_norm = _normalise(fm_name)
        display = fm_name or path.stem

        if handle == norm_q or name_norm == norm_q:
            candidates.append((0, display))
        elif norm_q in handle or norm_q in name_norm:
            candidates.append((1, display))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


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


def find_shared_events(
    name_a: str,
    name_b: str,
    season_filter: int | None = None,
    type_filter: list[str] | None = None,
    _events: list[dict] | None = None,
) -> list[dict]:
    """
    Return events where both *name_a* and *name_b* appear in the hermits list.

    Events with ``hermits == ["All"]`` are excluded — they represent
    server-wide events with no specific pairing signal.

    Args:
        name_a: Canonical display name of hermit A.
        name_b: Canonical display name of hermit B.
        season_filter: If given, restrict to this season number.
        type_filter: If given, restrict to events whose ``type`` field is in
            this list (e.g. ``["lore", "build"]``).
        _events: Pre-loaded event list (used by find_top_collaborators to
            avoid re-reading files for every hermit pair).

    Returns:
        List of event dicts, sorted chronologically.
    """
    norm_a = _normalise(name_a)
    norm_b = _normalise(name_b)
    if norm_a == norm_b:
        return []
    results: list[dict] = []

    for ev in (_events if _events is not None else _load_all_events()):
        hermits = ev.get("hermits", [])
        if hermits == ["All"]:
            continue
        if season_filter is not None and ev.get("season") != season_filter:
            continue
        if type_filter is not None and ev.get("type") not in type_filter:
            continue
        normed = [_normalise(h) for h in hermits]
        if norm_a in normed and norm_b in normed:
            results.append(ev)

    results.sort(key=_event_sort_key)
    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _all_hermit_names() -> list[str]:
    """Return canonical display names for all hermit profiles."""
    names: list[str] = []
    for path in sorted(HERMITS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        content = path.read_text(encoding="utf-8")
        fm_name = ""
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                for line in content[3:end].splitlines():
                    if line.startswith("name:"):
                        fm_name = line.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        names.append(fm_name or path.stem)
    return names


def find_top_collaborators(
    name_a: str,
    season_filter: int | None = None,
    type_filter: list[str] | None = None,
    top_n: int = 10,
) -> list[dict]:
    """
    Return a ranked list of hermits by shared-event count with *name_a*.

    Each entry is a dict with keys:
        rank, hermit, event_count, seasons

    Args:
        name_a: Canonical display name of the target hermit.
        season_filter: If given, restrict to this season number.
        type_filter: If given, restrict to events of these types.
        top_n: Maximum number of results to return.

    Returns:
        List of dicts sorted descending by event_count, ties broken by name.
    """
    all_names = _all_hermit_names()
    norm_a = _normalise(name_a)
    # Load events once and reuse across all pair queries.
    cached_events = _load_all_events()

    results: list[dict] = []
    for name_b in all_names:
        if _normalise(name_b) == norm_a:
            continue
        events = find_shared_events(
            name_a,
            name_b,
            season_filter=season_filter,
            type_filter=type_filter,
            _events=cached_events,
        )
        if not events:
            continue
        seasons = _seasons_covered(events)
        results.append(
            {
                "hermit": name_b,
                "event_count": len(events),
                "seasons": seasons,
            }
        )

    results.sort(key=lambda x: (-x["event_count"], x["hermit"].lower()))
    ranked: list[dict] = []
    for i, entry in enumerate(results[:top_n], start=1):
        ranked.append({"rank": i, **entry})
    return ranked


def _seasons_covered(events: list[dict]) -> list[int]:
    seen: set[int] = set()
    for ev in events:
        s = ev.get("season")
        if isinstance(s, int):
            seen.add(s)
    return sorted(seen)


def build_output(
    name_a: str,
    name_b: str,
    events: list[dict],
    season_filter: int | None = None,
    type_filter: list[str] | None = None,
) -> dict:
    """Assemble the final output dict."""
    seasons = _seasons_covered(events)
    out: dict = {
        "hermit_a": name_a,
        "hermit_b": name_b,
        "event_count": len(events),
        "seasons_with_collabs": seasons,
        "events": events,
    }
    if season_filter is not None:
        out["season_filter"] = season_filter
    if type_filter is not None:
        out["type_filter"] = type_filter
    return out


def format_text(output: dict) -> str:
    """Format collab output as a human-readable digest."""
    a = output["hermit_a"]
    b = output["hermit_b"]
    count = output["event_count"]
    seasons = output.get("seasons_with_collabs", [])
    events = output.get("events", [])

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append(f"  {a}  ×  {b}")
    lines.append("=" * 60)

    season_filter = output.get("season_filter")
    type_filter = output.get("type_filter")

    if count == 0:
        qualifier = ""
        if season_filter:
            qualifier += f" in Season {season_filter}"
        if type_filter:
            qualifier += f" of type {', '.join(type_filter)}"
        lines.append(f"  No shared events found{qualifier}.")
        lines.append(f"  (Try without filters, or check --types / --season)")
        return "\n".join(lines)

    season_str = (
        ", ".join(f"S{s}" for s in seasons) if seasons else "unknown"
    )
    lines.append(f"  {count} shared event{'s' if count != 1 else ''}"
                 f"  ·  Seasons: {season_str}")
    if season_filter:
        lines.append(f"  (filtered to Season {season_filter})")
    if type_filter:
        lines.append(f"  (filtered to types: {', '.join(type_filter)})")
    lines.append("")

    current_season: int | None = None
    for ev in events:
        s = ev.get("season")
        if s != current_season:
            current_season = s
            lines.append(f"  ── Season {s} ──")
        date = ev.get("date", "unknown date")
        ev_type = ev.get("type", "")
        title = ev.get("title", "(untitled)")
        desc = ev.get("description", "")
        tag = f"[{ev_type}]" if ev_type else ""
        lines.append(f"  {date}  {tag}  {title}")
        if desc:
            # Indent and wrap description
            words = desc.split()
            line_buf = "      "
            for word in words:
                if len(line_buf) + len(word) + 1 > 72:
                    lines.append(line_buf.rstrip())
                    line_buf = "      " + word
                else:
                    line_buf = (line_buf + " " + word).rstrip() if line_buf == "      " else line_buf + " " + word
            if line_buf.strip():
                lines.append(line_buf.rstrip())

    return "\n".join(lines)


def format_top_collabs(
    name_a: str,
    ranked: list[dict],
    season_filter: int | None = None,
) -> str:
    """Format top-collaborators leaderboard as a human-readable table."""
    season_label = f"Season {season_filter}" if season_filter else "all seasons"
    lines: list[str] = []
    lines.append(f"Top collaborators for {name_a} ({season_label}):")

    if not ranked:
        lines.append("  (no shared events found)")
        return "\n".join(lines)

    # Column widths
    max_name = max(len(e["hermit"]) for e in ranked)
    col_w = max(max_name, 6)

    for entry in ranked:
        rank = entry["rank"]
        hermit = entry["hermit"]
        count = entry["event_count"]
        seasons = entry.get("seasons", [])
        s_str = ", ".join(f"S{s}" for s in seasons) if seasons else ""
        s_part = f"  ({s_str})" if s_str else ""
        plural = "s" if count != 1 else " "  # space (not "") keeps column alignment
        lines.append(
            f"  {rank:2d}. {hermit:<{col_w}}  "
            f"{count} shared event{plural}{s_part}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.collab_query",
        description=(
            "Find shared Hermitcraft events between two Hermits. "
            "Answers 'when did A and B collaborate?' or "
            "'who does A collaborate with most?' (--top-collabs)."
        ),
    )
    p.add_argument(
        "--hermit-a",
        required=True,
        metavar="NAME",
        help="Target Hermit (case-insensitive, partial match ok)",
    )
    p.add_argument(
        "--hermit-b",
        metavar="NAME",
        help="Second Hermit for pairwise query (required unless --top-collabs)",
    )
    p.add_argument(
        "--top-collabs",
        action="store_true",
        help="Leaderboard mode: rank all Hermits by shared-event count with --hermit-a",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="Max results in --top-collabs mode (default: 10)",
    )
    p.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Restrict to a specific season number",
    )
    p.add_argument(
        "--types",
        nargs="+",
        metavar="TYPE",
        help="Restrict to event types, e.g. --types lore build collab",
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

    # Validate mode
    if not args.top_collabs and args.hermit_b is None:
        parser.error("--hermit-b is required unless --top-collabs is specified")

    name_a = _resolve_hermit_name(args.hermit_a)
    if name_a is None:
        print(
            f"[collab_query] No profile found for '{args.hermit_a}'. "
            "Check spelling or use tools/hermit_profile.py --list.",
            file=sys.stderr,
        )
        return 1

    # ── Top-collabs leaderboard mode ──────────────────────────────────────
    if args.top_collabs and args.hermit_b is not None:
        print(
            "Warning: --hermit-b is ignored in --top-collabs mode",
            file=sys.stderr,
        )

    if args.top_collabs:
        ranked = find_top_collaborators(
            name_a,
            season_filter=args.season,
            type_filter=args.types,
            top_n=args.top,
        )
        if args.json:
            out: dict = {
                "hermit": name_a,
                "top_n": args.top,
                "leaderboard": ranked,
            }
            if args.season is not None:
                out["season_filter"] = args.season
            if args.types is not None:
                out["type_filter"] = args.types
            print(json.dumps(out, indent=2))
        else:
            print(format_top_collabs(name_a, ranked, season_filter=args.season))
        return 0

    # ── Pairwise mode ─────────────────────────────────────────────────────
    name_b = _resolve_hermit_name(args.hermit_b)
    if name_b is None:
        print(
            f"[collab_query] No profile found for '{args.hermit_b}'. "
            "Check spelling or use tools/hermit_profile.py --list.",
            file=sys.stderr,
        )
        return 1

    if _normalise(name_a) == _normalise(name_b):
        print(
            "[collab_query] --hermit-a and --hermit-b resolve to the same Hermit.",
            file=sys.stderr,
        )
        return 1

    events = find_shared_events(
        name_a,
        name_b,
        season_filter=args.season,
        type_filter=args.types,
    )
    output = build_output(
        name_a,
        name_b,
        events,
        season_filter=args.season,
        type_filter=args.types,
    )

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(format_text(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
