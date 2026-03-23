"""
tests/test_no_bare_gh_subprocess.py
====================================
Repo-integrity test: no tool in tools/ may call subprocess.run (or
subprocess.Popen) with ["gh", ...] directly.  All GitHub CLI calls must
go through tools/api_retry.run_with_retry so they benefit from automatic
rate-limit retry and exponential backoff.

Rule (also documented in CLAUDE.md):
    Any tool that shells out to `gh` must import and use run_with_retry
    from tools/api_retry rather than calling subprocess.run directly.

How this test works:
    1. Scan every *.py file under tools/ (excluding api_retry.py itself,
       which is the implementation).
    2. Look for lines that call subprocess.run / subprocess.Popen AND
       whose argument list begins with the string "gh".
    3. If any such line is found, fail with a clear message pointing to
       the offending file and line number.

Exemptions:
    - tools/api_retry.py  (the implementation — it legitimately calls
      subprocess.run as the innermost layer)

False-positive rate:
    Very low.  We look for the literal pattern
        subprocess.run(  or  subprocess.Popen(
    followed by ["gh" or ('gh'
    on the *same or immediately continued line*.  Comment lines and
    strings that merely mention "gh" will not trigger this.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
TOOLS_DIR = ROOT / "tools"

# Files that are allowed to call subprocess.run(["gh", ...]) directly.
EXEMPTIONS = {"api_retry.py"}

# Patterns that indicate a bare subprocess call to gh.
# We look for subprocess.run( or subprocess.Popen( with ["gh" or ('gh'
# anywhere on the same physical line (handles both list and tuple args).
_BARE_CALL_RE = re.compile(
    r'subprocess\.(run|Popen)\s*\(\s*["\[].*["\']gh["\']',
)


def find_bare_gh_calls() -> list[tuple[Path, int, str]]:
    """
    Scan tools/*.py for bare subprocess calls to gh.

    Returns a list of (file_path, line_number, line_content) tuples for
    each violation found.
    """
    violations: list[tuple[Path, int, str]] = []
    for py_file in sorted(TOOLS_DIR.glob("*.py")):
        if py_file.name in EXEMPTIONS:
            continue
        try:
            lines = py_file.read_text().splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Skip pure comment lines
            if stripped.startswith("#"):
                continue
            if _BARE_CALL_RE.search(line):
                violations.append((py_file, lineno, line.rstrip()))
    return violations


class TestNoBareGhSubprocess(unittest.TestCase):
    """Enforce that all gh CLI calls go through run_with_retry."""

    def test_no_bare_subprocess_run_with_gh(self):
        """No tool file may call subprocess.run/Popen with ['gh', ...] directly."""
        violations = find_bare_gh_calls()
        if violations:
            lines = [
                "Found bare subprocess.run/Popen(['gh', ...]) calls — "
                "use tools/api_retry.run_with_retry instead:\n"
            ]
            for path, lineno, content in violations:
                lines.append(f"  {path.relative_to(ROOT)}:{lineno}  {content}")
            lines.append(
                "\nSee CLAUDE.md §'GitHub API Calls — Rate-Limit Guardrail' "
                "for the required pattern."
            )
            self.fail("\n".join(lines))

    def test_api_retry_itself_is_exempted(self):
        """api_retry.py must be in EXEMPTIONS so the scanner skips it."""
        self.assertIn("api_retry.py", EXEMPTIONS)

    def test_tools_dir_exists(self):
        self.assertTrue(TOOLS_DIR.exists(), f"tools/ dir not found at {TOOLS_DIR}")

    def test_pr_diff_fetcher_clean(self):
        """pr_diff_fetcher.py specifically must not have a bare gh call."""
        target = TOOLS_DIR / "pr_diff_fetcher.py"
        if not target.exists():
            self.skipTest("pr_diff_fetcher.py not present")
        violations = [v for v in find_bare_gh_calls() if v[0] == target]
        self.assertEqual(
            violations, [],
            f"pr_diff_fetcher.py has bare gh calls: {violations}",
        )

    def test_scanner_detects_violation_correctly(self):
        """Unit-test the regex: it must flag known-bad patterns."""
        bad_patterns = [
            'subprocess.run(["gh", "api", "repos/x/y"])',
            "subprocess.run(['gh', 'pr', 'diff'])",
            'result = subprocess.run(["gh", "api", "..."], capture_output=True)',
            'subprocess.Popen(["gh", "pr", "list"])',
        ]
        for pattern in bad_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(
                    _BARE_CALL_RE.search(pattern),
                    f"Scanner failed to detect bad pattern: {pattern!r}",
                )

    def test_scanner_ignores_safe_patterns(self):
        """Unit-test the regex: it must NOT flag safe non-comment patterns."""
        # Note: pure comment lines (starting with #) are stripped by
        # find_bare_gh_calls() *before* the regex runs, so we don't test
        # the regex against comment lines here — see test_scanner_skips_comments.
        safe_patterns = [
            "from tools.api_retry import run_with_retry",
            "run_with_retry(['gh', 'api', 'x'])",        # correct usage
            'subprocess.run(["python3", "tools/foo.py"])',  # non-gh subprocess
            "stderr contains 'gh rate limit'",            # string mention
        ]
        for pattern in safe_patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    _BARE_CALL_RE.search(pattern),
                    f"Scanner incorrectly flagged safe pattern: {pattern!r}",
                )

    def test_scanner_skips_comments(self):
        """find_bare_gh_calls() must skip pure comment lines."""
        import tempfile, os
        # Write a temp file with only a comment containing the bad pattern
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=TOOLS_DIR, delete=False
        ) as f:
            f.write("# subprocess.run(['gh', 'api'])  -- this is just a comment\n")
            tmp_path = Path(f.name)
        try:
            violations = [v for v in find_bare_gh_calls() if v[0] == tmp_path]
            self.assertEqual(violations, [],
                             "Scanner should skip pure comment lines")
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
