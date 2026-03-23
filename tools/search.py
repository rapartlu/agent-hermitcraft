#!/usr/bin/env python3
"""
Hermitcraft Knowledge Search
=============================
Search across Hermitcraft season events, hermit profiles, season
files, and season highlights for one or more keywords. Results are
ranked by relevance and include season number, hermit attribution,
a numeric rank, and a canonical link to the relevant CLI tool.

Usage
-----
  python3 tools/search.py --query "Boatem Hole"
  python3 tools/search.py --query "prank Grian" --json
  python3 tools/search.py --query "Decked Out" --season 7
  python3 tools/search.py --query "redstone" --sources events hermits
  python3 tools/search.py --query "mycelium" --limit 5
  python3 tools/search.py --query "mumbo" --grouped

Sources searched (default: all)
---------------------------------
  events      — knowledge/timelines/events.json
                + knowledge/timelines/video_events.json
  hermits     — knowledge/hermits/*.md  (profiles)
  seasons     — knowledge/seasons/*.md  (season summaries)
  highlights  — top-ranked events per season (via season_highlights)

Ranking
-------
  Title / heading matches score 3×; description / body matches score 1×.
  Query is split on whitespace; each word is searched independently (OR
  logic). Results with more keyword matches rank higher.
  Each result carries a ``rank`` field (1-based position in the sorted
  list) and a ``link`` field with the canonical CLI invocation.

Output
------
  Default: human-readable text digest.
  --json    : machine-readable JSON with a "results" array and a
              "grouped" object keyed by source type.
  --grouped : human-readable output grouped by source type.

Exit codes
----------
  0  success (≥1 results)
  1  no results found
  2  bad arguments or missing data files
"""

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
EVENTS_FILE = ROOT / "knowledge" / "timelines" / "events.json"
VIDEO_EVENTS_FILE = ROOT / "knowledge" / "timelines" / "video_events.json"
HERMITS_DIR = ROOT / "knowledge" / "hermits"
SEASONS_DIR = ROOT / "knowledge" / "seasons"

ALL_SOURCES = ("events", "hermits", "seasons", "highlights")

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tokenise_query(query: str) -> list[str]:
    """
    Split *query* into a list of non-empty lowercase tokens.
    Each token is searched independently (OR logic); higher total scores
    indicate more keyword coverage.
    """
    return [w.lower() for w in query.split() if w.strip()]


def _count_matches(text: str, tokens: list[str]) -> int:
    """Return the total number of token occurrences in *text* (case-insensitive)."""
    lower = text.lower()
    return sum(lower.count(tok) for tok in tokens)


def score_result(tokens: list[str], title: str, body: str) -> float:
    """
    Return a relevance score for a document with the given *title* and *body*.

    Title hits are worth 3×; body hits are worth 1×.
    """
    return _count_matches(title, tokens) * 3 + _count_matches(body, tokens)


def make_snippet(text: str, tokens: list[str], max_len: int = 160) -> str:
    """
    Return a short excerpt from *text* centred on the first token match.

    If no token is found in *text*, returns the first *max_len* characters.
    """
    text_lower = text.lower()
    best_pos: int | None = None
    for tok in tokens:
        pos = text_lower.find(tok)
        if pos != -1 and (best_pos is None or pos < best_pos):
            best_pos = pos

    if best_pos is None:
        raw = text[:max_len]
    else:
        start = max(0, best_pos - 60)
        end = min(len(text), best_pos + max_len - 60)
        raw = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")

    return re.sub(r"\s+", " ", raw).strip()


# ---------------------------------------------------------------------------
# Frontmatter parser (lightweight, no external deps)
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> dict:
    """Extract scalar fields from YAML-style ``---`` frontmatter."""
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


