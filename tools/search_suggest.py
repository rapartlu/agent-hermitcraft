#!/usr/bin/env python3
"""
tools/search_suggest.py — Search autocomplete / suggestion engine.

Returns ranked suggestions for a partial query string, drawing from:
  - Hermit names  (knowledge/hermits/*.md frontmatter)
  - Season titles  (e.g. "Season 7 — Turf Wars…")
  - Event titles   (knowledge/timelines/events.json + video_events.json)
  - Event types    ("build", "collab", "game", "lore", "meta", "milestone")

Designed for live search-as-you-type UX: fast, prefix-aware, low latency.

HTTP API
--------
  GET /search/suggest?q=<partial_query>
  Optional params:
    limit   Max suggestions to return (default 10, max 25)
    types   Comma-separated subset: hermits,seasons,events,types

  Response JSON:
    {
      "query": "gr",
      "suggestions": [
        {"label": "Grian", "category": "hermit", "value": "Grian"},
        {"label": "Season 9 — Decked Out 2", "category": "season", "value": "Season 9"},
        ...
      ]
    }

CLI usage
---------
  python -m tools.search_suggest --query gr
  python -m tools.search_suggest --query "dec" --limit 5
  python -m tools.search_suggest --query "bui" --types events types
  python -m tools.search_suggest --list-categories

Exit codes
----------
  0   suggestions found
  1   no suggestions
  2   bad arguments
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "events.json"
VIDEO_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "video_events.json"
HERMITS_DIR = _REPO_ROOT / "knowledge" / "hermits"
SEASONS_DIR = _REPO_ROOT / "knowledge" / "seasons"

ALL_CATEGORIES = ("hermits", "seasons", "events", "types")

# Static event-type labels (sourced from events.json vocabulary)
_EVENT_TYPES = [
    "build",
    "collab",
    "game",
    "lore",
    "meta",
    "milestone",
    "video",
    "profile",
    "season_summary",
]


# ---------------------------------------------------------------------------
# Candidate builders (called once, cached per process run)
# ---------------------------------------------------------------------------

def _load_hermit_names() -> list[dict]:
    """Return one suggestion candidate per hermit profile file."""
    candidates = []
    for path in sorted(HERMITS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        name = _frontmatter_value(content, "name") or path.stem
        candidates.append({
            "label": name,
            "category": "hermit",
            "value": name,
            "searchable": name.lower(),
        })
    return candidates


def _load_season_titles() -> list[dict]:
    """Return one suggestion candidate per season file."""
    candidates = []
    for path in sorted(SEASONS_DIR.glob("season-*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(content)
        try:
            season_num = int(fm.get("season", "0"))
        except ValueError:
            season_num = 0
        theme = fm.get("theme", "")
        label = f"Season {season_num}" + (f" — {theme}" if theme else "")
        candidates.append({
            "label": label,
            "category": "season",
            "value": f"Season {season_num}",
            "searchable": label.lower(),
        })
    return candidates


def _load_event_titles() -> list[dict]:
    """Return one suggestion candidate per event (title only, deduped)."""
    seen: set[str] = set()
    candidates = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if not path.exists():
            continue
        try:
            events = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for ev in events:
            title = ev.get("title", "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            season = ev.get("season")
            season_label = f" (S{season})" if season else ""
            label = title + season_label
            candidates.append({
                "label": label,
                "category": "event",
                "value": title,
                "searchable": title.lower(),
            })
    return candidates


def _event_type_candidates() -> list[dict]:
    """Return one suggestion candidate per event type."""
    return [
        {
            "label": t,
            "category": "type",
            "value": t,
            "searchable": t.lower(),
        }
        for t in _EVENT_TYPES
    ]


# ---------------------------------------------------------------------------
# Frontmatter helpers (duplicated lightly to keep this module self-contained)
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    result: dict = {}
    for line in content[4:end].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        value = raw.strip().strip('"').strip("'")
        if value:
            result[key.strip()] = value
    return result


def _frontmatter_value(content: str, key: str) -> str | None:
    fm = _parse_frontmatter(content)
    return fm.get(key)


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def _score_candidate(candidate: dict, query_lower: str) -> int:
    """
    Return a relevance score for *candidate* against *query_lower*.

    Scoring:
      3 — prefix match on first word (e.g. "Gr" matches "Grian")
      2 — prefix match anywhere in the searchable string
      1 — substring (non-prefix) match anywhere
      0 — no match
    """
    searchable = candidate["searchable"]
    if not query_lower:
        return 0

    # Exact prefix of the whole string
    if searchable.startswith(query_lower):
        return 3

    # Prefix of any whitespace-delimited word
    words = re.split(r"[\s\-_]+", searchable)
    if any(w.startswith(query_lower) for w in words):
        return 2

    # Substring anywhere
    if query_lower in searchable:
        return 1

    return 0


def get_suggestions(
    query: str,
    categories: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return up to *limit* suggestion dicts for *query*.

    Each suggestion has keys: label, category, value.
    Results are ranked: prefix matches first, then substring matches,
    then alphabetically within each tier.

    Parameters
    ----------
    query       Partial search string (may be empty → returns nothing).
    categories  Subset of ALL_CATEGORIES to include.  None = all.
    limit       Maximum suggestions to return (capped at 25).
    """
    if not query or not query.strip():
        return []

    limit = min(max(1, limit), 25)
    if categories is None:
        categories = list(ALL_CATEGORIES)

    query_lower = query.strip().lower()

    # Build candidate pool
    pool: list[dict] = []
    if "hermits" in categories:
        pool.extend(_load_hermit_names())
    if "seasons" in categories:
        pool.extend(_load_season_titles())
    if "events" in categories:
        pool.extend(_load_event_titles())
    if "types" in categories:
        pool.extend(_event_type_candidates())

    # Score
    scored: list[tuple[int, str, dict]] = []
    for candidate in pool:
        sc = _score_candidate(candidate, query_lower)
        if sc > 0:
            scored.append((-sc, candidate["label"].lower(), candidate))

    scored.sort(key=lambda x: (x[0], x[1]))

    return [item[2] for item in scored[:limit]]


