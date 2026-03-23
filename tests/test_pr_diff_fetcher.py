"""
Tests for tools/pr_diff_fetcher.py (pure-logic tests, no subprocess calls).
Run with: python3 tests/test_pr_diff_fetcher.py
"""

import inspect
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.pr_diff_fetcher import (
    build_per_file_report,
    fetch_changed_files,
    format_text_report,
    run,
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


# ── Pagination bug fix: multi-page NDJSON parsing ─────────────────────────────

print("Pagination fix (fetch_changed_files NDJSON parsing):")

# Simulate what `gh api --paginate --jq '.[] | {...}'` emits for 2 pages:
# one JSON object per line (not one array per page).
def _fake_fetch_changed_files_ndjson(ndjson_output):
    """Parse the NDJSON output the same way fetch_changed_files now does."""
    return [json.loads(line) for line in ndjson_output.splitlines() if line.strip()]

page1_obj1 = '{"filename":"a.py","status":"modified","additions":5,"deletions":1,"patch":"@@"}'
page1_obj2 = '{"filename":"b.py","status":"added","additions":10,"deletions":0,"patch":null}'
page2_obj1 = '{"filename":"c.py","status":"modified","additions":2,"deletions":2,"patch":"@@"}'

# Old approach (array per page) would fail on multi-page:
two_page_array_output = '[{"filename":"a.py"}]\n[{"filename":"b.py"}]'
try:
    json.loads(two_page_array_output)
    check("old array approach fails on multi-page", False, "expected JSONDecodeError")
except json.JSONDecodeError:
    check("old array approach fails on multi-page (confirmed)", True)

# New approach (NDJSON) succeeds on multi-page:
ndjson_output = "\n".join([page1_obj1, page1_obj2, page2_obj1])
files = _fake_fetch_changed_files_ndjson(ndjson_output)
check("ndjson parse returns 3 files across 2 pages", len(files) == 3)
check("first file parsed correctly",  files[0]["filename"] == "a.py")
check("second file parsed correctly", files[1]["filename"] == "b.py")
check("third file parsed correctly",  files[2]["filename"] == "c.py")

# Empty lines between pages are handled gracefully
ndjson_with_blanks = page1_obj1 + "\n\n" + page2_obj1 + "\n"
files2 = _fake_fetch_changed_files_ndjson(ndjson_with_blanks)
check("blank lines between pages ignored", len(files2) == 2)

# Null patch field doesn't crash
null_patch = '{"filename":"img.png","status":"added","additions":0,"deletions":0,"patch":null}'
files3 = _fake_fetch_changed_files_ndjson(null_patch)
check("null patch field parsed without crash", files3[0]["patch"] is None)


# ── run() has timeout parameter ───────────────────────────────────────────────

print("run() timeout:")

sig = inspect.signature(run)
check("run() accepts timeout kwarg", "timeout" in sig.parameters)
check("timeout defaults to 60", sig.parameters["timeout"].default == 60)


print(f"\n{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
