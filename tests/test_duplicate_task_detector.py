"""
Tests for tools/duplicate_task_detector.py
Run with: python3 tests/test_duplicate_task_detector.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, timedelta
from tools.duplicate_task_detector import (
    check_duplicate,
    extract_keywords,
    extract_refs,
    is_recent,
    RECENCY_WINDOW_HOURS,
    KEYWORD_OVERLAP_THRESHOLD,
)

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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ago_iso(hours=0, minutes=0):
    delta = timedelta(hours=hours, minutes=minutes)
    return (datetime.now(timezone.utc) - delta).isoformat()


# ── Real-world duplicate cases from the issue ─────────────────────────────────

print("Real-world cases (PR #10 and cheese-hater push):")

pr10_task = {
    "id": "01KMBW90", "title": "Fix PR #10 merge conflict",
    "status": "dispatched", "source_ref": "pull/10"
}
result = check_duplicate("Fix merge conflict on PR #10", [pr10_task], "pull/10")
check("PR #10 duplicate blocked (in-flight, source-ref)", result.is_duplicate)
check("match type is source_ref", result.match_type == "source_ref")
check("matching task id correct", result.matching_task_id == "01KMBW90")

push_task = {
    "id": "01KMC04C", "title": "Fix cheese-hater push failure",
    "status": "dispatched"
}
result2 = check_duplicate("Retry cheese-hater push failure", [push_task])
check("cheese-hater duplicate blocked (keyword)", result2.is_duplicate)
check("match type is keywords", result2.match_type == "keywords")


# ── In-flight statuses always block ──────────────────────────────────────────

print("In-flight statuses (dispatched / in_progress):")

for status in ["dispatched", "in_progress", "in-progress", "running"]:
    task = {"id": "t1", "title": "Fix PR #10 merge conflict",
            "status": status, "source_ref": "pull/10"}
    r = check_duplicate("Fix PR #10 merge conflict", [task], "pull/10")
    check(f"status='{status}' blocks dispatch", r.is_duplicate,
          f"got is_duplicate={r.is_duplicate}")


# ── Recent completions block within window ────────────────────────────────────

print("Recency window (done/failed/rejected/blocked):")

for status in ["done", "failed", "completed", "rejected", "blocked", "verified"]:
    task = {"id": "t1", "title": "Fix PR #10 merge conflict",
            "status": status, "source_ref": "pull/10",
            "updated_at": ago_iso(hours=1)}  # 1h ago — within 4h window
    r = check_duplicate("Fix PR #10 merge conflict", [task], "pull/10")
    check(f"status='{status}' recent → blocks dispatch", r.is_duplicate,
          f"got is_duplicate={r.is_duplicate}")

# Stale completed/failed tasks (beyond window) should NOT block
for stale_status in ["done", "failed"]:
    stale_task = {
        "id": "t1", "title": "Fix PR #10 merge conflict",
        "status": stale_status, "source_ref": "pull/10",
        "updated_at": ago_iso(hours=RECENCY_WINDOW_HOURS + 1)
    }
    r = check_duplicate("Fix PR #10 merge conflict", [stale_task], "pull/10")
    check(f"stale {stale_status} task (beyond window) does NOT block", not r.is_duplicate,
          f"got is_duplicate={r.is_duplicate}")


# ── Source-ref extraction ─────────────────────────────────────────────────────

print("extract_refs:")

check("extracts #10",                  "#10"      in extract_refs("Fix issue #10"))
check("extracts pull/10",              "pull/10"  in extract_refs("see pull/10"))
check("extracts issues/5 → issue/5",   "issue/5"  in extract_refs("issues/5 blocked"))
check("extracts issue/5 → issue/5",    "issue/5"  in extract_refs("issue/5 blocked"))
check("issues/N and issue/N match",    extract_refs("issues/5") & extract_refs("issue/5") != set())
check("extracts pr-10 → #10",          "#10"      in extract_refs("pr-10 fix"))
check("no refs → empty set",           extract_refs("nothing to see here") == set())
check("multiple refs",       len(extract_refs("PR #10 and #12")) == 2)


# ── Keyword extraction ────────────────────────────────────────────────────────

print("extract_keywords:")

kw = extract_keywords("Fix the merge conflict on branch feature-x")
check("extracts 'merge'",    "merge"   in kw)
check("extracts 'conflict'", "conflict" in kw)
check("extracts 'branch'",   "branch"  in kw)
check("extracts 'feature'",  "feature" in kw)
check("stopwords removed",   "the"     not in kw)
check("stopwords removed",   "fix"     not in kw)
check("stopwords removed",   "on"      not in kw)


# ── Keyword overlap matching ──────────────────────────────────────────────────

print("Keyword overlap:")

# Use titles without PR refs so the test exercises the keyword path,
# not the source-ref path (which would set keyword_overlap=None).
task_kw = {"id": "t1", "title": "Resolve cheese-hater push failure",
           "status": "dispatched"}
r = check_duplicate("Fix cheese-hater push failure", [task_kw])
check("high keyword overlap → blocked", r.is_duplicate,
      f"overlap={r.keyword_overlap}")
check("keyword_overlap populated", r.keyword_overlap is not None)

task_unrelated = {"id": "t2", "title": "Update season-7 hermit profiles",
                  "status": "dispatched"}
r2 = check_duplicate("Fix merge conflict on PR #10", [task_unrelated])
check("low keyword overlap → safe", not r2.is_duplicate)


# ── No-duplicate cases ────────────────────────────────────────────────────────

print("No-duplicate (safe to dispatch):")

# Different PR number
different_pr = {"id": "t1", "title": "Fix PR #5 merge conflict",
                "status": "dispatched", "source_ref": "pull/5"}
r = check_duplicate("Fix PR #10 merge conflict", [different_pr], "pull/10")
check("different PR ref → safe", not r.is_duplicate)

# Empty task list
r = check_duplicate("Do something new", [])
check("empty task list → safe", not r.is_duplicate)

# Task list with only old completed tasks
old_task = {"id": "t1", "title": "Fix PR #10 merge conflict",
            "status": "done", "source_ref": "pull/10",
            "updated_at": ago_iso(hours=RECENCY_WINDOW_HOURS + 2)}
r = check_duplicate("Fix PR #10 merge conflict", [old_task], "pull/10")
check("old done task → safe to re-dispatch", not r.is_duplicate)


# ── is_recent ────────────────────────────────────────────────────────────────

print("is_recent:")

check("1h ago → recent",          is_recent({"updated_at": ago_iso(hours=1)}, 4))
check("5h ago → not recent",      not is_recent({"updated_at": ago_iso(hours=5)}, 4))
check("no timestamp → treated as recent", is_recent({}, 4))
check("completed_at field used",  is_recent({"completed_at": ago_iso(minutes=30)}, 4))


# ── Exit codes via result ─────────────────────────────────────────────────────

print("Result fields:")

dup = check_duplicate("Fix PR #10", [{"id":"x","title":"Fix PR #10","status":"dispatched","source_ref":"pull/10"}], "pull/10")
check("duplicate: is_duplicate True", dup.is_duplicate)
check("duplicate: reason populated",  bool(dup.reason))
check("duplicate: matching_task_id",  dup.matching_task_id == "x")

safe = check_duplicate("New task no overlap", [])
check("safe: is_duplicate False",     not safe.is_duplicate)
check("safe: reason None",            safe.reason is None)
check("safe: match_type None",        safe.match_type is None)


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
