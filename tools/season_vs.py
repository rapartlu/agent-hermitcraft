"""
tools/season_vs.py — Head-to-head season comparison for Hermitcraft.

Implements the ``GET /seasons/:id/vs/:id2`` endpoint contract: compares two
Hermitcraft seasons across multiple activity dimensions and declares a
``winner`` with a brief rationale drawn from measurable metrics.

Dimensions compared
-------------------
  event_count      Total timeline events documented
  member_count     Named hermits on the roster
  build_count      Documented major builds
  collab_count     Events involving two or more named hermits
  highlight_score  Sum of significance scores for the top-5 events

Winner determination
--------------------
  Each dimension is scored as a simple win (1) or loss (0) for season A.
  The season with more dimension wins is declared winner.  On a tie the
  season with the higher highlight_score wins.  If still tied, it's a draw.

Output modes
------------
  --text   (default)  Formatted side-by-side comparison table
  --json              Structured dict for downstream tooling

HTTP API contract
-----------------
  GET /seasons/:id/vs/:id2
      Path params: id, id2  — season numbers (1–11)
      Response (JSON):
          {
              "season_a": <int>,
              "season_b": <int>,
              "comparison": {
                  "event_count":     {"a": <int>, "b": <int>, "winner": "a"|"b"|"tie"},
                  "member_count":    {"a": <int>, "b": <int>, "winner": "a"|"b"|"tie"},
                  "build_count":     {"a": <int>, "b": <int>, "winner": "a"|"b"|"tie"},
                  "collab_count":    {"a": <int>, "b": <int>, "winner": "a"|"b"|"tie"},
                  "highlight_score": {"a": <int>, "b": <int>, "winner": "a"|"b"|"tie"},
              },
              "winner": "a"|"b"|"tie",
              "winner_season": <int>|null,
              "rationale": "<one-sentence explanation>",
              "metadata": {
                  "a": {"season": <int>, "duration": "...", "minecraft_version": "..."},
                  "b": {"season": <int>, "duration": "...", "minecraft_version": "..."},
              }
          }
      404 (exit 1): if either season number is out of range (1–11)

Usage
-----
    python -m tools.season_vs --a 9 --b 10
    python -m tools.season_vs --a 7 --b 9 --json
    python -m tools.season_vs --list
"""

from __future__ import annotations

import argparse
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

# ---------------------------------------------------------------------------
# Significance scoring (local copy — avoids circular imports)
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
# Season metadata (from season_recap)
# ---------------------------------------------------------------------------

def _load_season_meta(season: int) -> dict:
    """Pull lightweight metadata for *season* from season_recap."""
    try:
        from tools.season_recap import build_recap  # type: ignore
        recap = build_recap(season)
        return {
            "season": season,
            "duration": recap.get("duration", ""),
            "minecraft_version": recap.get("minecraft_version", ""),
            "member_count_from_recap": recap.get("member_count", 0),
            "major_builds": recap.get("major_builds", []),
        }
    except Exception:
        return {
            "season": season,
            "duration": "",
            "minecraft_version": "",
            "member_count_from_recap": 0,
            "major_builds": [],
        }


# ---------------------------------------------------------------------------
# Dimension extractors
# ---------------------------------------------------------------------------

def _event_count(events: list[dict]) -> int:
    return len(events)


def _member_count(events: list[dict]) -> int:
    """Unique named hermits (excluding 'All') seen across events."""
    hermit_set: set[str] = set()
    for ev in events:
        for h in ev.get("hermits", []):
            if h != "All":
                hermit_set.add(h)
    return len(hermit_set)


def _build_count(events: list[dict], major_builds: list) -> int:
    """Build events from timeline + major_builds from recap."""
    timeline_builds = sum(1 for ev in events if ev.get("type") == "build")
    return timeline_builds + len(major_builds)


def _collab_count(events: list[dict]) -> int:
    """Events involving two or more named hermits (excluding 'All' catchall)."""
    count = 0
    for ev in events:
        hermits = ev.get("hermits", [])
        if hermits == ["All"]:
            continue
        named = [h for h in hermits if h != "All"]
        if len(named) >= 2:
            count += 1
    return count


