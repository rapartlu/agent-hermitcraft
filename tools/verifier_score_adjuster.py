"""
verifier_score_adjuster.py

Adjusts a raw verifier score when infrastructure blockers are detected
in the task result text, and assigns one of three verification statuses:

    verified   — score >= 0.75, no blocker
    rejected   — score < 0.75, no blocker (agent error, can retry)
    blocked    — infrastructure blocker detected regardless of score

Problem: tasks 01KMC04C (0.45) and 01KMC05Z (0.35) were scored against
the final observable outcome (no PR created) without accounting for the
missing GH_TOKEN that prevented the push.  The agent completed all code
work correctly — only the infra step failed.

Adjustment logic:
  1. Scan the result text for INFRA_PATTERNS (imported from rejection_classifier).
  2. If a blocker is found:
       a. Identify the blocker's contribution to the task (INFRA_WEIGHT).
       b. Re-score only the agent's portion: adjusted = raw / (1 - INFRA_WEIGHT)
          capped at 1.0.
       c. Set status = 'blocked' regardless of the adjusted score.
  3. If no blocker: status = 'verified' if score >= ACCEPT_THRESHOLD else 'rejected'.

Usage:
    python tools/verifier_score_adjuster.py --score 0.35 \\
        --result "All files committed. gh push failed: GITHUB_TOKEN not set."

    python tools/verifier_score_adjuster.py --score 0.35 \\
        --result-file result.txt --json

Exit codes:
    0  — verified
    1  — rejected  (agent should retry)
    2  — blocked   (orchestrator must fix infra)
    3  — unexpected error
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Optional

# Import infra patterns from sibling module to keep detection logic in one place
try:
    from tools.rejection_classifier import INFRA_PATTERNS
except ImportError:
    # Allow running from repo root or tools/ directory
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from tools.rejection_classifier import INFRA_PATTERNS

# Score at or above which work is accepted (no blocker path)
ACCEPT_THRESHOLD = 0.75

# Fraction of a typical task that infra steps (push, PR creation) represent.
# When a blocker prevents only this portion, we credit the agent for the rest.
INFRA_WEIGHT = 0.25


@dataclass
class AdjustmentResult:
    raw_score: float
    adjusted_score: float
    status: str                     # "verified" | "rejected" | "blocked"
    blocker_detected: bool
    matched_pattern: Optional[str]
    adjustment_note: str
    exit_code: int


def detect_blocker(text: str) -> Optional[str]:
    """Return the first matching INFRA_PATTERN found in text, or None."""
    lower = text.lower()
    for pattern in INFRA_PATTERNS:
        if re.search(pattern, lower):
            return pattern
    return None


def adjust(raw_score: float, result_text: str) -> AdjustmentResult:
    matched = detect_blocker(result_text)

    if matched:
        # Re-score only the agent-controlled portion of the work.
        # If infra accounts for INFRA_WEIGHT of the task, then:
        #   raw_score = agent_score * (1 - INFRA_WEIGHT) + 0 * INFRA_WEIGHT
        #   agent_score = raw_score / (1 - INFRA_WEIGHT)
        agent_score = min(raw_score / (1 - INFRA_WEIGHT), 1.0)
        note = (
            f"Infrastructure blocker detected ('{matched}'). "
            f"Raw score {raw_score:.2f} re-scored to {agent_score:.2f} "
            f"after removing {INFRA_WEIGHT:.0%} infra weight. "
            f"Status set to 'blocked' — do not re-dispatch agent; fix infra first."
        )
        return AdjustmentResult(
            raw_score=raw_score,
            adjusted_score=round(agent_score, 4),
            status="blocked",
            blocker_detected=True,
            matched_pattern=matched,
            adjustment_note=note,
            exit_code=2,
        )

    # No blocker — standard accept/reject threshold
    if raw_score >= ACCEPT_THRESHOLD:
        note = f"Score {raw_score:.2f} >= {ACCEPT_THRESHOLD} threshold. Work accepted."
        status, exit_code = "verified", 0
    else:
        note = (
            f"Score {raw_score:.2f} < {ACCEPT_THRESHOLD} threshold and no infra blocker. "
            f"Agent error — dispatch revision guidance."
        )
        status, exit_code = "rejected", 1

    return AdjustmentResult(
        raw_score=raw_score,
        adjusted_score=raw_score,
        status=status,
        blocker_detected=False,
        matched_pattern=None,
        adjustment_note=note,
        exit_code=exit_code,
    )


def format_report(r: AdjustmentResult) -> str:
    icon = {"verified": "✓", "rejected": "✗", "blocked": "⚠"}[r.status]
    lines = [
        f"{icon}  Status: {r.status.upper()}",
        f"   Raw score:      {r.raw_score:.2f}",
    ]
    if r.blocker_detected:
        lines.append(f"   Adjusted score: {r.adjusted_score:.2f}  (infra portion removed)")
        lines.append(f"   Blocker signal: {r.matched_pattern}")
    lines.append(f"   Note: {r.adjustment_note}")
    return "\n".join(lines)


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Adjust verifier score for infrastructure blockers."
        )
        parser.add_argument("--score", type=float, required=True,
                            help="Raw verifier score (0.0–1.0)")
        src = parser.add_mutually_exclusive_group(required=True)
        src.add_argument("--result", help="Task result text string")
        src.add_argument("--result-file", help="Path to file containing result text")
        src.add_argument("--stdin", action="store_true", help="Read result text from stdin")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Output as JSON")
        args = parser.parse_args()

        if args.stdin:
            result_text = sys.stdin.read()
        elif args.result_file:
            with open(args.result_file) as f:
                result_text = f.read()
        else:
            result_text = args.result

        r = adjust(args.score, result_text)

        if args.as_json:
            print(json.dumps(asdict(r), indent=2))
        else:
            print(format_report(r))

        sys.exit(r.exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[verifier_score_adjuster] unexpected error: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