def _strip_frontmatter(content: str) -> str:
    """Return *content* with the leading ``---`` frontmatter block removed."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    return content[end + 4:] if end != -1 else content


# ---------------------------------------------------------------------------
# Per-source search functions
# ---------------------------------------------------------------------------

def search_events(tokens: list[str], season_filter: int | None = None) -> list[dict]:
    """
    Search ``events.json`` and ``video_events.json`` for *tokens*.

    Each matching event becomes one result dict with keys:
    source, score, season, hermits, id, title, snippet, date, type.
    """
    all_events: list[dict] = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                all_events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass

    results = []
    for ev in all_events:
        season = ev.get("season")
        if season_filter is not None and season != season_filter:
            continue
        title = ev.get("title", "")
        body = ev.get("description", "")
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue
        r: dict = {
            "source": "event",
            "score": sc,
            "season": season,
            "hermits": ev.get("hermits", []),
            "id": ev.get("id", ""),
            "title": title,
            "snippet": make_snippet(body, tokens) if body else "",
            "date": ev.get("date", ""),
            "type": ev.get("type", ""),
        }
        r["link"] = _make_link("event", r)
        results.append(r)
    return results


def search_hermit_profiles(
    tokens: list[str],
    season_filter: int | None = None,
) -> list[dict]:
    """
    Search ``knowledge/hermits/*.md`` profile files for *tokens*.

    If *season_filter* is given, only include hermits who played in that season
    (checked via the ``seasons`` frontmatter list).
    """
    results = []
    for path in sorted(HERMITS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        fm = _parse_frontmatter(content)
        name = fm.get("name", path.stem)

        # Season filter: parse the "seasons:" field as a bracketed list
        if season_filter is not None:
            raw_seasons = fm.get("seasons", "")
            season_nums = [
                int(s) for s in re.findall(r"\d+", raw_seasons)
            ]
            if season_filter not in season_nums:
                continue

        body = _strip_frontmatter(content)
        title = name
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue

        r = {
            "source": "hermit_profile",
            "score": sc,
            "season": None,
            "hermits": [name],
            "id": f"hermit-{re.sub(r'[^a-z0-9]', '', name.lower())}",
            "title": f"{name} — Hermit Profile",
            "snippet": make_snippet(body, tokens),
            "date": fm.get("join_date", fm.get("joined_year", "")),
            "type": "profile",
        }
        r["link"] = _make_link("hermit_profile", r)
        results.append(r)
    return results


def search_season_files(
    tokens: list[str],
    season_filter: int | None = None,
) -> list[dict]:
    """
    Search ``knowledge/seasons/season-N.md`` files for *tokens*.
    """
    results = []
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

        if season_filter is not None and season_num != season_filter:
            continue

        body = _strip_frontmatter(content)
        theme = fm.get("theme", "")
        title = f"Season {season_num}" + (f" — {theme}" if theme else "")
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue

        r = {
            "source": "season_file",
            "score": sc,
            "season": season_num if season_num else None,
            "hermits": [],
            "id": f"season-{season_num}",
            "title": title,
            "snippet": make_snippet(body, tokens),
            "date": fm.get("start_date", ""),
            "type": "season_summary",
        }
        r["link"] = _make_link("season_file", r)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Canonical link builder
# ---------------------------------------------------------------------------

def _make_link(source: str, result: dict) -> str:
    """Return a canonical CLI invocation string for *result*.

    These strings let callers drill into the full detail view for any
    search hit — e.g. pass them directly to the relevant tool.
    """
    season = result.get("season")
    if source == "hermit_profile":
        name = result["hermits"][0] if result.get("hermits") else result["id"]
        return f"python -m tools.hermit_profile --hermit {name!r}"
    if source == "season_file":
        return f"python -m tools.season_recap --season {season}"
    if source == "highlight":
        return f"python -m tools.season_highlights --season {season}"
    if source == "event":
        if season:
            return f"python -m tools.timeline --season {season}"
        return "python -m tools.timeline"
    return ""


# ---------------------------------------------------------------------------
# Highlights search
# ---------------------------------------------------------------------------

def search_highlights(
    tokens: list[str],
    season_filter: int | None = None,
) -> list[dict]:
    """
    Search curated season highlights for *tokens*.

    Highlights are the top-ranked events per season produced by
    ``tools.season_highlights``.  Each matching highlight becomes one
    result dict with ``source == "highlight"``.
    """
    # Import lazily so the module stays usable without season_highlights.
    # Support both `python3 -m tools.search` and `python3 tools/search.py`
    # invocations by ensuring the repo root is on sys.path first.
    try:
        import importlib
        _root = str(Path(__file__).parent.parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        _mod = importlib.import_module("tools.season_highlights")
        rank_season_highlights = _mod.rank_season_highlights
    except Exception:
        return []

    # Determine which seasons to search
    seasons_to_search: list[int] = (
        [season_filter] if season_filter is not None
        else list(range(1, 12))
    )

    results = []
    for season_num in seasons_to_search:
        try:
            highlights = rank_season_highlights(season_num, top_n=20)
        except Exception:
            continue
        for entry in highlights:
            title = entry.get("title", "")
            body = entry.get("description", "")
            sc = score_result(tokens, title, body)
            if sc <= 0:
                continue
            results.append({
                "source": "highlight",
                "score": sc,
                "season": season_num,
                "hermits": entry.get("hermits", []),
                "id": f"highlight-s{season_num}-{entry.get('rank', 0)}",
                "title": title,
                "snippet": make_snippet(body, tokens) if body else "",
                "date": entry.get("date", ""),
                "type": entry.get("type", "highlight"),
                "significance_score": entry.get("significance_score", 0),
            })
    return results


# ---------------------------------------------------------------------------
# Result grouping
# ---------------------------------------------------------------------------

# Maps internal source keys to friendly group names used in grouped output.
_GROUP_LABELS: dict[str, str] = {
    "hermit_profile": "hermits",
    "season_file":    "seasons",
    "event":          "events",
    "highlight":      "highlights",
}


def group_results(results: list[dict]) -> dict[str, list[dict]]:
    """Return *results* organised into a dict keyed by source-group label.

    Keys: ``hermits``, ``seasons``, ``events``, ``highlights``.
    Within each group items retain their overall rank order.
    """
    grouped: dict[str, list[dict]] = {
        "hermits": [], "seasons": [], "events": [], "highlights": [],
    }
    for r in results:
        label = _GROUP_LABELS.get(r["source"], r["source"])
        grouped.setdefault(label, []).append(r)
    return grouped


# ---------------------------------------------------------------------------
# Top-level search
# ---------------------------------------------------------------------------

def run_search(
    query: str,
    sources: list[str] | None = None,
    season_filter: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search *query* across the requested *sources*.

    Returns a list of result dicts sorted by score (highest first),
    capped at *limit* entries.  Every result carries:

    * ``rank``  — 1-based position in the sorted result list.
    * ``link``  — canonical CLI invocation for the matching item.
    """
    if sources is None:
        sources = list(ALL_SOURCES)

    tokens = _tokenise_query(query)
    if not tokens:
        return []

    all_results: list[dict] = []

    if "events" in sources:
        all_results.extend(search_events(tokens, season_filter))
    if "hermits" in sources:
        all_results.extend(search_hermit_profiles(tokens, season_filter))
    if "seasons" in sources:
        all_results.extend(search_season_files(tokens, season_filter))
    if "highlights" in sources:
        all_results.extend(search_highlights(tokens, season_filter))

    # Sort: score desc, then season asc (None seasons last), then id
    def sort_key(r: dict) -> tuple:
        season_sort = r["season"] if r["season"] is not None else 9999
        return (-r["score"], season_sort, r["id"])

    all_results.sort(key=sort_key)
    ranked = all_results[:limit]

    # Stamp rank (1-based) on each result; ensure link is present.
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
        if "link" not in r:
            r["link"] = _make_link(r["source"], r)

    return ranked


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 60) -> str:
    return char * width


def _format_result_block(r: dict) -> list[str]:
    """Return lines for a single result card (used by both formatters)."""
    lines: list[str] = []
    score  = r["score"]
    source = r["source"]
    season = r["season"]
    rank   = r.get("rank", "?")
    hermits: list = r["hermits"]
    title  = r["title"]
    snippet = r["snippet"]
    date   = r["date"]
    link   = r.get("link", "")

    season_label = f"Season {season}" if season else "cross-season"
    hermit_str   = ", ".join(hermits) if hermits else "—"
    date_label   = f"  ·  {date}" if date else ""

    lines.append("")
    lines.append(
        f"  #{rank}  [Score: {score}]  {source}  ·  {season_label}{date_label}"
    )
    lines.append(f"  {title}")
    if hermits:
        lines.append(f"  Hermits: {hermit_str}")
    if link:
        lines.append(f"  Link: {link}")
    lines.append("  " + _hr("─", 56))
    if snippet:
        # Word-wrap snippet at ~76 chars
        words = snippet.split()
        row = ""
        for w in words:
            if len(row) + len(w) + 1 > 74:
                lines.append("  " + row)
                row = w
            else:
                row = (row + " " + w).strip()
        if row:
            lines.append("  " + row)
    lines.append("  " + _hr("─", 56))
    return lines


def format_search_results(query: str, results: list[dict]) -> str:
    """Return a human-readable flat search results string."""
    lines: list[str] = []
    lines.append(_hr("═"))
    lines.append(f'  HERMITCRAFT SEARCH: "{query}"')
    count = len(results)
    lines.append(f"  {count} result{'s' if count != 1 else ''} found")
    lines.append(_hr("═"))

    if not results:
        lines.append("")
        lines.append("  No matches found. Try different keywords or --sources all.")
        lines.append("")
        lines.append(_hr("═"))
        return "\n".join(lines)

    for r in results:
        lines.extend(_format_result_block(r))

    lines.append("")
    lines.append(_hr("═"))
    return "\n".join(lines)


_GROUP_HEADING: dict[str, str] = {
    "hermits":    "👤 HERMIT PROFILES",
    "seasons":    "📅 SEASONS",
    "events":     "📋 EVENTS",
    "highlights": "🏅 HIGHLIGHTS",
}


def format_grouped_results(query: str, results: list[dict]) -> str:
    """Return a human-readable search results string grouped by source type."""
    lines: list[str] = []
    lines.append(_hr("═"))
    lines.append(f'  HERMITCRAFT SEARCH: "{query}"  (grouped)')
    count = len(results)
    lines.append(f"  {count} result{'s' if count != 1 else ''} found")
    lines.append(_hr("═"))

    if not results:
        lines.append("")
        lines.append("  No matches found. Try different keywords or --sources all.")
        lines.append("")
        lines.append(_hr("═"))
        return "\n".join(lines)

    grouped = group_results(results)
    for group_key in ("hermits", "seasons", "highlights", "events"):
        group = grouped.get(group_key, [])
        if not group:
            continue
        heading = _GROUP_HEADING.get(group_key, group_key.upper())
        lines.append("")
        lines.append(f"  {heading}  ({len(group)})")
        lines.append("  " + _hr("═", 56))
        for r in group:
            lines.extend(_format_result_block(r))

    lines.append("")
    lines.append(_hr("═"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search",
        description=(
            "Search across Hermitcraft events, hermit profiles, season "
            "files, and highlights for one or more keywords."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--query", "-q",
        required=True,
        metavar="KEYWORDS",
        help="Search terms (space-separated, OR logic across terms).",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=list(ALL_SOURCES),
        default=list(ALL_SOURCES),
        metavar="SOURCE",
        help=(
            f"Which sources to search: {', '.join(ALL_SOURCES)}. "
            "Default: all. Multiple values accepted."
        ),
    )
    parser.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Restrict search to a specific season number (1–11).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of results to return (default: 20).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output machine-readable JSON instead of text.",
    )
    parser.add_argument(
        "--grouped",
        action="store_true",
        dest="grouped",
        help="Group results by source type (hermits, seasons, highlights, events).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.limit < 1:
        sys.stderr.write("[search] --limit must be ≥ 1\n")
        return 2

    results = run_search(
        query=args.query,
        sources=args.sources,
        season_filter=args.season,
        limit=args.limit,
    )

    if args.as_json:
        payload = {
            "query": args.query,
            "sources": args.sources,
            "season_filter": args.season,
            "result_count": len(results),
            "results": results,
            "grouped": group_results(results),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif args.grouped:
        print(format_grouped_results(args.query, results))
    else:
        print(format_search_results(args.query, results))

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
