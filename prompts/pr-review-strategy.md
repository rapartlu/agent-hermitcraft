# PR Review Strategy

Guidelines for reviewing PRs without being misled by diff truncation.

---

## The Problem

`gh pr diff` silently truncates large diffs. When a reviewer operates on
a truncated diff, they may flag files as "missing" or "incomplete" when
those files are actually present on the branch — causing unnecessary
change-request cycles.

**Signals that a diff is truncated:**
- The diff ends mid-hunk (no trailing newline, no `diff --git` for expected files)
- The diff is exactly a round number of bytes (e.g. 65,536 — a common buffer size)
- The PR description lists more files than appear in the diff
- `gh pr diff` output is smaller than `gh api repos/{repo}/pulls/{pr}/files` implies

---

## Reviewing a PR

### Step 1 — Always list changed files first

Before reading the diff, fetch the authoritative file list:

```bash
gh api repos/{owner}/{repo}/pulls/{pr}/files \
  --jq '[.[] | {filename, status, additions, deletions}]'
```

This is never truncated. Use it as the ground truth for what changed.

### Step 2 — Check diff completeness

Fetch the diff and compare the file count:

```bash
gh pr diff {pr} --repo {owner}/{repo} | grep '^diff --git' | wc -l
```

If this count is lower than the file count from Step 1, the diff is
truncated. Do **not** review the truncated diff as if it were complete.

### Step 3 — For large diffs, use per-file mode

Use `tools/pr_diff_fetcher.py` which automatically detects truncation
(threshold: 100 KB) and falls back to per-file content via `gh api`:

```bash
python tools/pr_diff_fetcher.py --repo owner/repo --pr 42
# or force per-file mode for any PR:
python tools/pr_diff_fetcher.py --repo owner/repo --pr 42 --force-perfile
```

The tool emits an explicit warning when switching to per-file mode so
the reviewer knows the view is complete.

### Step 4 — Reviewing per-file output

When in per-file mode:
- The tool shows `+additions/-deletions` per file — use this to verify
  that expected changes are present, even if the patch is long
- A file with `additions > 0` is present and has content; do not flag
  it as missing based on absence from the unified diff
- Files marked `(no patch available — binary or empty file)` are
  intentional — verify via `gh api repos/{owner}/{repo}/contents/{path}?ref={branch}`

---

## Review Decision Rules

| Situation | Action |
|---|---|
| Diff complete (all files present) | Review normally |
| Diff truncated, switched to per-file | Review per-file summaries; do not request changes for files you cannot see the full patch of unless additions/deletions are 0 |
| File shows `additions=0, deletions=0` | Investigate — may be a rename or metadata change |
| File unexpectedly missing from API list | Flag as genuinely missing; request changes |

---

## Emitting Truncation Warnings

Whenever a review is conducted on a potentially truncated diff, prefix
the review comment with:

```
⚠️ Note: The unified diff for this PR exceeds the truncation threshold.
This review was conducted in per-file mode via gh api. All N changed
files were reviewed individually.
```

This makes it clear to the PR author that the review was complete and
prevents false "reviewer only saw part of the diff" assumptions.

---

## Tool Reference

```bash
# Auto-detect truncation and use best mode
python tools/pr_diff_fetcher.py --repo owner/repo --pr 42

# Always use per-file mode (safest for PRs with >20 files)
python tools/pr_diff_fetcher.py --repo owner/repo --pr 42 --force-perfile

# JSON output for programmatic use
python tools/pr_diff_fetcher.py --repo owner/repo --pr 42 --json
```

JSON fields: `mode`, `truncation_warning`, `unified_diff_bytes`, `files[]`
(each with `filename`, `status`, `additions`, `deletions`, `patch_preview`,
`truncated`).
