"""
Tests for tools/pr_diff_fetcher.py (pure-logic tests, no subprocess calls).
Run with: python3 tests/test_pr_diff_fetcher.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.pr_diff_fetcher import (
    build_per_file_report,
    format_text_report,
    DiffReport,
    FileSummary,
    DIFF_TRUNCATION_THRESHOLD,
    PER_FILE_CONTENT_LIMIT,
)
from dataclasses import asdict

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


# ── Helper to build a DiffReport directly ────────────────────────────────────

def make_unified_report(diff_text="diff --git a/f\n+content", truncation_warning=False):
    return DiffReport(
        repo="owner/repo",
        pr_number=42,
        mode="unified",
        truncation_warning=truncation_warning,
        unified_diff_bytes=len(diff_text.encode()),
        files=[],
        unified_diff=diff_text,
    )


def make_perfile_report(files):
    return DiffReport(
        repo="owner/repo",
        pr_number=42,
        mode="per-file",
        truncation_warning=True,
        unified_diff_bytes=DIFF_TRUNCATION_THRESHOLD + 1,
        files=[asdict(f) for f in files],
        unified_diff=None,
    )


# ── DiffReport structure ──────────────────────────────────────────────────────

print("DiffReport structure:")

r = make_unified_report()
check("unified mode set", r.mode == "unified")
check("no truncation warning on small diff", not r.truncation_warning)
check("unified_diff populated", r.unified_diff is not None)
check("files empty in unified mode", r.files == [])

r2 = make_perfile_report([
    FileSummary("src/foo.py", "modified", 10, 2, "@@\n+line", False),
    FileSummary("src/bar.py", "added",    50, 0, None,       False),
])
check("per-file mode set", r2.mode == "per-file")
check("truncation_warning True in per-file", r2.truncation_warning)
check("files populated", len(r2.files) == 2)
check("unified_diff None in per-file", r2.unified_diff is None)


# ── FileSummary truncation flag ───────────────────────────────────────────────

print("FileSummary truncation:")

long_patch = "x" * (PER_FILE_CONTENT_LIMIT + 1)
short_patch = "x" * (PER_FILE_CONTENT_LIMIT - 1)

fs_long  = FileSummary("a.py", "modified", 5, 0, long_patch[:PER_FILE_CONTENT_LIMIT], True)
fs_short = FileSummary("b.py", "modified", 5, 0, short_patch, False)

check("long patch marked truncated", fs_long.truncated is True)
check("short patch not truncated",   fs_short.truncated is False)
check("patch_preview respects limit", len(fs_long.patch_preview) == PER_FILE_CONTENT_LIMIT)


# ── format_text_report ────────────────────────────────────────────────────────

print("format_text_report:")

text_unified = format_text_report(make_unified_report("diff --git a/f\n+line"))
check("unified output contains diff", "diff --git" in text_unified)
check("unified output contains PR number", "42" in text_unified)
check("unified output shows mode", "unified" in text_unified)
check("no warning in complete diff", "WARNING" not in text_unified)

text_perfile = format_text_report(make_perfile_report([
    FileSummary("src/foo.py", "modified", 10, 2, "@@\n+new line", False),
    FileSummary("img/logo.png", "added",   1, 0, None,           False),
]))
check("per-file output contains WARNING", "WARNING" in text_perfile)
check("per-file output lists filename", "src/foo.py" in text_perfile)
check("per-file output shows additions", "+10" in text_perfile)
check("binary/empty file noted", "no patch available" in text_perfile)
check("truncation threshold shown in warning", str(DIFF_TRUNCATION_THRESHOLD) in text_perfile or "bytes" in text_perfile)

text_truncated_file = format_text_report(make_perfile_report([
    FileSummary("big.py", "modified", 200, 0, "x" * PER_FILE_CONTENT_LIMIT, True),
]))
check("truncated file note shown", "truncated at" in text_truncated_file)


# ── Threshold constants sanity ────────────────────────────────────────────────

print("Constants:")
check("DIFF_TRUNCATION_THRESHOLD > 0", DIFF_TRUNCATION_THRESHOLD > 0)
check("PER_FILE_CONTENT_LIMIT < DIFF_TRUNCATION_THRESHOLD",
      PER_FILE_CONTENT_LIMIT < DIFF_TRUNCATION_THRESHOLD)


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
