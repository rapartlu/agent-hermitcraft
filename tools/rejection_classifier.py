"""
rejection_classifier.py

Classifies verifier rejections as 'fixable' (agent can retry) or
'infrastructure-blocked' (requires human/orchestrator intervention).

Usage:
    python tools/rejection_classifier.py --score 0.35 --notes "gh CLI not authenticated"

Exit codes:
    0  — fixable, agent should retry
    1  — infrastructure-blocked, escalate to orchestrator
    2  — unexpected error
"""

import argparse
import json
import sys
import re

# Keywords that indicate an environment/infrastructure problem rather than
# a knowledge or logic error the agent can fix by itself.
INFRA_PATTERNS = [
    r"not authenticated",
    r"gh cli",
    r"github[_ ]token",
    r"permission denied",
    r"env(ironment)? (var|variable)",
    r"container",
    r"no such file or directory",
    r"command not found",
    r"network (error|timeout|unreachable)",
    r"rate.?limit",
    r"quota exceeded",
    r"deploy",
    r"secret",
    r"credentials?",
    r"ssh key",
    r"certificate",
    r"port \d+ (already in use|unavailable)",
    r"cannot connect",
    r"connection refused",
    r"dns (lookup|resolution)",
]

# Score threshold below which we classify more aggressively
LOW_SCORE_THRESHOLD = 0.5


def classify(score: float, notes: str) -> dict:
    """
    Returns a classification dict:
        {
            "classification": "fixable" | "infrastructure-blocked",
            "confidence": float,   # 0.0-1.0
            "matched_pattern": str | None,
            "recommended_action": str,
        }
    """
    notes_lower = notes.lower()

    matched = None
    for pattern in INFRA_PATTERNS:
        if re.search(pattern, notes_lower):
            matched = pattern
            break

    if matched:
        return {
            "classification": "infrastructure-blocked",
            "confidence": 0.9,
            "matched_pattern": matched,
            "recommended_action": (
                "Escalate to orchestrator. Do not redispatch to agent — "
                "the environment is missing a capability. "
                f"Matched signal: '{matched}'."
            ),
        }

    # No infra signal — treat as a fixable knowledge/logic error
    confidence = 0.8 if score < LOW_SCORE_THRESHOLD else 0.65
    return {
        "classification": "fixable",
        "confidence": confidence,
        "matched_pattern": None,
        "recommended_action": (
            "Dispatch revision guidance to the agent with specific "
            "correction steps. Reference the failing score "
            f"({score:.2f}) and the verification notes directly."
        ),
    }


def build_routing_message(task_id: str, score: float, notes: str) -> str:
    """
    Builds a human-readable routing message for the supervisor log.
    """
    result = classify(score, notes)
    cls = result["classification"]
    action = result["recommended_action"]
    confidence = result["confidence"]

    if cls == "infrastructure-blocked":
        header = f"[verifier] Task {task_id} INFRASTRUCTURE-BLOCKED (score {score:.2f}, confidence {confidence:.0%})"
    else:
        header = f"[verifier] Task {task_id} FIXABLE rejection (score {score:.2f}, confidence {confidence:.0%})"

    return f"{header}\nAction: {action}\nNotes: {notes}"


def main():
    parser = argparse.ArgumentParser(description="Classify a verifier rejection.")
    parser.add_argument("--task-id", default="UNKNOWN", help="Task ID")
    parser.add_argument("--score", type=float, required=True, help="Verifier score (0.0-1.0)")
    parser.add_argument("--notes", required=True, help="Verification notes / rejection reason")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Output as JSON")
    args = parser.parse_args()

    result = classify(args.score, args.notes)
    result["task_id"] = args.task_id
    result["score"] = args.score

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(build_routing_message(args.task_id, args.score, args.notes))

    # Exit 1 if infrastructure-blocked so callers can branch on exit code
    sys.exit(1 if result["classification"] == "infrastructure-blocked" else 0)


if __name__ == "__main__":
    main()