def _highlight_score(events: list[dict], top_n: int = 5) -> int:
    """Sum of significance scores for the top *top_n* events."""
    scored = sorted(events, key=_significance_score, reverse=True)
    return sum(_significance_score(ev) for ev in scored[:top_n])


# ---------------------------------------------------------------------------
# Comparison builder
# ---------------------------------------------------------------------------

def _dim_winner(a_val: int, b_val: int) -> str:
    if a_val > b_val:
        return "a"
    if b_val > a_val:
        return "b"
    return "tie"


def build_vs(season_a: int, season_b: int) -> dict:
    """
    Build a full head-to-head comparison between *season_a* and *season_b*.

    Returns the structured dict matching the HTTP API contract (see module
    docstring).  Never raises for valid season numbers with sparse data —
    dimensions will be 0 rather than absent.
    """
    all_events = _load_all_events()
    events_a = _season_events(all_events, season_a)
    events_b = _season_events(all_events, season_b)

    meta_a = _load_season_meta(season_a)
    meta_b = _load_season_meta(season_b)

    # Compute each dimension
    dims: dict[str, dict[str, int | str]] = {}

    ec_a = _event_count(events_a)
    ec_b = _event_count(events_b)
    dims["event_count"] = {"a": ec_a, "b": ec_b, "winner": _dim_winner(ec_a, ec_b)}

    mc_a = _member_count(events_a) or meta_a["member_count_from_recap"]
    mc_b = _member_count(events_b) or meta_b["member_count_from_recap"]
    dims["member_count"] = {"a": mc_a, "b": mc_b, "winner": _dim_winner(mc_a, mc_b)}

    bc_a = _build_count(events_a, meta_a["major_builds"])
    bc_b = _build_count(events_b, meta_b["major_builds"])
    dims["build_count"] = {"a": bc_a, "b": bc_b, "winner": _dim_winner(bc_a, bc_b)}

    cc_a = _collab_count(events_a)
    cc_b = _collab_count(events_b)
    dims["collab_count"] = {"a": cc_a, "b": cc_b, "winner": _dim_winner(cc_a, cc_b)}

    hs_a = _highlight_score(events_a)
    hs_b = _highlight_score(events_b)
    dims["highlight_score"] = {"a": hs_a, "b": hs_b, "winner": _dim_winner(hs_a, hs_b)}

    # Tally wins
    wins_a = sum(1 for d in dims.values() if d["winner"] == "a")
    wins_b = sum(1 for d in dims.values() if d["winner"] == "b")

    if wins_a > wins_b:
        overall_winner = "a"
        winner_season: int | None = season_a
    elif wins_b > wins_a:
        overall_winner = "b"
        winner_season = season_b
    else:
        # Tie-break: higher highlight_score
        if hs_a > hs_b:
            overall_winner = "a"
            winner_season = season_a
        elif hs_b > hs_a:
            overall_winner = "b"
            winner_season = season_b
        else:
            overall_winner = "tie"
            winner_season = None

    rationale = _build_rationale(
        season_a, season_b, overall_winner, wins_a, wins_b, dims
    )

    return {
        "season_a": season_a,
        "season_b": season_b,
        "comparison": dims,
        "winner": overall_winner,
        "winner_season": winner_season,
        "rationale": rationale,
        "metadata": {
            "a": {
                "season": season_a,
                "duration": meta_a["duration"],
                "minecraft_version": meta_a["minecraft_version"],
            },
            "b": {
                "season": season_b,
                "duration": meta_b["duration"],
                "minecraft_version": meta_b["minecraft_version"],
            },
        },
    }


def _build_rationale(
    season_a: int,
    season_b: int,
    winner: str,
    wins_a: int,
    wins_b: int,
    dims: dict,
) -> str:
    """One sentence explaining why the winner won (or why it's a tie)."""
    if winner == "tie":
        return (
            f"Season {season_a} and Season {season_b} are evenly matched "
            f"across all measured dimensions — too close to call."
        )

    win_season = season_a if winner == "a" else season_b
    lose_season = season_b if winner == "a" else season_a
    w = winner  # "a" or "b"

    # Identify which dims the winner won
    won_dims = [name for name, d in dims.items() if d["winner"] == w]
    # Build human-readable dim labels
    _dim_labels = {
        "event_count": "documented events",
        "member_count": "active hermits",
        "build_count": "notable builds",
        "collab_count": "collaboration events",
        "highlight_score": "highlight significance",
    }

    if not won_dims:
        return (
            f"Season {win_season} edges out Season {lose_season} via tie-break "
            f"on highlight significance score."
        )

    top_dim = won_dims[0]
    top_val_w = dims[top_dim][w]
    top_val_other = dims[top_dim]["b" if w == "a" else "a"]
    label = _dim_labels.get(top_dim, top_dim.replace("_", " "))

    wins_str = f"{max(wins_a, wins_b)}/{len(dims)}"
    return (
        f"Season {win_season} wins {wins_str} dimensions, leading most clearly "
        f"in {label} ({top_val_w} vs {top_val_other})."
    )


