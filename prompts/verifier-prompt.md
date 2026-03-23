# Verifier Prompt

Instructions for scoring a completed agent task and assigning a
verification status.

---

## Three-Status Model

Every completed task receives one of three statuses — **not two**:

| Status | Meaning | Next action |
|---|---|---|
| `verified` | Score ≥ 0.75, no infrastructure blocker | Accept; merge PR / close issue |
| `rejected` | Score < 0.75, agent-caused shortfall | Dispatch revision guidance immediately |
| `blocked`  | Infrastructure blocker detected | Escalate to orchestrator; do NOT re-dispatch agent |

The `blocked` status is distinct from `rejected`. A blocked task may
have been completed correctly by the agent — the failure is in the
environment, not the work.

---

## Step 1 — Scan for Infrastructure Blockers First

Before scoring, read the task result and check for any of the following
signals. If found, the task is `blocked` regardless of outcome:

- Authentication / credentials: `gh CLI not authenticated`, `GITHUB_TOKEN not set`, `permission denied`
- Missing tools: `command not found`, `gh: not found`
- Container / environment limits: `container`, `env var not set`, `no such file or directory`
- Network failures: `connection refused`, `network timeout`, `DNS`, `rate limit`, `quota exceeded`
- Secret management: `SSH key`, `certificate`, `secret not available`

**If a blocker is present:**
1. Note the exact signal in your verification notes.
2. Score *only the agent's portion* of the work (see Step 2b).
3. Set status = `blocked`.
4. Do not penalise the score for the infrastructure step the agent could not complete.

Use `tools/verifier_score_adjuster.py` to compute the adjusted score:

```bash
python tools/verifier_score_adjuster.py \
  --score <raw_score> \
  --result "...task result text..."
```

---

## Step 2a — Standard Scoring (no blocker)

Evaluate the task against its acceptance criteria. Consider:

| Dimension | Weight |
|---|---|
| Correctness (facts, logic, data) | 40% |
| Completeness (all required items present) | 30% |
| Format / structure (YAML, markdown, tests pass) | 20% |
| Commit hygiene (message, branch, references issue) | 10% |

Score 0.0–1.0.  Accept at ≥ 0.75; reject below.

---

## Step 2b — Adjusted Scoring (blocker present)

When an infra blocker is confirmed, the observable outcome
(e.g. no PR created) reflects the environment, not the agent.

Score only what the agent controlled:
- Were the files written correctly? (correctness + completeness + format)
- Were commits made properly?
- Did the agent explicitly flag the blocker in its output?

Exclude from scoring:
- Whether the PR was created (requires `gh` auth)
- Whether remote push succeeded (requires `GH_TOKEN`)
- Any step after the blocker was hit

The adjuster applies a 25% infra weight correction automatically:
`adjusted_score = min(raw_score / 0.75, 1.0)`

---

## Step 3 — Write Verification Notes

Notes must include:

1. **Status**: `verified` / `rejected` / `blocked`
2. **Score**: raw score (and adjusted score if blocked)
3. **Evidence**: specific lines from the result that support the score
4. **Blocker signal** (if blocked): exact matched pattern
5. **Next action**: what the orchestrator should do

### Example — blocked task

```
Status: blocked
Raw score: 0.35 → adjusted: 0.47
Blocker: "GITHUB_TOKEN not set in container" (matched: 'github[_ ]token')
Evidence: Agent committed all 11 season files (46ea6ad, 7dda94c).
          Push failed with: fatal: could not read Username — GH_TOKEN missing.
Agent work: complete. Infrastructure work: blocked.
Next action: inject GH_TOKEN into container; re-run push step only.
             Do NOT re-dispatch full research task.
```

### Example — rejected task

```
Status: rejected
Score: 0.45
Evidence: Season 10 file lists TinfoilChef as returning member (left before S10).
          Season 8 end date incorrect (2020 vs 2021).
Next action: dispatch revision task with specific corrections.
```

### Example — verified task

```
Status: verified
Score: 0.82
Evidence: All 27 hermit profiles present with correct YAML frontmatter.
          Tests pass. Branch pushed. PR opened with issue reference.
Next action: approve and merge.
```

---

## Quick Reference

```bash
# Adjust score for infra blocker (exits 0=verified, 1=rejected, 2=blocked)
python tools/verifier_score_adjuster.py --score 0.35 \
  --result "Committed all files. Push failed: GITHUB_TOKEN not set."

# JSON output for pipeline
python tools/verifier_score_adjuster.py --score 0.35 --json \
  --result "..."

# Also see:
#   tools/rejection_classifier.py  — classify fixable vs infra-blocked
#   prompts/rejection-routing.md   — routing decisions after rejection
```
