"""
Tests for tools/task_scope_estimator.py
Run with: python3 tests/test_task_scope_estimator.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.task_scope_estimator import estimate, SCORE_SINGLE, SCORE_PLAN

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


def signal_names(est):
    return {s["name"] for s in est.matched_signals}


# ── Real-world cases that prompted this issue ─────────────────────────────────

print("Real-world timeout cases (should recommend plan):")

est = estimate("Research and document all 11 Hermitcraft seasons")
check("all-11-seasons → plan",     est.recommendation == "plan",  f"got {est.recommendation} (score {est.raw_score})")
check("all-11-seasons exit code",  est.exit_code == 2)
check("all-11-seasons flag",       est.dispatch_flag == "--plan")
check("all_items signal fires",    "all_items" in signal_names(est))

est2 = estimate("Research current Hermit roster and create profiles for all 27 hermits")
check("all-27-hermits → plan",     est2.recommendation == "plan",  f"got {est2.recommendation} (score {est2.raw_score})")
check("all-27-hermits flag",       est2.dispatch_flag == "--plan")


# ── Narrow tasks (should be single) ──────────────────────────────────────────

print("Narrow tasks (should be single):")

est = estimate("Fix typo in season-1.md")
check("fix-typo → single",         est.recommendation == "single", f"score {est.raw_score}")
check("fix-typo exit code",        est.exit_code == 0)
check("fix-typo no flag",          est.dispatch_flag == "")
check("fix_single negative fires", "fix_single" in signal_names(est))

est = estimate("Update the start date in season-6.md")
check("update-date → single",      est.recommendation == "single", f"score {est.raw_score}")

est = estimate("Add a note about TinfoilChef's departure to season-9.md")
check("add-note → single",         est.recommendation == "single", f"score {est.raw_score}")


# ── Individual signal detection ───────────────────────────────────────────────

print("Signal detection:")

est = estimate("Document every hermit profile in the knowledge base")
check("every_item fires",          "every_item" in signal_names(est))

est = estimate("Research and write 15 season summaries")
check("research_write_n fires",    "research_write_n" in signal_names(est))
check("n_items_large fires",       "n_items_large" in signal_names(est))

est = estimate("Create a comprehensive guide to all seasons")
check("comprehensive fires",       "comprehensive" in signal_names(est))
check("all_items fires",           "all_items" in signal_names(est))

est = estimate("Document seasons 1-5 in detail")
check("season_range fires",        "season_range" in signal_names(est))

est = estimate("Research the lore and then document it across multiple PRs")
check("multiple_prs fires",        "multiple_prs" in signal_names(est))


# ── Boundary scores ───────────────────────────────────────────────────────────

print("Boundary / score thresholds:")

# A task with score exactly at the warn boundary
est_warn = estimate("Create profiles for each hermit in the roster")
# "each" = +10, "create_multiple" = +10 = 20 (single) — may vary; just test the mapping
if est_warn.raw_score >= SCORE_PLAN:
    check("score≥plan → plan rec",   est_warn.recommendation == "plan")
elif est_warn.raw_score >= SCORE_SINGLE:
    check("score in warn band → warn", est_warn.recommendation == "warn")
else:
    check("score<single → single",    est_warn.recommendation == "single")

# Score is always ≥ 0 after clamping
est_narrow = estimate("Fix a typo")
check("score never negative",       est_narrow.raw_score >= 0)

# SCORE constants are sane
check("SCORE_SINGLE < SCORE_PLAN",  SCORE_SINGLE < SCORE_PLAN)
check("SCORE_SINGLE > 0",           SCORE_SINGLE > 0)


# ── Exit code mapping ─────────────────────────────────────────────────────────

print("Exit code mapping:")

check("single → exit 0", estimate("Fix one typo")["exit_code"] == 0
      if False else estimate("Fix one typo").exit_code == 0)

est_plan = estimate("Research and document all 11 seasons comprehensively")
check("plan → exit 2", est_plan.exit_code == 2)

# warn case: manufacture a known-score task
from tools.task_scope_estimator import estimate as _est, SCORE_SINGLE, SCORE_PLAN
est_w = _est("Add profiles for each of the 7 new hermits")
if SCORE_SINGLE <= est_w.raw_score < SCORE_PLAN:
    check("warn → exit 1", est_w.exit_code == 1)
else:
    # Not in warn band for this input — skip assertion, just check consistency
    check("exit code consistent with rec",
          (est_w.recommendation == "single" and est_w.exit_code == 0) or
          (est_w.recommendation == "warn"   and est_w.exit_code == 1) or
          (est_w.recommendation == "plan"   and est_w.exit_code == 2))


# ── Explanation is always populated ──────────────────────────────────────────

print("Explanation:")

for task in [
    "Fix typo",
    "Create profiles for each hermit",
    "Research and document all 11 seasons",
]:
    est = estimate(task)
    check(f"explanation populated: '{task[:30]}'", bool(est.explanation))


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