# ---------------------------------------------------------------------------
# Text renderer
# ---------------------------------------------------------------------------

def render_text(result: dict) -> str:
    """Format the comparison as a human-readable table."""
    sa = result["season_a"]
    sb = result["season_b"]
    dims = result["comparison"]
    winner = result["winner"]
    winner_season = result.get("winner_season")
    rationale = result["rationale"]
    meta = result["metadata"]

    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"  Season {sa}  vs  Season {sb}")
    lines.append("=" * 64)

    # Metadata row
    for key in ("a", "b"):
        s = sa if key == "a" else sb
        m = meta[key]
        dur = f"  {m['duration']}" if m.get("duration") else ""
        ver = f"  [{m['minecraft_version']}]" if m.get("minecraft_version") else ""
        lines.append(f"  S{s}:{dur}{ver}")
    lines.append("")

    # Dimension table
    _dim_labels = {
        "event_count": "Timeline events",
        "member_count": "Active hermits",
        "build_count": "Notable builds",
        "collab_count": "Collaboration events",
        "highlight_score": "Highlight score (top 5)",
    }

    col_w = 24
    lines.append(f"  {'Dimension':<{col_w}}  {'S'+str(sa):>6}  {'S'+str(sb):>6}  Winner")
    lines.append("  " + "-" * 56)

    for dim_key, label in _dim_labels.items():
        d = dims.get(dim_key, {})
        val_a = d.get("a", 0)
        val_b = d.get("b", 0)
        dim_winner = d.get("winner", "tie")
        w_label = (
            f"S{sa}" if dim_winner == "a"
            else f"S{sb}" if dim_winner == "b"
            else "tie"
        )
        lines.append(
            f"  {label:<{col_w}}  {val_a:>6}  {val_b:>6}  {w_label}"
        )

    lines.append("")

    # Overall result
    if winner == "tie":
        lines.append("  RESULT: TIE")
    else:
        lines.append(f"  RESULT: Season {winner_season} wins")

    lines.append(f"  {rationale}")
    lines.append("=" * 64)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.season_vs",
        description=(
            "Compare two Hermitcraft seasons head-to-head across event count, "
            "hermit count, builds, collaborations, and highlight significance. "
            "Declares a winner with a brief rationale."
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--a",
        type=int,
        metavar="SEASON_A",
        dest="season_a",
        help="First season number (1–11)",
    )
    mode.add_argument(
        "--list",
        action="store_true",
        help="List valid season numbers and exit",
    )
    p.add_argument(
        "--b",
        type=int,
        metavar="SEASON_B",
        dest="season_b",
        help="Second season number (1–11) — required when --a is given",
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

    if args.list:
        print("Valid seasons:", ", ".join(str(s) for s in KNOWN_SEASONS))
        return 0

    season_a: int = args.season_a
    season_b: int | None = args.season_b

    # Validate both seasons provided
    if season_b is None:
        print("[season_vs] --b SEASON_B is required when --a is given.",
              file=sys.stderr)
        return 1

    # Validate range
    bad = [s for s in (season_a, season_b) if s not in KNOWN_SEASONS]
    if bad:
        for s in bad:
            print(
                f"[season_vs] Season {s} not found. "
                f"Valid seasons: {', '.join(str(x) for x in KNOWN_SEASONS)}",
                file=sys.stderr,
            )
        return 1

    if season_a == season_b:
        print("[season_vs] --a and --b must be different seasons.",
              file=sys.stderr)
        return 1

    result = build_vs(season_a, season_b)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
