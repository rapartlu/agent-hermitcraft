"""
Tests for tools/tag_task_result.py (pure-logic tests, no filesystem side-effects).
Run with: python3 tests/test_tag_task_result.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.tag_task_result import detect_blocker, build_metadata, METADATA_FILENAME

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


# ── detect_blocker ────────────────────────────────────────────────────────────

print("detect_blocker — infrastructure signals:")

r = detect_blocker("Push failed: GITHUB_TOKEN not set in container.")
check("GITHUB_TOKEN detected",          r["detected"] is True)
check("signal populated",               r["signal"] is not None)

r = detect_blocker("gh CLI not authenticated. Please run gh auth login.")
check("gh not authenticated detected",  r["detected"] is True)

r = detect_blocker("fatal: could not read Username for 'https://github.com': terminal prompts disabled")
check("terminal prompts disabled → detected", r["detected"] is True)

r = detect_blocker("All files committed. Branch pushed. PR opened.")
check("clean result → not detected",    r["detected"] is False)
check("signal None for clean result",   r["signal"] is None)

r = detect_blocker("PERMISSION DENIED when writing to /etc/config")
check("case-insensitive detection",     r["detected"] is True)


print("detect_blocker — explicit flag detection:")

r_flag = detect_blocker(
    "Committed all 11 season files. Cannot push: GITHUB_TOKEN not set. "
    "gh CLI not authenticated — blocked by missing GH_TOKEN in container."
)
check("explicitly_flagged True when agent names blocker", r_flag["explicitly_flagged"] is True)

r_no_flag = detect_blocker(
    "Push failed: GITHUB_TOKEN not set."
    # No explicit agent acknowledgement phrase
)
check("explicitly_flagged may be False without agent phrase",
      isinstance(r_no_flag["explicitly_flagged"], bool))  # just type-check


# ── build_metadata ────────────────────────────────────────────────────────────

print("build_metadata — blocked case:")

meta_blocked = build_metadata(
    session_id="test-session-1",
    blocker={"detected": True, "signal": "github[_ ]token", "explicitly_flagged": True},
    cwd="/repo",
)
check("schema_version present",         meta_blocked["schema_version"] == 1)
check("infrastructure_blocked True",    meta_blocked["infrastructure_blocked"] is True)
check("blocker_signal populated",       meta_blocked["blocker_signal"] == "github[_ ]token")
check("infra_score_weight present",     "infra_score_weight" in meta_blocked)
check("infra_score_weight is 0.25",     meta_blocked["infra_score_weight"] == 0.25)
check("verifier_instruction present",   "verifier_instruction" in meta_blocked)
check("instruction mentions blocked",   "blocked" in meta_blocked["verifier_instruction"].lower())
check("instruction says no re-dispatch","re-dispatch" in meta_blocked["verifier_instruction"].lower()
      or "do not" in meta_blocked["verifier_instruction"].lower())
check("agent_explicitly_flagged present", "agent_explicitly_flagged_blocker" in meta_blocked)
check("session_id preserved",           meta_blocked["session_id"] == "test-session-1")
check("tagged_at present",              "tagged_at" in meta_blocked)
check("cwd present",                    meta_blocked["cwd"] == "/repo")


print("build_metadata — clean case:")

meta_clean = build_metadata(
    session_id="test-session-2",
    blocker={"detected": False, "signal": None, "explicitly_flagged": False},
    cwd="/repo",
)
check("infrastructure_blocked False",   meta_clean["infrastructure_blocked"] is False)
check("no blocker_signal key",          "blocker_signal" not in meta_clean)
check("no infra_score_weight key",      "infra_score_weight" not in meta_clean)
check("verifier_instruction present",   "verifier_instruction" in meta_clean)
check("instruction says score normally","normally" in meta_clean["verifier_instruction"].lower())


print("build_metadata — JSON serialisable:")

try:
    json.dumps(meta_blocked)
    check("blocked metadata is JSON serialisable", True)
except (TypeError, ValueError) as e:
    check("blocked metadata is JSON serialisable", False, str(e))

try:
    json.dumps(meta_clean)
    check("clean metadata is JSON serialisable", True)
except (TypeError, ValueError) as e:
    check("clean metadata is JSON serialisable", False, str(e))


print("Constants:")

check("METADATA_FILENAME is .task_result_meta.json",
      METADATA_FILENAME == ".task_result_meta.json")


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
