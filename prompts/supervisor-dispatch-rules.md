# Supervisor Dispatch Rules

Rules the supervisor must follow before creating a new task, to prevent
duplicate dispatches for the same unresolved issue.

---

## The Problem

Each supervisor cycle sees unresolved state and may dispatch a new task
without checking whether an existing task already covers it.  This
produced 3–5 duplicate dispatches for the same work:

- PR #10 merge conflicts: tasks 01KMBW90, 01KMBT19, 01KMC2EH
- cheese-hater push failures: tasks 01KMC04C, 01KMC2QZ, 01KMC2A9, 01KMC2GD

---

## Rule 1 — Always Check for Duplicates Before Dispatching

Run `tools/duplicate_task_detector.py` against the current task list
before creating any new task:

```bash
python tools/duplicate_task_detector.py \
  --title "Fix PR #10 merge conflict" \
  --source-ref "pull/10" \
  --tasks tasks.json
# exits 0 (safe) or 1 (duplicate found)
```

**If the detector returns exit 1: do not dispatch.** Log the reason and
continue to the next unresolved item.

---

## Rule 2 — Duplicate Detection Logic

A proposed task is a duplicate if any existing task:

| Existing task status | Match condition | Blocked? |
|---|---|---|
| `dispatched` / `in_progress` | same source-ref OR ≥ 60% keyword overlap | Always blocked |
| `done` / `rejected` / `blocked` | same source-ref OR ≥ 60% keyword overlap | Blocked if completed within last **4 hours** |
| `done` / `rejected` / `blocked` | any match | **Not blocked** if older than 4 hours — retry allowed |

The 4-hour recency window prevents eternal suppression of genuinely
failed tasks while still blocking the same-cycle re-dispatch pattern.

---

## Rule 3 — Re-Dispatch Conditions

Only re-dispatch a task that was previously completed/rejected if **all**
of the following are true:

1. The previous task is **older than 4 hours** (recency window expired), OR
2. The previous task was `rejected` (not `blocked`) and the specific
   failure cause has been addressed (e.g. infra was fixed), OR
3. The proposed task is **meaningfully different** in scope from the
   previous one (e.g. a decomposed sub-task vs the original monolithic task)

If the previous task was `blocked` (infra failure), do **not** re-dispatch
until the infrastructure issue is resolved.  Check `tools/rejection_classifier.py`
to confirm the blocker has been removed.

---

## Rule 4 — In-Flight Task Grace Period

If a task is `dispatched` or `in_progress`, never dispatch a duplicate
regardless of how long it has been running.  Instead:

- If in-flight for < 30 minutes: wait — it may still complete.
- If in-flight for 30–120 minutes: add to the stalled-task watchlist.
- If in-flight for > 120 minutes: mark as `timed_out`, then apply the
  recency-window logic above (treat as a recent completion).

---

## Rule 5 — Source-Ref Matching

When building a new task, always populate `source_ref` with the PR
number, issue number, or branch name the task addresses.  This is the
most reliable deduplication key.

```json
{
  "title": "Fix merge conflict on PR #10",
  "source_ref": "pull/10",
  "status": "dispatched"
}
```

Tasks without `source_ref` fall back to keyword matching — less
reliable, so prefer always setting it.

---

## Supervisor Cycle Pseudocode

```
for each unresolved_item in supervisor_queue:
    proposed_title = generate_task_title(unresolved_item)
    proposed_ref   = unresolved_item.source_ref

    result = check_duplicate(proposed_title, all_tasks, proposed_ref)

    if result.is_duplicate:
        log(f"Skipping {proposed_title}: {result.reason}")
        continue   # ← do NOT dispatch

    dispatch(proposed_title, proposed_ref)
```

---

## Tool Reference

```bash
# Check before dispatch (exits 0=safe, 1=duplicate)
python tools/duplicate_task_detector.py \
  --title "Fix PR #10 merge conflict" \
  --source-ref "pull/10" \
  --tasks tasks.json

# JSON output for pipeline integration
python tools/duplicate_task_detector.py \
  --title "..." --tasks tasks.json --json

# Adjust recency window (default 4 hours)
python tools/duplicate_task_detector.py \
  --title "..." --tasks tasks.json --recency-hours 8
```

JSON fields: `is_duplicate`, `reason`, `matching_task_id`,
`matching_task_status`, `match_type`, `keyword_overlap`.
