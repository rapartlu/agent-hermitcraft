"""
tools/season_digest.py — Shareable "Season in Review" digest generator.

Combines per-season highlights, collaborations, and a narrative arc summary
into one ready-to-share document.  The markdown output can be pasted directly
into a Discord message, a Reddit post, or a wiki page; the JSON output feeds
downstream tools such as a Discord bot or static site generator.

Sections in every digest:
  1. Quick stats  — date range, hermit count, event-type breakdown
  2. Top highlights — top N events ranked by significance score, with
                      contextual prose (title + description)
  3. Peak moment  — the single highest-scoring event (Hall of Fame entry)
  4. Notable collaborations — top hermit pairs that teamed up this season
  5. Season arc   — one-paragraph narrative synthesised from milestone events

Output modes:
  --markdown  (default)  Ready-to-paste .md document with headers / bullets
  --json                 Structured dict for downstream tooling

Usage:
    python -m tools.season_digest --season 9
    python -m tools.season_digest --season 9 --top 3
    python -m tools.season_digest --season 9 --json
    python -m tools.season_digest --season 9 --markdown
    python -m tools.season_digest --list
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "events.json"
_VIDEO_EVENTS_FILE = _REPO_ROOT / "knowledge" / "timelines" / "video_events.json"

KNOWN_SEASONS: list[int] = list(range(1, 12))  # seasons 1–11

_DEFAULT_TOP_N = 5
_DEFAULT_TOP_PAIRS = 3

# ---------------------------------------------------------------------------
# Significance scoring (mirrors season_highlights / all_time_highlights)
# ---------------------------------------------------------------------------

_TYPE_SCORE: dict[str, int] = {
    "milestone": 10,
    "lore": 8,
    "game": 7,
    "collab": 6,
    "build": 5,
    "meta": 1,
}


def _significance_score(event: dict) -> int:
    score = _TYPE_SCORE.get(event.get("type", ""), 0)
    hermits = event.get("hermits", [])
    if hermits == ["All"]:
        score += 3
    elif len(hermits) >= 4:
        score += 2
    elif len(hermits) >= 2:
        score += 1
    if event.get("date_precision") == "day":
        score += 1
    return score


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


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

def _load_all_events() -> list[dict]:
    events: list[dict] = []
    for path in (_EVENTS_FILE, _VIDEO_EVENTS_FILE):
        if path.exists():
            try:
                events.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return events


def _season_events(all_events: list[dict], season: int) -> list[dict]:
    return [ev for ev in all_events if ev.get("season") == season]


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_stats(season: int, events: list[dict]) -> dict:
    """
    Quick stats block for *season*.

    Returns:
        season, event_count, hermit_count, hermits, date_start, date_end,
        type_breakdown (dict of type → count)
    """
    if not events:
        return {
            "season": season,
            "event_count": 0,
            "hermit_count": 0,
            "hermits": [],
            "date_start": None,
            "date_end": None,
            "type_breakdown": {},
        }

    hermit_set: set[str] = set()
    for ev in events:
        for h in ev.get("hermits", []):
            if h != "All":
                hermit_set.add(h)

    dates = sorted(
        ev.get("date", "")
        for ev in events
        if ev.get("date") and ev.get("date_precision") in ("day", "month", "year")
    )
    date_start = dates[0] if dates else None
    date_end = dates[-1] if dates else None

    type_breakdown = dict(
        collections.Counter(ev.get("type", "unknown") for ev in events)
    )

    return {
        "season": season,
        "event_count": len(events),
        "hermit_count": len(hermit_set),
        "hermits": sorted(hermit_set),
        "date_start": date_start,
        "date_end": date_end,
        "type_breakdown": type_breakdown,
    }


def build_highlights(season: int, events: list[dict], top_n: int) -> list[dict]:
    """
    Top *top_n* events for *season* ranked by significance score.

    Each entry: rank, title, description, date, type, hermits,
                significance_score
    """
    scored = [
        (_significance_score(ev), _event_sort_key(ev), ev)
        for ev in events
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))

    results: list[dict] = []
    for rank, (score, _, ev) in enumerate(scored[:top_n], start=1):
        results.append(
            {
                "rank": rank,
                "title": ev.get("title", "(untitled)"),
                "description": ev.get("description", ""),
                "date": ev.get("date", ""),
                "type": ev.get("type", ""),
                "hermits": ev.get("hermits", []),
                "significance_score": score,
            }
        )
    return results


def build_peak_moment(season: int, events: list[dict]) -> dict | None:
    """
    The single highest-scoring event for *season* — the Hall of Fame entry.

    Returns None when *events* is empty.
    Ties broken chronologically (earlier first).
    """
    if not events:
        return None

    best_ev = max(
        events,
        key=lambda ev: (_significance_score(ev), tuple(-x for x in _event_sort_key(ev))),
    )
    # Re-compute with proper tie-break (max doesn't do compound sort easily)
    scored = [(_significance_score(ev), _event_sort_key(ev), ev) for ev in events]
    scored.sort(key=lambda x: (-x[0], x[1]))
    score, _, best_ev = scored[0]

    return {
        "title": best_ev.get("title", "(untitled)"),
        "description": best_ev.get("description", ""),
        "date": best_ev.get("date", ""),
        "type": best_ev.get("type", ""),
        "hermits": best_ev.get("hermits", []),
        "significance_score": score,
    }


def build_collaborations(season: int, events: list[dict], top_n: int) -> list[dict]:
    """
    Top *top_n* hermit pairs by shared-event count for *season*.

    Counts events in which both hermits appear together (excludes "All"
    catch-all entries, which aren't pair-specific).

    Each entry: hermit_a, hermit_b, shared_event_count, event_titles
    """
    # Build per-event hermit sets (named hermits only)
    named_events = [
        (ev, set(h for h in ev.get("hermits", []) if h != "All"))
        for ev in events
    ]

    pair_events: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for ev, hermit_set in named_events:
        if len(hermit_set) < 2:
            continue
        for a, b in itertools.combinations(sorted(hermit_set), 2):
            pair_events[(a, b)].append(ev.get("title", "(untitled)"))

    ranked = sorted(
        pair_events.items(),
        key=lambda kv: -len(kv[1]),
    )

    results: list[dict] = []
    for (a, b), titles in ranked[:top_n]:
        results.append(
            {
                "hermit_a": a,
                "hermit_b": b,
                "shared_event_count": len(titles),
                "event_titles": titles,
            }
        )
    return results


def build_arc_summary(season: int, stats: dict, highlights: list[dict]) -> str:
    """
    One-paragraph narrative arc synthesised from milestone/lore highlights.

    Pulls thread lines from the top milestone and lore events and weaves
    them into a human-readable paragraph.  Degrades gracefully: if no
    milestone events exist, falls back to the top highlights.
    """
    # Pick narrative anchor events (milestone > lore > whatever we have)
    anchors = [h for h in highlights if h.get("type") in ("milestone", "lore")]
    if not anchors:
        anchors = highlights[:3]

    if not anchors:
        return f"Season {season} data is sparse — no narrative arc available."

    hermit_count = stats.get("hermit_count", 0)
    date_start = stats.get("date_start") or "an unknown date"
    date_end = stats.get("date_end") or "an unknown date"

    # Opening sentence
    sentences: list[str] = [
        f"Season {season} brought together {hermit_count} hermits"
        f" from {date_start} to {date_end}."
    ]

    # One sentence per anchor event
    for anchor in anchors:
        title = anchor.get("title", "")
        desc = anchor.get("description", "")
        # Use first sentence of description if available, else title only
        first_sentence = desc.split(".")[0].strip() if desc else ""
        if first_sentence and len(first_sentence) < 200:
            sentences.append(first_sentence + ".")
        elif title:
            sentences.append(f"A defining moment was {title}.")

    # Closing
    type_breakdown = stats.get("type_breakdown", {})
    top_type = max(type_breakdown, key=lambda t: type_breakdown[t], default=None)
    if top_type:
        sentences.append(
            f"The season was dominated by {top_type} events,"
            f" reflecting the server's energy and ambition."
        )

    return " ".join(sentences)


# ---------------------------------------------------------------------------
# Digest assembler
# ---------------------------------------------------------------------------

def build_digest(
    season: int,
    top_n: int = _DEFAULT_TOP_N,
    top_pairs: int = _DEFAULT_TOP_PAIRS,
) -> dict:
    """
    Assemble a full Season in Review digest for *season*.

    Returns a structured dict with keys:
        season, stats, highlights, peak_moment, collaborations, arc_summary

    Never raises for known seasons with sparse data — sections will be empty
    rather than absent.
    """
    all_events = _load_all_events()
    events = _season_events(all_events, season)

    stats = build_stats(season, events)
    highlights = build_highlights(season, events, top_n)
    peak = build_peak_moment(season, events)
    collabs = build_collaborations(season, events, top_pairs)
    arc = build_arc_summary(season, stats, highlights)

    return {
        "season": season,
        "stats": stats,
        "highlights": highlights,
        "peak_moment": peak,
        "collaborations": collabs,
        "arc_summary": arc,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _md_hermits(hermits: list[str]) -> str:
    if hermits == ["All"]:
        return "All hermits"
    return ", ".join(hermits[:4]) + (" …" if len(hermits) > 4 else "")


def render_markdown(digest: dict) -> str:
    """
    Render *digest* as a ready-to-paste markdown document.
    """
    season = digest["season"]
    stats = digest.get("stats", {})
    highlights = digest.get("highlights", [])
    peak = digest.get("peak_moment")
    collabs = digest.get("collaborations", [])
    arc = digest.get("arc_summary", "")

    lines: list[str] = []

    # ── Title ──────────────────────────────────────────────────────────────
    lines += [f"# Hermitcraft Season {season} — Season in Review", ""]

    # ── Stats ──────────────────────────────────────────────────────────────
    lines += ["## Quick Stats", ""]
    date_start = stats.get("date_start") or "unknown"
    date_end = stats.get("date_end") or "unknown"
    lines.append(f"- **Date range:** {date_start} → {date_end}")
    lines.append(f"- **Hermits:** {stats.get('hermit_count', 0)}")
    lines.append(f"- **Documented events:** {stats.get('event_count', 0)}")

    breakdown = stats.get("type_breakdown", {})
    if breakdown:
        bd_str = ", ".join(
            f"{t}: {c}"
            for t, c in sorted(breakdown.items(), key=lambda x: -x[1])
        )
        lines.append(f"- **Event types:** {bd_str}")

    lines.append("")

    # ── Arc summary ────────────────────────────────────────────────────────
    lines += ["## Season Arc", "", arc, ""]

    # ── Peak moment ────────────────────────────────────────────────────────
    lines += ["## Peak Moment", ""]
    if peak:
        lines.append(
            f"**{peak['title']}**  "
            f"*(score: {peak['significance_score']})*"
        )
        if peak.get("date"):
            lines.append(f"*{peak['date']} · {_md_hermits(peak['hermits'])}*")
        if peak.get("description"):
            lines.append("")
            lines.append(f"> {peak['description']}")
    else:
        lines.append("*No peak moment data available for this season.*")

    lines.append("")

    # ── Highlights ─────────────────────────────────────────────────────────
    lines += [f"## Top {len(highlights)} Highlights", ""]
    if highlights:
        for entry in highlights:
            rank = entry["rank"]
            title = entry["title"]
            ev_type = entry.get("type", "")
            date = entry.get("date", "")
            desc = entry.get("description", "")
            score = entry.get("significance_score", 0)

            type_badge = f"`{ev_type}`" if ev_type else ""
            lines.append(f"### {rank}. {title}")
            meta_parts = [p for p in [date, _md_hermits(entry.get("hermits", [])),
                                      f"score: {score}"] if p]
            lines.append(f"*{' · '.join(meta_parts)}*  {type_badge}")
            if desc:
                lines += ["", desc]
            lines.append("")
    else:
        lines.append("*No highlights data available for this season.*")
        lines.append("")

    # ── Collaborations ─────────────────────────────────────────────────────
    lines += ["## Notable Collaborations", ""]
    if collabs:
        for entry in collabs:
            a = entry["hermit_a"]
            b = entry["hermit_b"]
            count = entry["shared_event_count"]
            plural = "s" if count != 1 else ""
            titles = entry.get("event_titles", [])
            title_str = ", ".join(f"*{t}*" for t in titles[:2])
            suffix = f" — {title_str}" if title_str else ""
            lines.append(
                f"- **{a} & {b}**: {count} shared event{plural}{suffix}"
            )
        lines.append("")
    else:
        lines.append(
            "*No multi-hermit collaboration events recorded for this season.*"
        )
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.season_digest",
        description=(
            "Generate a shareable Season in Review digest for a Hermitcraft "
            "season.  Combines highlights, collaborations, and a narrative arc "
            "summary into one document."
        ),
    )
    mode_group = p.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--season",
        type=int,
        metavar="N",
        help="Season number (1–11)",
    )
    mode_group.add_argument(
        "--list",
        action="store_true",
        help="List available season numbers and exit",
    )
    p.add_argument(
        "--top",
        type=int,
        default=_DEFAULT_TOP_N,
        metavar="N",
        help=f"Number of highlights to include (default: {_DEFAULT_TOP_N})",
    )

    fmt_group = p.add_mutually_exclusive_group()
    fmt_group.add_argument(
        "--markdown",
        action="store_true",
        default=False,
        help="Output as markdown (default when neither flag is given)",
    )
    fmt_group.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print("Available seasons:", ", ".join(str(s) for s in KNOWN_SEASONS))
        return 0

    season = args.season
    if season not in KNOWN_SEASONS:
        print(
            f"[season_digest] Season {season} not found. "
            f"Available: {', '.join(str(s) for s in KNOWN_SEASONS)}",
            file=sys.stderr,
        )
        return 1

    digest = build_digest(season, top_n=args.top)

    if args.json:
        print(json.dumps(digest, indent=2))
    else:
        # --markdown is default when neither flag is given
        print(render_markdown(digest))

    return 0


if __name__ == "__main__":
    sys.exit(main())
