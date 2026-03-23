#!/usr/bin/env python3
"""
Hermitcraft Knowledge Search
=============================
Search across Hermitcraft season events, hermit profiles, and season
files for one or more keywords. Results are ranked by relevance and
include season number and hermit attribution.

Usage
-----
  python3 tools/search.py --query "Boatem Hole"
  python3 tools/search.py --query "prank Grian" --json
  python3 tools/search.py --query "Decked Out" --season 7
  python3 tools/search.py --query "redstone" --sources events hermits
  python3 tools/search.py --query "mycelium" --limit 5
  python3 tools/search.py --query "mycelium" --sources lore
  python3 tools/search.py --query "prank" --sources lore --hermit Grian
  python3 tools/search.py --query "base" --hermit Grian
  python3 tools/search.py --query "war" --type collab
  python3 tools/search.py --query "build" --season 9 --hermit TangoTek --type build

Sources searched (default: all)
---------------------------------
  events    — knowledge/timelines/events.json
              + knowledge/timelines/video_events.json
  hermits   — knowledge/hermits/*.md  (profiles)
  seasons   — knowledge/seasons/*.md  (season summaries)
  lore      — knowledge/lore/*.md     (lore / storyline files)

Ranking
-------
  Title / heading matches score 3×; description / body matches score 1×.
  Query is split on whitespace; each word is searched independently (OR
  logic). Results with more keyword matches rank higher.

Output
------
  Default: human-readable text digest.
  --json : machine-readable JSON object with a "results" array.

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
LORE_DIR = ROOT / "knowledge" / "lore"

ALL_SOURCES = ("events", "hermits", "seasons", "lore")

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

def search_events(
    tokens: list[str],
    season_filter: int | None = None,
    hermit_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict]:
    """
    Search ``events.json`` and ``video_events.json`` for *tokens*.

    Each matching event becomes one result dict with keys:
    source, score, season, hermits, id, title, snippet, date, type.

    Optional filters (applied before scoring):
    - *season_filter*  restrict to a specific season number
    - *hermit_filter*  restrict to events involving a named hermit
                       (case-insensitive substring match against hermit list)
    - *type_filter*    restrict to a specific event type (exact, case-insensitive)
    """
    all_events: list[dict] = []
    for path in (EVENTS_FILE, VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                all_events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass

    hermit_lower = hermit_filter.lower() if hermit_filter else None
    type_lower = type_filter.lower() if type_filter else None

    results = []
    for ev in all_events:
        season = ev.get("season")
        if season_filter is not None and season != season_filter:
            continue

        ev_type = ev.get("type", "")
        if type_lower is not None and ev_type.lower() != type_lower:
            continue

        ev_hermits: list[str] = ev.get("hermits", [])
        if hermit_lower is not None:
            if not any(hermit_lower in h.lower() for h in ev_hermits):
                continue

        title = ev.get("title", "")
        body = ev.get("description", "")
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue
        results.append({
            "source": "event",
            "score": sc,
            "season": season,
            "hermits": ev_hermits,
            "id": ev.get("id", ""),
            "title": title,
            "snippet": make_snippet(body, tokens) if body else "",
            "date": ev.get("date", ""),
            "type": ev_type,
        })
    return results


def search_hermit_profiles(
    tokens: list[str],
    season_filter: int | None = None,
    hermit_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict]:
    """
    Search ``knowledge/hermits/*.md`` profile files for *tokens*.

    If *season_filter* is given, only include hermits who played in that season
    (checked via the ``seasons`` frontmatter list).

    If *hermit_filter* is given, only include the profile whose name contains
    the filter string (case-insensitive).

    If *type_filter* is given and it is not ``"profile"``, skip all profiles.
    """
    # Profiles have type="profile"; skip entirely if caller wants a different type
    if type_filter is not None and type_filter.lower() != "profile":
        return []

    hermit_lower = hermit_filter.lower() if hermit_filter else None

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

        # Hermit filter: name contains the filter string
        if hermit_lower is not None and hermit_lower not in name.lower():
            continue

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

        results.append({
            "source": "hermit_profile",
            "score": sc,
            "season": None,
            "hermits": [name],
            "id": f"hermit-{re.sub(r'[^a-z0-9]', '', name.lower())}",
            "title": f"{name} — Hermit Profile",
            "snippet": make_snippet(body, tokens),
            "date": fm.get("join_date", fm.get("joined_year", "")),
            "type": "profile",
        })
    return results


def search_season_files(
    tokens: list[str],
    season_filter: int | None = None,
    hermit_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict]:
    """
    Search ``knowledge/seasons/season-N.md`` files for *tokens*.

    If *hermit_filter* is given, only include seasons where that hermit is
    mentioned in the Members section.

    If *type_filter* is given and it is not ``"season_summary"``, skip all
    season files.
    """
    if type_filter is not None and type_filter.lower() != "season_summary":
        return []

    hermit_lower = hermit_filter.lower() if hermit_filter else None

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

        # Hermit filter: check the body text (Members section mentions the hermit)
        if hermit_lower is not None and hermit_lower not in body.lower():
            continue

        theme = fm.get("theme", "")
        title = f"Season {season_num}" + (f" — {theme}" if theme else "")
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue

        results.append({
            "source": "season_file",
            "score": sc,
            "season": season_num if season_num else None,
            "hermits": [],
            "id": f"season-{season_num}",
            "title": title,
            "snippet": make_snippet(body, tokens),
            "date": fm.get("start_date", ""),
            "type": "season_summary",
        })
    return results


def _parse_lore_hermits(fm: dict) -> list[str]:
    """
    Extract the hermits list from lore frontmatter.

    Lore files use either:
      hermits_involved:  (multi-line YAML list  →  stored as raw text by our
                          lightweight parser which reads only scalar values)
    or a plain comma-separated ``hermits:`` scalar.

    Because our frontmatter parser only handles scalar values, the
    ``hermits_involved`` block is not captured.  We therefore parse the raw
    YAML block ourselves for list entries.
    """
    # Try scalar hermits field first (comma-separated or single value)
    hermits_scalar = fm.get("hermits", "")
    if hermits_scalar:
        return [h.strip() for h in hermits_scalar.split(",") if h.strip()]
    return []


def _parse_lore_hermits_from_raw(content: str) -> list[str]:
    """
    Parse YAML list items under ``hermits_involved:`` from raw markdown content.
    Returns a list of hermit name strings.
    """
    hermits: list[str] = []
    in_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("hermits_involved:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- "):
                hermits.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("#"):
                # Another YAML key — end of block
                in_block = False
    return hermits


def search_lore_files(
    tokens: list[str],
    season_filter: int | None = None,
    hermit_filter: str | None = None,
    type_filter: str | None = None,
) -> list[dict]:
    """
    Search ``knowledge/lore/*.md`` files for *tokens*.

    Each matching lore file becomes one result with:
    source, score, season, hermits, id, title, snippet, date, type.

    If *season_filter* is given, only include lore files whose ``season``
    frontmatter field matches (cross-season lore files with a ``seasons``
    list are always included if the season appears in that list).

    If *hermit_filter* is given, only include lore files that mention that
    hermit in the ``hermits_involved`` block or the body text.

    If *type_filter* is given, only include lore files whose ``type``
    frontmatter field matches (case-insensitive).
    """
    results = []
    for path in sorted(LORE_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        fm = _parse_frontmatter(content)
        lore_type = fm.get("type", "lore")

        # type_filter: match against frontmatter type (exact, case-insensitive)
        if type_filter is not None and lore_type.lower() != type_filter.lower():
            continue

        # season_filter: check scalar "season" or list "seasons"
        if season_filter is not None:
            scalar_season = fm.get("season", "")
            try:
                if int(scalar_season) == season_filter:
                    pass  # match — proceed
                else:
                    # Try "seasons" list field
                    raw_seasons = fm.get("seasons", "")
                    season_nums = [int(s) for s in re.findall(r"\d+", raw_seasons)]
                    if season_filter not in season_nums:
                        continue
            except (ValueError, TypeError):
                raw_seasons = fm.get("seasons", "")
                season_nums = [int(s) for s in re.findall(r"\d+", raw_seasons)]
                if season_filter not in season_nums:
                    continue

        # Hermit list (from YAML block parser)
        hermits = _parse_lore_hermits_from_raw(content)
        if not hermits:
            hermits = _parse_lore_hermits(fm)

        body = _strip_frontmatter(content)

        # hermit_filter: check hermits list + body text
        if hermit_filter is not None:
            hermit_lower = hermit_filter.lower()
            in_hermits = any(hermit_lower in h.lower() for h in hermits)
            in_body = hermit_lower in body.lower()
            if not in_hermits and not in_body:
                continue

        title = fm.get("title", path.stem.replace("-", " ").title())
        sc = score_result(tokens, title, body)
        if sc <= 0:
            continue

        # Season: prefer scalar "season"; fall back to first entry of "seasons"
        season_val: int | None = None
        try:
            season_val = int(fm.get("season", ""))
        except (ValueError, TypeError):
            raw_seasons = fm.get("seasons", "")
            nums = [int(s) for s in re.findall(r"\d+", raw_seasons)]
            season_val = nums[0] if nums else None

        results.append({
            "source": "lore_file",
            "score": sc,
            "season": season_val,
            "hermits": hermits,
            "id": f"lore-{path.stem}",
            "title": title,
            "snippet": make_snippet(body, tokens),
            "date": "",
            "type": lore_type,
        })
    return results


# ---------------------------------------------------------------------------
# Top-level search
# ---------------------------------------------------------------------------

def run_search(
    query: str,
    sources: list[str] | None = None,
    season_filter: int | None = None,
    hermit_filter: str | None = None,
    type_filter: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search *query* across the requested *sources*.

    Returns a list of result dicts sorted by score (highest first),
    capped at *limit* entries.

    Optional filters (all combinable):
    - *season_filter*  restrict to a specific season number
    - *hermit_filter*  restrict to results involving a named hermit
    - *type_filter*    restrict to a specific result type
                       (e.g. "build", "collab", "lore", "profile", "season_summary")
    """
    if sources is None:
        sources = list(ALL_SOURCES)

    tokens = _tokenise_query(query)
    if not tokens:
        return []

    all_results: list[dict] = []

    if "events" in sources:
        all_results.extend(search_events(
            tokens, season_filter, hermit_filter, type_filter
        ))
    if "hermits" in sources:
        all_results.extend(search_hermit_profiles(
            tokens, season_filter, hermit_filter, type_filter
        ))
    if "seasons" in sources:
        all_results.extend(search_season_files(
            tokens, season_filter, hermit_filter, type_filter
        ))
    if "lore" in sources:
        all_results.extend(search_lore_files(
            tokens, season_filter, hermit_filter, type_filter
        ))

    # Sort: score desc, then season asc (None seasons last), then id
    def sort_key(r: dict) -> tuple:
        season_sort = r["season"] if r["season"] is not None else 9999
        return (-r["score"], season_sort, r["id"])

    all_results.sort(key=sort_key)
    return all_results[:limit]


# ---------------------------------------------------------------------------
# Text formatter
# ---------------------------------------------------------------------------

def _hr(char: str = "─", width: int = 60) -> str:
    return char * width


def format_search_results(query: str, results: list[dict]) -> str:
    """Return a human-readable search results string."""
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
        score = r["score"]
        source = r["source"]
        season = r["season"]
        hermits: list = r["hermits"]
        title = r["title"]
        snippet = r["snippet"]
        date = r["date"]

        season_label = f"Season {season}" if season else "cross-season"
        hermit_str = ", ".join(hermits) if hermits else "—"
        date_label = f"  ·  {date}" if date else ""

        lines.append("")
        lines.append(f"  [Score: {score}]  {source}  ·  {season_label}{date_label}")
        lines.append(f"  {title}")
        if hermits:
            lines.append(f"  Hermits: {hermit_str}")
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
            "Search across Hermitcraft events, hermit profiles, and season "
            "files for one or more keywords."
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
        "--hermit",
        metavar="NAME",
        default=None,
        help=(
            "Restrict search to results involving a specific hermit "
            "(case-insensitive substring match, e.g. --hermit Grian)."
        ),
    )
    parser.add_argument(
        "--type",
        metavar="TYPE",
        default=None,
        dest="result_type",
        help=(
            "Restrict search to a specific result type "
            "(e.g. build, collab, lore, game, milestone, profile, season_summary)."
        ),
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
        hermit_filter=args.hermit,
        type_filter=args.result_type,
        limit=args.limit,
    )

    if args.as_json:
        payload = {
            "query": args.query,
            "sources": args.sources,
            "season_filter": args.season,
            "hermit_filter": args.hermit,
            "type_filter": args.result_type,
            "result_count": len(results),
            "results": results,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_search_results(args.query, results))

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
