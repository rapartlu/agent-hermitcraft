"""
tools/season_digest.py — Shareable "Season in Review" digest generator.

Combines per-season highlights, collaborations, and a narrative arc summary
into one ready-to-share document.  The markdown output can be pasted directly
into a Discord message, a Reddit post, or a wiki page; the JSON output feeds
downstream tools such as a Discord bot or static site generator; the Discord
embed output can be POSTed directly to a Discord webhook.

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
  --discord              Discord embed JSON payload (POST to a webhook directly)

Discord embed limits enforced automatically:
  Field value  ≤ 1 024 chars   Embed title ≤ 256 chars
  Total embed  ≤ 6 000 chars   Truncated with … rather than hard-cut

Usage:
    python -m tools.season_digest --season 9
    python -m tools.season_digest --season 9 --top 3
    python -m tools.season_digest --season 9 --json
    python -m tools.season_digest --season 9 --markdown
    python -m tools.season_digest --season 9 --discord
    python -m tools.season_digest --list
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import re
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
# Discord embed renderer
# ---------------------------------------------------------------------------

# Discord API hard limits
_DISCORD_TITLE_LIMIT: int = 256
_DISCORD_FIELD_VALUE_LIMIT: int = 1024
_DISCORD_EMBED_TOTAL_LIMIT: int = 6000
_DISCORD_FIELD_NAME_LIMIT: int = 256

# One distinct colour per season (decimal RGB, matching Discord's colour int).
# Chosen to be visually distinct across the 11 seasons.
_SEASON_COLOURS: dict[int, int] = {
    1:  0x1ABC9C,   # teal          — founding era
    2:  0x2ECC71,   # green
    3:  0x3498DB,   # blue
    4:  0x9B59B6,   # purple
    5:  0xE91E63,   # pink
    6:  0xF39C12,   # orange        — "golden age" begins
    7:  0xE74C3C,   # red
    8:  0x1E88E5,   # bright blue   — Demise / Last Life cross-over era
    9:  0x00BCD4,   # cyan          — longest season ever
    10: 0x8BC34A,   # lime green
    11: 0x7E57C2,   # indigo
}
_COLOUR_DEFAULT: int = 0x99AAB5  # Discord grey fallback


def _truncate(text: str, max_len: int, suffix: str = " …") -> str:
    """Return *text* truncated to *max_len* chars, appending *suffix* if cut.

    Truncation is word-aware: the cut happens at the last space before the
    limit so words are never split mid-character.
    """
    if len(text) <= max_len:
        return text
    cut_at = max_len - len(suffix)
    # Walk back to a word boundary
    boundary = text.rfind(" ", 0, cut_at)
    if boundary <= 0:
        boundary = cut_at
    return text[:boundary] + suffix


def _discord_stats_value(stats: dict) -> str:
    """Compact stats line for a Discord embed field value."""
    date_start = stats.get("date_start") or "unknown"
    date_end = stats.get("date_end") or "unknown"
    hermit_count = stats.get("hermit_count", 0)
    event_count = stats.get("event_count", 0)
    breakdown = stats.get("type_breakdown", {})

    lines = [
        f"📅 {date_start} → {date_end}",
        f"👥 {hermit_count} hermits · {event_count} documented events",
    ]
    if breakdown:
        top_types = sorted(breakdown.items(), key=lambda x: -x[1])[:3]
        lines.append("📊 " + ", ".join(f"{t}: {c}" for t, c in top_types))

    return "\n".join(lines)


def _discord_peak_value(peak: dict) -> str:
    """One-block peak-moment field value."""
    title = peak.get("title", "(untitled)")
    score = peak.get("significance_score", 0)
    date = peak.get("date", "")
    hermits = peak.get("hermits", [])
    desc = peak.get("description", "")

    hermit_str = "All hermits" if hermits == ["All"] else ", ".join(hermits[:3])
    header = f"**{title}** *(score: {score})*"
    meta = f"{date} · {hermit_str}" if date else hermit_str

    parts = [header, meta]
    if desc:
        # Trim description to fit the remaining character budget.
        # Note: if header + meta already exceed the field limit, budget goes
        # negative and the description is simply skipped (budget ≤ 40 guard).
        # The caller always wraps the return value in _truncate(...,
        # _DISCORD_FIELD_VALUE_LIMIT) as a final clamp, so the hard limit is
        # always honoured regardless.
        budget = _DISCORD_FIELD_VALUE_LIMIT - len(header) - len(meta) - 4
        if budget > 40:
            parts.append(_truncate(desc, budget))

    return "\n".join(p for p in parts if p)


def _discord_highlights_value(highlights: list[dict]) -> tuple[str, int]:
    """Numbered list of highlights, truncated to fit the field limit.

    Returns a ``(text, rendered_count)`` tuple so callers can label the field
    accurately even when the list is cut short by the character budget.
    """
    lines: list[str] = []
    for entry in highlights:
        rank = entry["rank"]
        title = entry["title"]
        ev_type = entry.get("type", "")
        score = entry.get("significance_score", 0)
        type_tag = f" `{ev_type}`" if ev_type else ""
        line = f"{rank}. **{title}**{type_tag} *(score: {score})*"
        # Add line only while we stay within the limit
        candidate = "\n".join(lines + [line])
        if len(candidate) > _DISCORD_FIELD_VALUE_LIMIT - 4:
            lines.append(" …")
            break
        lines.append(line)
    text = "\n".join(lines) if lines else "*No highlights available.*"
    return text, len(lines)


def _discord_collabs_value(collabs: list[dict]) -> str:
    """Bullet list of top collaborating pairs."""
    if not collabs:
        return "*No multi-hermit collaborations recorded.*"
    lines: list[str] = []
    for entry in collabs:
        a = entry["hermit_a"]
        b = entry["hermit_b"]
        count = entry["shared_event_count"]
        plural = "s" if count != 1 else ""
        titles = entry.get("event_titles", [])
        title_note = f" — {titles[0]}" if titles else ""
        line = f"• **{a} & {b}**: {count} event{plural}{title_note}"
        candidate = "\n".join(lines + [line])
        if len(candidate) > _DISCORD_FIELD_VALUE_LIMIT - 4:
            lines.append(" …")
            break
        lines.append(line)
    return "\n".join(lines)


def build_discord_embed(digest: dict) -> dict:
    """
    Build a Discord embed dict from *digest*.

    The returned dict is a single embed object (not the outer ``{"embeds": […]}``
    wrapper) so callers can compose multiple embeds if needed.

    All field values are guaranteed to be ≤ ``_DISCORD_FIELD_VALUE_LIMIT``
    characters.  The function also trims the total embed character count to
    stay within ``_DISCORD_EMBED_TOTAL_LIMIT``.

    Structure::

        {
            "title":  "🏆 Hermitcraft Season N — Season in Review",
            "color":  <int>,
            "fields": [
                {"name": "📊 Quick Stats",         "value": "…", "inline": False},
                {"name": "📖 Season Arc",           "value": "…", "inline": False},
                {"name": "🌟 Peak Moment",          "value": "…", "inline": False},
                {"name": "🏅 Top Highlights",       "value": "…", "inline": False},
                {"name": "🤝 Notable Collaborations","value": "…", "inline": False},
            ],
            "footer": {"text": "hermitcraft-agent • /digest season N"},
        }
    """
    season = digest["season"]
    stats = digest.get("stats", {})
    highlights = digest.get("highlights", [])
    peak = digest.get("peak_moment")
    collabs = digest.get("collaborations", [])
    arc = digest.get("arc_summary", "")

    title = _truncate(
        f"🏆 Hermitcraft Season {season} — Season in Review",
        _DISCORD_TITLE_LIMIT,
    )
    colour = _SEASON_COLOURS.get(season, _COLOUR_DEFAULT)

    # Arc: trim to 2 sentences for embed brevity.
    # Use a lookbehind on sentence-ending punctuation + whitespace so that
    # abbreviations (e.g. "1.16.2") and version numbers don't cause false splits.
    arc_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", arc)
        if s.strip()
    ]
    arc_short = " ".join(arc_sentences[:2])
    arc_value = _truncate(arc_short, _DISCORD_FIELD_VALUE_LIMIT)

    fields: list[dict] = [
        {
            "name": "📊 Quick Stats",
            "value": _truncate(_discord_stats_value(stats),
                                _DISCORD_FIELD_VALUE_LIMIT),
            "inline": False,
        },
        {
            "name": "📖 Season Arc",
            "value": arc_value or "*No arc summary available.*",
            "inline": False,
        },
    ]

    if peak:
        fields.append(
            {
                "name": "🌟 Peak Moment",
                "value": _truncate(_discord_peak_value(peak),
                                   _DISCORD_FIELD_VALUE_LIMIT),
                "inline": False,
            }
        )

    if highlights:
        highlights_text, rendered_count = _discord_highlights_value(highlights)
        fields.append(
            {
                # Use the *rendered* count, not len(highlights), so the label
                # stays accurate when the character budget truncates the list.
                "name": f"🏅 Top {rendered_count} Highlights",
                "value": highlights_text,
                "inline": False,
            }
        )

    fields.append(
        {
            "name": "🤝 Notable Collaborations",
            "value": _discord_collabs_value(collabs),
            "inline": False,
        }
    )

    embed: dict = {
        "title": title,
        "color": colour,
        "fields": fields,
        "footer": {"text": f"hermitcraft-agent • /digest season {season}"},
    }

    # ── Safety trim: ensure total character count ≤ embed limit ─────────────
    # Count: title + all field names + all field values + footer text
    def _embed_char_count(e: dict) -> int:
        total = len(e.get("title", ""))
        for f in e.get("fields", []):
            total += len(f.get("name", "")) + len(f.get("value", ""))
        total += len(e.get("footer", {}).get("text", ""))
        return total

    # If over limit, progressively shorten the longest field values
    while _embed_char_count(embed) > _DISCORD_EMBED_TOTAL_LIMIT and embed["fields"]:
        # Find the field with the longest value and shorten it
        longest = max(embed["fields"], key=lambda f: len(f["value"]))
        if len(longest["value"]) <= 50:
            # Nothing meaningful left to trim; remove the field instead
            embed["fields"].remove(longest)
        else:
            longest["value"] = _truncate(
                longest["value"],
                len(longest["value"]) - 100,
            )

    # Last resort: if title + footer alone exceed the limit (pathological case
    # where all fields have been stripped), clamp title so the embed always
    # satisfies the Discord total-character constraint.
    if _embed_char_count(embed) > _DISCORD_EMBED_TOTAL_LIMIT:
        footer_text = embed.get("footer", {}).get("text", "")
        remaining = _DISCORD_EMBED_TOTAL_LIMIT - len(footer_text)
        embed["title"] = _truncate(embed["title"], max(10, remaining))

    return embed


def render_discord(digest: dict) -> str:
    """
    Render *digest* as a Discord webhook-ready JSON string.

    The output is the ``{"embeds": […]}`` wrapper expected by the Discord
    webhook API — pipe it straight to ``curl -d @- <webhook_url>``.
    """
    embed = build_discord_embed(digest)
    return json.dumps({"embeds": [embed]}, indent=2, ensure_ascii=False)


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
    fmt_group.add_argument(
        "--discord",
        action="store_true",
        default=False,
        help=(
            "Output as a Discord embed JSON payload — POST directly to a "
            "webhook.  Field values are automatically trimmed to Discord's "
            "1 024-char limit; total embed stays under 6 000 chars."
        ),
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
    elif args.discord:
        print(render_discord(digest))
    else:
        # --markdown is default when neither flag is given
        print(render_markdown(digest))

    return 0


if __name__ == "__main__":
    sys.exit(main())
