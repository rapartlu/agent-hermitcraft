"""
Tests for tools/verification_backlog.py
Run with: python3 tests/test_verification_backlog.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.verification_backlog import analyse, format_report, BACKLOG_WARN_THRESHOLD, BACKLOG_CRIT_THRESHOLD


def make_task(status="done", quality_score=None, verification_status=None, updated_at=None):
    t = {"id": "test", "status": status}
    if quality_score is not None:
        t["quality_score"] = quality_score
    if verification_status is not None:
        t["verification_status"] = verification_status
    if updated_at is not None:
        t["updated_at"] = updated_at
    return t


passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS {name}")
        passed += 1
    else:
        print(f"  FAIL {name}" + (f": {detail}" if detail else ""))
        failed += 1


print("Summary counts:")

tasks_mixed = (
    [make_task(status="done", quality_score=None)] * 4 +            # 4 unverified
    [make_task(status="done", quality_score=0.8)] * 3 +             # 3 verified
    [make_task(status="done", verification_status="in_progress")] * 2 +  # 2 in-progress
    [make_task(status="pending")] * 5                                # 5 not done
)
r = analyse(tasks_mixed)
check("total_tasks", r["summary"]["total_tasks"] == 14)
check("done_tasks", r["summary"]["done_tasks"] == 9)
check("unverified_done", r["summary"]["unverified_done"] == 4)
check("in_progress_verification", r["summary"]["in_progress_verification"] == 2)
check("verified_done", r["summary"]["verified_done"] == 3)


print("Severity thresholds:")

ok_tasks = [make_task(quality_score=None)] * (BACKLOG_WARN_THRESHOLD - 1)
check("ok severity", analyse(ok_tasks)["severity"] == "ok")
check("ok exit code", analyse(ok_tasks)["exit_code"] == 0)

warn_tasks = [make_task(quality_score=None)] * BACKLOG_WARN_THRESHOLD
check("elevated severity", analyse(warn_tasks)["severity"] == "elevated")
check("elevated exit code", analyse(warn_tasks)["exit_code"] == 1)

crit_tasks = [make_task(quality_score=None)] * BACKLOG_CRIT_THRESHOLD
check("critical severity", analyse(crit_tasks)["severity"] == "critical")
check("critical exit code", analyse(crit_tasks)["exit_code"] == 2)


print("In-progress tasks excluded from unverified:")

in_prog = [make_task(verification_status="in_progress")] * 3
check("in-progress not counted as unverified", analyse(in_prog)["summary"]["unverified_done"] == 0)

verified = [make_task(quality_score=0.9)] * 3
check("verified not counted as unverified", analyse(verified)["summary"]["unverified_done"] == 0)


print("Lag calculation:")

from datetime import datetime, timezone, timedelta
old_ts = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
lag_tasks = [make_task(quality_score=None, updated_at=old_ts)] * 3
r_lag = analyse(lag_tasks)
check("lag p50 populated", r_lag["lag_seconds"]["p50"] is not None)
check("lag p50 >= 100s", r_lag["lag_seconds"]["p50"] >= 100)

no_ts_tasks = [make_task(quality_score=None)] * 3
check("lag null when no updated_at", analyse(no_ts_tasks)["lag_seconds"]["p50"] is None)


print("Empty input:")

check("empty list returns ok", analyse([])["severity"] == "ok")
check("empty list exit code 0", analyse([])["exit_code"] == 0)


print("Format report:")

r_fmt = analyse([make_task(quality_score=None)] * 12)
report_str = format_report(r_fmt)
check("report contains severity", "CRITICAL" in report_str)
check("report contains recommendation", "Recommendation:" in report_str)
check("report contains count", "12" in report_str)


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
