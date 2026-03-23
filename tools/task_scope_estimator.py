"""
task_scope_estimator.py

Estimates the scope of a task description and recommends whether to
dispatch it as a single-agent task or decompose it with --plan.

Problem: large-scope tasks (e.g. "document all Hermitcraft seasons")
dispatched as single-agent tasks silently time out. The dispatcher
should detect high-scope tasks up front and apply --plan automatically.

Scoring:
  Each signal adds points to a raw score (0–100+). The score maps to
  a dispatch recommendation:
    < 30   — single  (dispatch directly)
    30–59  — warn    (single, but flag to supervisor; consider --plan)
    ≥ 60   — plan    (decompose with --plan before dispatching)

Usage:
    python tools/task_scope_estimator.py --task "research and document all 11 seasons"
    python tools/task_scope_estimator.py --task "fix typo in season-1.md"
    python tools/task_scope_estimator.py --task "..." --json
    echo "document all hermits" | python tools/task_scope_estimator.py --stdin

Exit codes:
    0  — single (safe to dispatch directly)
    1  — warn   (single but elevated scope; consider --plan)
    2  — plan   (must decompose before dispatching)
    3  — unexpected error
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Optional


# ── Scope signals ──────────────────────────────────────────────────────────────

@dataclass
class Signal:
    name: str
    pattern: str          # regex applied to lowercased task text
    points: int
    reason: str


SIGNALS: list[Signal] = [
    # Broad-scope quantifiers
    Signal("all_items",      r"\ball\b.{0,30}(seasons?|hermits?|episodes?|files?|pages?|entries)", 25,
           "task covers 'all' of a category"),
    Signal("every_item",     r"\bevery\b.{0,20}(season|hermit|episode|file|page|entry)",           25,
           "task covers 'every' item in a category"),
    Signal("document_every", r"document\s+every",                                                   20,
           "explicit 'document every' pattern"),
    Signal("research_write_n", r"research\s+and\s+(write|document).{0,30}\d+",                     20,
           "research+write N items pattern"),
    Signal("n_items_large",  r"\b(1[0-9]|[2-9]\d)\b.{0,15}(seasons?|hermits?|files?|profiles?)",  15,
           "10+ explicit items mentioned"),
    Signal("n_items_medium", r"\b[5-9]\b.{0,15}(seasons?|hermits?|files?|profiles?)",              10,
           "5-9 explicit items mentioned"),

    # Work-type multipliers
    Signal("create_multiple",r"(create|write|add|generate).{0,20}(profiles?|files?|pages?|entries)", 10,
           "creating multiple artefacts"),
    Signal("research_multi", r"research.{0,30}(and|then|also).{0,30}(document|write|create)",      10,
           "research-then-write pipeline"),
    Signal("comprehensive",  r"\b(comprehensive|complete|full|entire|whole)\b",                     10,
           "comprehensive scope keyword"),
    Signal("each_item",      r"\beach\b.{0,20}(season|hermit|episode|profile)",                     10,
           "'each' item pattern"),

    # Description length (long descriptions often signal complex tasks)
    Signal("long_description", r"(?s).{200,}",                                                       5,
           "description > 200 chars"),
    Signal("very_long_description", r"(?s).{400,}",                                                  5,
           "description > 400 chars"),

    # Explicit decomposition hints
    Signal("multiple_prs",   r"(multiple|several)\s+prs?",                                          20,
           "task explicitly requires multiple PRs"),
    Signal("phase_hint",     r"\b(phase|step|part|batch|chunk)\s+\d",                               15,
           "phased/batched work hinted"),
    Signal("season_range",   r"season[s]?\s+\d+\s*([-–—to]+)\s*\d+",                               15,
           "season range mentioned (e.g. seasons 1-5)"),
]

# Signals that reduce scope (task is clearly narrow)
NEGATIVE_SIGNALS: list[Signal] = [
    Signal("fix_single",     r"\bfix\b.{0,30}(typo|spelling|date|name|link|url|error)\b",          -20,
           "fixing a single small error"),
    Signal("single_file",    r"\b(one|a single|the)\s+(file|season|hermit|profile|entry)\b",        -15,
           "explicitly one file/item"),
    Signal("update_field",   r"\bupdate\b.{0,20}(field|value|date|name|link)\b",                   -10,
           "updating a single field"),
    Signal("add_note",       r"\b(add|append)\b.{0,20}(note|comment|clarification)\b",             -10,
           "adding a brief annotation"),
]

SCORE_SINGLE = 30   # below this → single
SCORE_PLAN   = 60   # at or above this → plan


@dataclass
class ScopeEstimate:
    task: str
    raw_score: int
    recommendation: str        # "single" | "warn" | "plan"
    dispatch_flag: str         # "" | "--plan"
    matched_signals: list      # list of {name, points, reason}
    exit_code: int
    explanation: str


def estimate(task: str) -> ScopeEstimate:
    text = task.lower()
    matched = []
    score = 0

    for sig in SIGNALS + NEGATIVE_SIGNALS:
        if re.search(sig.pattern, text):
            score += sig.points
            matched.append({"name": sig.name, "points": sig.points, "reason": sig.reason})

    score = max(0, score)  # clamp to 0

    if score >= SCORE_PLAN:
        rec = "plan"
        flag = "--plan"
        exit_code = 2
        explanation = (
            f"Score {score} ≥ {SCORE_PLAN}: task scope is high. "
            "Decompose with --plan before dispatching to avoid timeouts."
        )
    elif score >= SCORE_SINGLE:
        rec = "warn"
        flag = ""
        exit_code = 1
        explanation = (
            f"Score {score} is elevated ({SCORE_SINGLE}–{SCORE_PLAN - 1}). "
            "Single-agent dispatch may work but consider --plan if the task times out."
        )
    else:
        rec = "single"
        flag = ""
        exit_code = 0
        explanation = (
            f"Score {score} < {SCORE_SINGLE}: task scope is low. "
            "Safe to dispatch as a single-agent task."
        )

    return ScopeEstimate(
        task=task,
        raw_score=score,
        recommendation=rec,
        dispatch_flag=flag,
        matched_signals=matched,
        exit_code=exit_code,
        explanation=explanation,
    )


def format_report(est: ScopeEstimate) -> str:
    icon = {"single": "✓", "warn": "⚠", "plan": "⛔"}[est.recommendation]
    lines = [
        f"{icon}  Scope: {est.recommendation.upper()}  (score {est.raw_score})",
        f"   {est.explanation}",
    ]
    if est.dispatch_flag:
        lines.append(f"   Dispatch flag: {est.dispatch_flag}")
    if est.matched_signals:
        lines.append("   Matched signals:")
        for s in est.matched_signals:
            sign = "+" if s["points"] >= 0 else ""
            lines.append(f"     {sign}{s['points']:3d}  {s['name']}: {s['reason']}")
    return "\n".join(lines)


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Estimate task scope and recommend dispatch mode."
        )
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument("--task", help="Task description string")
        src.add_argument("--stdin", action="store_true", help="Read task from stdin")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Output as JSON")
        args = parser.parse_args()

        task_text = sys.stdin.read().strip() if args.stdin else args.task
        est = estimate(task_text)

        if args.as_json:
            print(json.dumps(asdict(est), indent=2))
        else:
            print(format_report(est))

        sys.exit(est.exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[task_scope_estimator] unexpected error: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
