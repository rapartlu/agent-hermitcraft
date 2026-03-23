"""
Tests for tools/verifier_score_adjuster.py
Run with: python3 tests/test_verifier_score_adjuster.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.verifier_score_adjuster import (
    adjust,
    detect_blocker,
    ACCEPT_THRESHOLD,
    INFRA_WEIGHT,
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


# ── Real-world cases from the issue ──────────────────────────────────────────

print("Real-world cases (tasks 01KMC04C / 01KMC05Z):")

# Task 01KMC05Z: score 0.35, push failed due to missing GH_TOKEN
r = adjust(0.35, "All files committed. Push failed: GITHUB_TOKEN not set in container.")
check("01KMC05Z → blocked",           r.status == "blocked")
check("01KMC05Z exit code 2",         r.exit_code == 2)
check("01KMC05Z blocker detected",    r.blocker_detected is True)
check("01KMC05Z adjusted > raw",      r.adjusted_score > r.raw_score,
      f"adjusted={r.adjusted_score}, raw={r.raw_score}")
check("01KMC05Z adjusted <= 1.0",     r.adjusted_score <= 1.0)

# Task 01KMC04C: score 0.45, same root cause
r2 = adjust(0.45, "Committed all season files. gh push failed: not authenticated.")
check("01KMC04C → blocked",           r2.status == "blocked")
check("01KMC04C adjusted > raw",      r2.adjusted_score > r2.raw_score)


# ── detect_blocker ────────────────────────────────────────────────────────────

print("detect_blocker:")

check("detects GITHUB_TOKEN",         detect_blocker("GITHUB_TOKEN not set") is not None)
check("detects gh not authenticated", detect_blocker("gh CLI not authenticated") is not None)
check("detects permission denied",    detect_blocker("Permission denied (publickey)") is not None)
check("detects command not found",    detect_blocker("bash: gh: command not found") is not None)
check("detects rate limit",           detect_blocker("API rate limit exceeded") is not None)
check("detects connection refused",   detect_blocker("Connection refused") is not None)
check("returns None for clean result",detect_blocker("All files written and pushed.") is None)
check("case-insensitive",             detect_blocker("PERMISSION DENIED") is not None)


# ── Adjusted score calculation ────────────────────────────────────────────────

print("Score adjustment calculation:")

# adjusted = min(raw / (1 - INFRA_WEIGHT), 1.0)
import math
blocker_text = "Push failed: GITHUB_TOKEN not set."

r = adjust(0.35, blocker_text)
expected = min(0.35 / (1 - INFRA_WEIGHT), 1.0)
check("0.35 adjusted correctly",
      math.isclose(r.adjusted_score, round(expected, 4), rel_tol=1e-4))

r = adjust(0.45, blocker_text)
expected = min(0.45 / (1 - INFRA_WEIGHT), 1.0)
check("0.45 adjusted correctly",
      math.isclose(r.adjusted_score, round(expected, 4), rel_tol=1e-4))

# Score that would overflow 1.0 without cap
r = adjust(0.90, blocker_text)
check("adjusted score capped at 1.0", r.adjusted_score <= 1.0)
check("raw_score preserved",          r.raw_score == 0.90)


# ── No-blocker path ───────────────────────────────────────────────────────────

print("No-blocker path:")

r_ok = adjust(0.80, "All 11 season files written, pushed, PR opened.")
check("0.80 clean → verified",        r_ok.status == "verified")
check("0.80 exit code 0",             r_ok.exit_code == 0)
check("0.80 no adjustment",           r_ok.adjusted_score == r_ok.raw_score)
check("0.80 blocker_detected False",  r_ok.blocker_detected is False)
check("0.80 matched_pattern None",    r_ok.matched_pattern is None)

r_rej = adjust(0.60, "Season 10 member list is incorrect.")
check("0.60 clean → rejected",        r_rej.status == "rejected")
check("0.60 exit code 1",             r_rej.exit_code == 1)
check("0.60 no adjustment",           r_rej.adjusted_score == r_rej.raw_score)

# Exact threshold
r_thresh = adjust(ACCEPT_THRESHOLD, "Work complete.")
check(f"score={ACCEPT_THRESHOLD} → verified", r_thresh.status == "verified")

r_below = adjust(ACCEPT_THRESHOLD - 0.01, "Work complete.")
check(f"score={ACCEPT_THRESHOLD - 0.01:.2f} → rejected", r_below.status == "rejected")


# ── blocked status always wins regardless of raw score ───────────────────────

print("blocked status overrides score level:")

for score in [0.10, 0.50, 0.80, 0.99]:
    r = adjust(score, "Push failed: GITHUB_TOKEN not set.")
    check(f"score={score} + blocker → blocked", r.status == "blocked",
          f"got {r.status}")


# ── Adjustment note is always populated ──────────────────────────────────────

print("adjustment_note always populated:")

for text, score in [
    ("Push failed: GH_TOKEN missing.", 0.35),
    ("Wrong facts in season file.", 0.50),
    ("All work complete.", 0.85),
]:
    r = adjust(score, text)
    check(f"note populated (score={score})", bool(r.adjustment_note))


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
