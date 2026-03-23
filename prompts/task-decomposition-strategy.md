# Task Decomposition Strategy

How the dispatcher should handle large-scope tasks to prevent timeouts.

---

## Problem

Large tasks dispatched as single-agent jobs silently time out. The
supervisor then re-dispatches the same task, causing repeated failures.
Example: "Research and document all 11 Hermitcraft seasons" timed out
3+ times before being split manually.

---

## Decision Rule: Estimate Scope Before Dispatching

Every task description must pass through the scope estimator before
dispatch. Use `tools/task_scope_estimator.py`:

```bash
python tools/task_scope_estimator.py --task "research and document all 11 seasons"
# → ⛔ Scope: PLAN (score 65) — decompose with --plan

python tools/task_scope_estimator.py --task "fix typo in season-1.md"
# → ✓ Scope: SINGLE (score 0) — safe to dispatch directly
```

| Score | Recommendation | Action |
|---|---|---|
| < 30  | `single` (exit 0) | Dispatch directly |
| 30–59 | `warn`   (exit 1) | Dispatch directly; log warning; re-evaluate if it times out once |
| ≥ 60  | `plan`   (exit 2) | **Decompose first** — do not dispatch monolithically |

---

## Decomposition Pattern

When scope is `plan`, break the task into sub-tasks of 2–3 items each,
then dispatch each sub-task independently with its own issue + PR:

### Example: "Document all 11 seasons"

**Bad (monolithic — will time out):**
```
Task: Research and document all 11 Hermitcraft seasons
```

**Good (decomposed):**
```
Sub-task A: Research and document Seasons 1–3
Sub-task B: Research and document Seasons 4–6
Sub-task C: Research and document Seasons 7–9
Sub-task D: Research and document Seasons 10–11
```

Each sub-task:
- Creates its own branch (`research/seasons-1-3`)
- Commits incrementally (one season at a time)
- Opens a focused PR referencing the parent issue

The parent issue closes when all sub-task PRs are merged.

---

## Scope Signals (high-weight)

These patterns reliably indicate a large-scope task:

| Pattern | Example | Score Added |
|---|---|---|
| `all <category>` | "document all seasons" | +25 |
| `every <item>` | "profile every hermit" | +25 |
| 10+ items named | "11 seasons", "27 hermits" | +15 |
| research-then-write pipeline | "research and document..." | +10 |
| `comprehensive` / `complete` | "comprehensive season guide" | +10 |
| Multiple PRs expected | "create multiple PRs" | +20 |

---

## Scope Signals (negative — narrows scope)

| Pattern | Example | Score Removed |
|---|---|---|
| Fixing a single error | "fix typo in season-1" | -20 |
| Explicitly one item | "a single hermit profile" | -15 |
| Updating one field | "update the start date" | -10 |

---

## Commit Cadence for Decomposed Tasks

To further prevent timeouts within each sub-task, agents must commit
after **every item completed**, not at the end of the batch:

```
research/seasons-1-3 branch:
  commit 1: research: add Season 1 knowledge base
  commit 2: research: add Season 2 knowledge base
  commit 3: research: add Season 3 knowledge base
  → open PR
```

This means a timeout mid-batch loses at most one item's work, not the
entire batch.

---

## Supervisor Re-Dispatch Rules

1. If a task times out **once**: check scope estimator score. If ≥ 60, decompose before re-dispatching.
2. If a task times out **twice**: always decompose, regardless of score.
3. Never re-dispatch a monolithic task more than once without decomposition.
4. When re-dispatching, reference the previous task ID and timeout count in the new task description so the agent knows to commit incrementally.

---

## Tool Reference

```bash
# Get recommendation (exits 0/1/2)
python tools/task_scope_estimator.py --task "document all hermits"

# JSON output for pipeline integration
python tools/task_scope_estimator.py --json --task "document all hermits"

# Read from stdin
echo "research all seasons" | python tools/task_scope_estimator.py --stdin
```

JSON fields: `raw_score`, `recommendation`, `dispatch_flag`, `matched_signals[]`, `explanation`.
