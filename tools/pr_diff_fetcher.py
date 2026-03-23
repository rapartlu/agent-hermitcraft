"""
pr_diff_fetcher.py

Fetches PR diffs without truncation by falling back to per-file content
via the GitHub API when the unified diff exceeds a size threshold.

Problem: `gh pr diff` truncates large diffs silently. Reviewers then
flag missing files that are actually present, producing unnecessary
change-request cycles.

Strategy:
  1. Fetch the unified diff via `gh pr diff`.
  2. If it exceeds DIFF_TRUNCATION_THRESHOLD bytes, emit a warning and
     switch to per-file mode: list changed files via `gh api`, then
     fetch each file's content and produce a per-file summary.
  3. Always emit a machine-readable header so callers know whether the
     view is complete or per-file-fallback.

Usage:
    python tools/pr_diff_fetcher.py --repo owner/repo --pr 42
    python tools/pr_diff_fetcher.py --repo owner/repo --pr 42 --json
    python tools/pr_diff_fetcher.py --repo owner/repo --pr 42 --force-perfile

Exit codes:
    0  — success (complete diff or per-file fallback)
    1  — PR not found or API error
    2  — unexpected error
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Optional

# Threshold above which we switch to per-file mode (100 KB)
DIFF_TRUNCATION_THRESHOLD = 100_000

# Max bytes to include per file in per-file mode (avoid overwhelming output)
PER_FILE_CONTENT_LIMIT = 8_000


@dataclass
class FileSummary:
    filename: str
    status: str          # added | modified | removed | renamed
    additions: int
    deletions: int
    patch_preview: Optional[str]  # first PER_FILE_CONTENT_LIMIT bytes of patch
    truncated: bool


@dataclass
class DiffReport:
    repo: str
    pr_number: int
    mode: str            # "unified" | "per-file"
    truncation_warning: bool
    unified_diff_bytes: Optional[int]
    files: list          # list of FileSummary dicts (per-file mode) or []
    unified_diff: Optional[str]  # populated in unified mode only


def run(cmd: list) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def fetch_unified_diff(repo: str, pr: int) -> tuple[Optional[str], Optional[str]]:
    """Returns (diff_text, error_message)."""
    rc, stdout, stderr = run(["gh", "pr", "diff", str(pr), "--repo", repo])
    if rc != 0:
        return None, stderr.strip() or f"gh pr diff exited {rc}"
    return stdout, None


def fetch_changed_files(repo: str, pr: int) -> tuple[Optional[list], Optional[str]]:
    """Returns (files_list, error_message) using gh api."""
    rc, stdout, stderr = run([
        "gh", "api",
        f"repos/{repo}/pulls/{pr}/files",
        "--paginate",
        "--jq", "[.[] | {filename, status, additions, deletions, patch}]"
    ])
    if rc != 0:
        return None, stderr.strip() or f"gh api exited {rc}"
    try:
        files = json.loads(stdout)
        return files, None
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def build_per_file_report(repo: str, pr: int, unified_diff_bytes: int) -> DiffReport:
    files_raw, err = fetch_changed_files(repo, pr)
    if err:
        raise RuntimeError(f"Failed to fetch changed files: {err}")

    summaries = []
    for f in files_raw:
        patch = f.get("patch", "") or ""
        truncated = len(patch) > PER_FILE_CONTENT_LIMIT
        summaries.append(FileSummary(
            filename=f.get("filename", ""),
            status=f.get("status", ""),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
            patch_preview=patch[:PER_FILE_CONTENT_LIMIT] if patch else None,
            truncated=truncated,
        ))

    return DiffReport(
        repo=repo,
        pr_number=pr,
        mode="per-file",
        truncation_warning=True,
        unified_diff_bytes=unified_diff_bytes,
        files=[asdict(s) for s in summaries],
        unified_diff=None,
    )


def fetch_diff_report(repo: str, pr: int, force_perfile: bool = False) -> DiffReport:
    diff, err = fetch_unified_diff(repo, pr)
    if err:
        raise RuntimeError(f"Failed to fetch PR diff: {err}")

    diff_bytes = len(diff.encode("utf-8"))

    if force_perfile or diff_bytes >= DIFF_TRUNCATION_THRESHOLD:
        return build_per_file_report(repo, pr, diff_bytes)

    return DiffReport(
        repo=repo,
        pr_number=pr,
        mode="unified",
        truncation_warning=False,
        unified_diff_bytes=diff_bytes,
        files=[],
        unified_diff=diff,
    )


def format_text_report(report: DiffReport) -> str:
    lines = []
    if report.truncation_warning:
        lines.append(
            f"⚠️  WARNING: Unified diff ({report.unified_diff_bytes:,} bytes) exceeds "
            f"truncation threshold ({DIFF_TRUNCATION_THRESHOLD:,} bytes). "
            f"Switched to per-file mode — all {len(report.files)} changed files shown individually."
        )
        lines.append("")

    lines.append(f"PR #{report.pr_number} on {report.repo}  [{report.mode} mode]")
    lines.append("=" * 60)

    if report.mode == "unified":
        lines.append(report.unified_diff or "")
    else:
        for f in report.files:
            status_icon = {"added": "+", "removed": "-", "modified": "~", "renamed": "→"}.get(f["status"], "?")
            lines.append(
                f"\n[{status_icon}] {f['filename']}  "
                f"+{f['additions']}/-{f['deletions']}  ({f['status']})"
            )
            lines.append("-" * 40)
            if f["patch_preview"]:
                lines.append(f["patch_preview"])
                if f["truncated"]:
                    lines.append(f"  ... [truncated at {PER_FILE_CONTENT_LIMIT} bytes]")
            else:
                lines.append("  (no patch available — binary or empty file)")

    return "\n".join(lines)


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Fetch PR diffs without silent truncation."
        )
        parser.add_argument("--repo", required=True, help="owner/repo")
        parser.add_argument("--pr", type=int, required=True, help="PR number")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Output as JSON")
        parser.add_argument("--force-perfile", action="store_true",
                            help="Always use per-file mode regardless of diff size")
        args = parser.parse_args()

        report = fetch_diff_report(args.repo, args.pr, args.force_perfile)

        if args.as_json:
            print(json.dumps(asdict(report), indent=2))
        else:
            print(format_text_report(report))

        sys.exit(0)
    except SystemExit:
        raise
    except RuntimeError as exc:
        print(f"[pr_diff_fetcher] error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[pr_diff_fetcher] unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