def format_suggestions(query: str, suggestions: list[dict]) -> str:
    """Return a human-readable suggestion list string."""
    lines = []
    lines.append(f'Suggestions for "{query}" ({len(suggestions)} results):')
    if not suggestions:
        lines.append("  (no matches)")
    for s in suggestions:
        lines.append(f"  [{s['category']}]  {s['label']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="search_suggest",
        description="Autocomplete suggestions for a partial Hermitcraft search query.",
    )
    p.add_argument("--query", "-q", required=False, default="",
                   help="Partial query string to complete.")
    p.add_argument("--limit", type=int, default=10,
                   help="Max suggestions (default 10, max 25).")
    p.add_argument("--types", nargs="+", choices=list(ALL_CATEGORIES),
                   dest="categories", default=None,
                   help=f"Which categories to include: {', '.join(ALL_CATEGORIES)}.")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="Output JSON instead of plain text.")
    p.add_argument("--list-categories", action="store_true",
                   help="Print available suggestion categories and exit.")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_categories:
        print("Available suggestion categories:", ", ".join(ALL_CATEGORIES))
        return 0

    if not args.query or not args.query.strip():
        parser.error("--query / -q is required and must not be empty")
        return 2

    suggestions = get_suggestions(
        query=args.query,
        categories=args.categories,
        limit=args.limit,
    )

    if args.as_json:
        payload = {
            "query": args.query,
            "suggestions": [
                {"label": s["label"], "category": s["category"], "value": s["value"]}
                for s in suggestions
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_suggestions(args.query, suggestions))

    return 0 if suggestions else 1


if __name__ == "__main__":
    sys.exit(main())
