"""
verification_backlog.py

Analyses a JSON task dump and reports the current verification backlog:
  - unverified done tasks (quality_score=null, status=done)
  - verification lag distribution
  - recommendations based on backlog size

Usage:
    python tools/verification_backlog.py --tasks tasks.json
    python tools/verification_backlog.py --tasks tasks.json --json
    echo '[{"id":"abc","status":"done","quality_score":null}]' | \\
        python tools/verification_backlog.py --stdin

Exit codes:
    0  — backlog within acceptable range (< 5 unverified tasks)
    1  — backlog elevated (5-9 unverified tasks); consider raising batch size
    2  — backlog critical (>= 10 unverified tasks); decouple verification loop
    3  — unexpected error
"""

import argparse
import json
import sys
from datetime import datetime, timezone


BACKLOG_WARN_THRESHOLD = 5    # exit 1
BACKLOG_CRIT_THRESHOLD = 10   # exit 2


def analyse(tasks: list) -> dict:
    """
    Accepts a list of task dicts and returns a backlog analysis report.
    Expected task fields (all optional except 'status'):
        id, status, quality_score, verification_status, updated_at (ISO8601)
    """
    total = len(tasks)
    done = [t for t in tasks if t.get("status") == "done"]
    unverified = [
        t for t in done
        if t.get("quality_score") is None
        and t.get("verification_status") not in ("in_progress", "verified")
    ]
    in_progress_verification = [
        t for t in done
        if t.get("verification_status") == "in_progress"
    ]
    verified = [t for t in done if t.get("quality_score") is not None]

    # Compute lag for tasks that have updated_at
    now = datetime.now(timezone.utc)
    lags = []
    for t in unverified:
        updated = t.get("updated_at")
        if updated:
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                lags.append((now - dt).total_seconds())
            except ValueError:
                pass

    lags.sort()
    lag_p50 = lags[len(lags) // 2] if lags else None
    lag_p95 = lags[int(len(lags) * 0.95)] if lags else None
    lag_max = lags[-1] if lags else None

    unverified_count = len(unverified)
    if unverified_count >= BACKLOG_CRIT_THRESHOLD:
        severity = "critical"
        recommendation = (
            f"Backlog is critical ({unverified_count} unverified tasks). "
            "Decouple verification into a higher-frequency sub-loop running "
            "every 5s with batch size 10. See prompts/verification-backlog-strategy.md."
        )
        exit_code = 2
    elif unverified_count >= BACKLOG_WARN_THRESHOLD:
        severity = "elevated"
        recommendation = (
            f"Backlog is elevated ({unverified_count} unverified tasks). "
            "Raise per-cycle verification limit from 3 to 8 as an interim fix."
        )
        exit_code = 1
    else:
        severity = "ok"
        recommendation = (
            f"Backlog is within acceptable range ({unverified_count} unverified tasks)."
        )
        exit_code = 0

    return {
        "summary": {
            "total_tasks": total,
            "done_tasks": len(done),
            "unverified_done": unverified_count,
            "in_progress_verification": len(in_progress_verification),
            "verified_done": len(verified),
        },
        "lag_seconds": {
            "p50": round(lag_p50, 1) if lag_p50 is not None else None,
            "p95": round(lag_p95, 1) if lag_p95 is not None else None,
            "max": round(lag_max, 1) if lag_max is not None else None,
        },
        "severity": severity,
        "recommendation": recommendation,
        "exit_code": exit_code,
    }


def format_report(report: dict) -> str:
    s = report["summary"]
    lag = report["lag_seconds"]
    lines = [
        f"Verification Backlog Report",
        f"  Total tasks:              {s['total_tasks']}",
        f"  Done (total):             {s['done_tasks']}",
        f"  Unverified done:          {s['unverified_done']}",
        f"  Verification in-progress: {s['in_progress_verification']}",
        f"  Verified done:            {s['verified_done']}",
        f"  Lag p50:  {lag['p50']}s" if lag["p50"] is not None else "  Lag p50:  n/a",
        f"  Lag p95:  {lag['p95']}s" if lag["p95"] is not None else "  Lag p95:  n/a",
        f"  Lag max:  {lag['max']}s" if lag["max"] is not None else "  Lag max:  n/a",
        f"",
        f"Severity: {report['severity'].upper()}",
        f"Recommendation: {report['recommendation']}",
    ]
    return "\n".join(lines)


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Analyse verification backlog from a JSON task dump."
        )
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--tasks", help="Path to JSON file containing task list")
        source.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Output as JSON")
        args = parser.parse_args()

        if args.stdin:
            raw = sys.stdin.read()
        else:
            with open(args.tasks) as f:
                raw = f.read()

        tasks = json.loads(raw)
        if not isinstance(tasks, list):
            raise ValueError("Input must be a JSON array of task objects")

        report = analyse(tasks)
        exit_code = report["exit_code"]

        if args.as_json:
            print(json.dumps(report, indent=2))
        else:
            print(format_report(report))

        sys.exit(exit_code)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[verification_backlog] unexpected error: {exc}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
