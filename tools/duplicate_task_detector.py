"""
duplicate_task_detector.py

Checks whether a proposed new task duplicates an existing in-flight or
recently-completed task, so the supervisor can avoid re-dispatching work
that is already covered.

Problem: The supervisor sees unresolved state and dispatches again each
cycle without recognising that a task for the same issue is already
dispatched, in-progress, or recently completed.  This produced 3–5
consecutive duplicate dispatches for PR #10 merge conflicts and
cheese-hater push failures.

Detection strategy:
  1. Source-ref match  — new task references the same PR/issue/branch as
     an existing task.
  2. Title keyword overlap — new task title shares enough significant
     keywords with an existing task title.
  3. Age gate  — a completed/rejected task is only considered a duplicate
     if it finished within RECENCY_WINDOW_HOURS hours.  Older tasks are
     treated as stale and re-dispatch is allowed.

A task is blocked (is a duplicate) if an existing task:
  - has status in {dispatched, in_progress} matching by source-ref OR keywords, OR
  - has status in {done, rejected, blocked} within RECENCY_WINDOW_HOURS
    matching by source-ref OR keywords.

Usage:
    python tools/duplicate_task_detector.py \\
        --title "Fix PR #10 merge conflict" \\
        --source-ref "pull/10" \\
        --tasks tasks.json

    python tools/duplicate_task_detector.py \\
        --title "Fix PR #10 merge conflict" \\
        --tasks tasks.json --json

Exit codes:
    0  — no duplicate found, safe to dispatch
    1  — duplicate found, do NOT dispatch
    2  — unexpected error
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

# Hours within which a completed task is still considered recent enough
# to block a duplicate dispatch.
RECENCY_WINDOW_HOURS = 4

# Minimum fraction of significant title words that must overlap to
# trigger a keyword-based duplicate match.
KEYWORD_OVERLAP_THRESHOLD = 0.6

# Words too common to use as matching signals.
STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "in", "of", "on", "at",
    "fix", "add", "update", "create", "write", "task", "issue", "pr",
    "with", "from", "by", "is", "was", "be", "this", "that", "it",
}

# Task statuses that block dispatch unconditionally (in-flight work).
# Schema statuses: dispatched, in_progress.
# "in-progress" and "running" are defensive aliases not in the schema.
INFLIGHT_STATUSES = {"dispatched", "in_progress", "in-progress", "running"}

# Task statuses that block dispatch only within the recency window.
# Schema statuses: done, failed.
# "completed", "rejected", "blocked", "verified" are defensive aliases
# used by adjacent tools (verifier_score_adjuster, rejection_classifier).
RECENT_STATUSES = {"done", "failed", "completed", "rejected", "blocked", "verified"}


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    reason: Optional[str]          # human-readable explanation
    matching_task_id: Optional[str]
    matching_task_status: Optional[str]
    match_type: Optional[str]      # "source_ref" | "keywords" | None
    keyword_overlap: Optional[float]
    proposed_title: str
    proposed_source_ref: Optional[str]


def extract_keywords(title: str) -> set:
    """Return significant lowercase words from a title."""
    words = re.findall(r"[a-z0-9#]+", title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def extract_refs(text: str) -> set:
    """Extract PR/issue/branch references from text (e.g. 'pull/10', '#10', 'pr-10').

    All issue variants ('issues/10', 'issue/10') are normalised to 'issue/N'
    so they match each other regardless of pluralisation.
    """
    refs = set()
    # GitHub-style: #10, PR #10, issue #10
    for m in re.finditer(r"#(\d+)", text.lower()):
        refs.add(f"#{m.group(1)}")
    # URL-style: pull/10, issues/10, issue/10
    # Normalise 'issues/N' → 'issue/N' for consistent matching.
    for m in re.finditer(r"(pull|issue[s]?)/(\d+)", text.lower()):
        prefix = "issue" if m.group(1).startswith("issue") else m.group(1)
        refs.add(f"{prefix}/{m.group(2)}")
    # Branch-style: pr-10, issue-10
    for m in re.finditer(r"(pr|issue)-(\d+)", text.lower()):
        refs.add(f"#{m.group(2)}")
    return refs


def is_recent(task: dict, window_hours: int) -> bool:
    """Return True if the task completed within the recency window."""
    for field in ("completed_at", "updated_at", "finished_at"):
        ts = task.get(field)
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
                return dt >= cutoff
            except ValueError:
                continue
    # If no timestamp is available, treat as recent to be safe.
    return True


def check_duplicate(
    proposed_title: str,
    existing_tasks: list,
    proposed_source_ref: Optional[str] = None,
    recency_window_hours: int = RECENCY_WINDOW_HOURS,
    keyword_overlap_threshold: float = KEYWORD_OVERLAP_THRESHOLD,
) -> DuplicateCheckResult:
    """
    Check whether the proposed task duplicates any existing task.
    Returns a DuplicateCheckResult describing the outcome.
    """
    proposed_keywords = extract_keywords(proposed_title)
    proposed_refs = extract_refs(proposed_title)
    if proposed_source_ref:
        proposed_refs |= extract_refs(proposed_source_ref)

    for task in existing_tasks:
        status = (task.get("status") or "").lower().replace("-", "_")
        task_id = task.get("id", "?")
        task_title = task.get("title") or task.get("description") or ""
        task_refs = extract_refs(task_title)
        if task.get("source_ref"):
            task_refs |= extract_refs(str(task["source_ref"]))

        # Determine if this task is in a blocking state
        is_inflight = status in INFLIGHT_STATUSES
        is_recent_completion = status in RECENT_STATUSES and is_recent(
            task, recency_window_hours
        )
        if not (is_inflight or is_recent_completion):
            continue

        # 1. Source-ref match
        if proposed_refs and task_refs and proposed_refs & task_refs:
            return DuplicateCheckResult(
                is_duplicate=True,
                reason=(
                    f"Existing task {task_id} ({status}) covers the same "
                    f"source ref(s): {proposed_refs & task_refs}"
                ),
                matching_task_id=task_id,
                matching_task_status=status,
                match_type="source_ref",
                keyword_overlap=None,
                proposed_title=proposed_title,
                proposed_source_ref=proposed_source_ref,
            )

        # If both sides have refs but none overlap, the tasks address
        # different PRs/issues — skip keyword matching to avoid false
        # positives on shared generic terms (e.g. "merge conflict").
        if proposed_refs and task_refs and not (proposed_refs & task_refs):
            continue

        # 2. Keyword overlap match
        task_keywords = extract_keywords(task_title)
        if proposed_keywords and task_keywords:
            overlap = proposed_keywords & task_keywords
            # Overlap fraction relative to the smaller keyword set
            smaller = min(len(proposed_keywords), len(task_keywords))
            fraction = len(overlap) / smaller if smaller else 0.0
            if fraction >= keyword_overlap_threshold:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    reason=(
                        f"Existing task {task_id} ({status}) overlaps "
                        f"{fraction:.0%} on keywords: {overlap}"
                    ),
                    matching_task_id=task_id,
                    matching_task_status=status,
                    match_type="keywords",
                    keyword_overlap=round(fraction, 4),
                    proposed_title=proposed_title,
                    proposed_source_ref=proposed_source_ref,
                )

    return DuplicateCheckResult(
        is_duplicate=False,
        reason=None,
        matching_task_id=None,
        matching_task_status=None,
        match_type=None,
        keyword_overlap=None,
        proposed_title=proposed_title,
        proposed_source_ref=proposed_source_ref,
    )


def format_report(result: DuplicateCheckResult) -> str:
    if result.is_duplicate:
        lines = [
            f"⛔  DUPLICATE — do not dispatch",
            f"   Proposed:  \"{result.proposed_title}\"",
            f"   Reason:    {result.reason}",
            f"   Match type: {result.match_type}",
        ]
        if result.keyword_overlap is not None:
            lines.append(f"   Keyword overlap: {result.keyword_overlap:.0%}")
    else:
        lines = [
            f"✓   SAFE TO DISPATCH — no duplicate found",
            f"   Proposed:  \"{result.proposed_title}\"",
        ]
    return "\n".join(lines)


def main():
    try:
        parser = argparse.ArgumentParser(
            description="Check if a proposed task duplicates an existing one."
        )
        parser.add_argument("--title", required=True,
                            help="Title/description of the proposed task")
        parser.add_argument("--source-ref", default=None,
                            help="Optional PR/issue/branch reference (e.g. 'pull/10')")
        parser.add_argument("--tasks", required=True,
                            help="Path to JSON file containing existing task list")
        parser.add_argument("--recency-hours", type=int, default=RECENCY_WINDOW_HOURS,
                            help=f"Hours to treat completed tasks as recent (default {RECENCY_WINDOW_HOURS})")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Output as JSON")
        args = parser.parse_args()

        with open(args.tasks) as f:
            tasks = json.load(f)
        if not isinstance(tasks, list):
            raise ValueError("Tasks file must contain a JSON array")

        result = check_duplicate(
            proposed_title=args.title,
            existing_tasks=tasks,
            proposed_source_ref=args.source_ref,
            recency_window_hours=args.recency_hours,
        )

        if args.as_json:
            print(json.dumps(asdict(result), indent=2))
        else:
            print(format_report(result))

        sys.exit(1 if result.is_duplicate else 0)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[duplicate_task_detector] unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
