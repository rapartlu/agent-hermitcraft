# Verification Backlog Strategy

Addresses the problem where task completion rate outpaces the verifier,
leaving many tasks in `status=done` with `quality_score=null`. The
supervisor cannot distinguish complete work from stalled work, causing
redundant re-dispatches and wasted agent cycles.

---

## Root Cause

The daemon verifies ≤ 3 tasks per 30-second cycle. If agents complete
tasks faster than that, the backlog grows unboundedly. Once a task has
been `done` but unverified for multiple cycles, the supervisor may
re-dispatch it — producing duplicate work and false failure signals.

---

## Recommended Fix: Decoupled Verification Sub-Loop

Run verification as a **separate higher-frequency loop** independent of
the main 30-second daemon cycle.

```
main daemon (30s cycle)
│
├── dispatch new tasks
├── run supervisor analysis
└── (no longer blocks on verification)

verification loop (5s cycle, runs concurrently)
│
├── query: SELECT * FROM tasks WHERE status='done' AND quality_score IS NULL LIMIT 10
├── for each task: call verifier, write quality_score + verification_status
└── emit routing event if score < 0.5 (see rejection-routing.md)
```

**Why this is better than raising the per-cycle limit:**

| Approach | Pros | Cons |
|---|---|---|
| Raise limit (3 → 10) | Simple config change | Still coupled to 30s cycle; burst completions still lag |
| Decouple sub-loop | Continuously drains backlog; scales with completion rate | Slightly more complex; needs concurrency guard |

The decoupled loop is preferred because it is self-regulating: if there
are 0 unverified tasks, it sleeps cheaply. If there are 50, it processes
10 per 5-second tick and clears the backlog in ~25 seconds.

---

## Implementation Notes

### Concurrency Guard

The verification loop must not double-verify the same task. Use an
optimistic lock or status transition:

```sql
-- Claim a batch atomically
UPDATE tasks
SET verification_status = 'in_progress'
WHERE id IN (
    SELECT id FROM tasks
    WHERE status = 'done'
      AND quality_score IS NULL
      AND verification_status IS NULL
    LIMIT 10
)
RETURNING *;
```

### Batch Size Tuning

| Tasks in backlog | Recommended batch | Expected clear time |
|---|---|---|
| < 10 | 5 | 5–10s |
| 10–50 | 10 | 25–50s |
| > 50 | 15 | 50–75s |

Start with batch size 10. Raise only if the verifier is consistently
idle (backlog < batch size for 3+ consecutive ticks).

### Fallback: Raise the Per-Cycle Limit

If the decoupled loop is not feasible immediately, raise the per-cycle
verification limit from 3 to **8** as an interim fix. This reduces lag
under moderate load without requiring architectural changes.

```python
# orchestrator config — interim fix
MAX_VERIFY_PER_CYCLE = 8  # was 3
```

Do not raise above 10 without also adding the concurrency guard, or
multiple daemon instances may verify the same tasks simultaneously.

---

## Supervisor Behaviour Change

Once the verification loop is decoupled, the supervisor should:

1. **Never re-dispatch a task that is `status=done, verification_status=in_progress`.**
   It is being verified — wait one more cycle.

2. **Re-dispatch only if `verification_status` has been `in_progress` for
   > 2 minutes** (the verifier itself may have stalled).

3. **Use `quality_score IS NULL AND verification_status IS NULL AND
   updated_at < NOW() - INTERVAL '5 minutes'`** as the signal for a
   truly stalled/dropped task, not just `quality_score IS NULL`.

---

## Metrics to Track

Add these to the supervisor's cycle summary to detect future backlogs early:

```
unverified_done_tasks: <count>        # target: < 5
verification_lag_p50: <seconds>       # target: < 30s
verification_lag_p95: <seconds>       # target: < 120s
tasks_reverified: <count>             # target: 0 (dedup is working)
```

If `unverified_done_tasks` exceeds 10 for two consecutive cycles, emit
an `infrastructure` alert — the verification loop may be down.
