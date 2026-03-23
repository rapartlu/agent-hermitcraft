# Rejection Routing Prompt

When the verifier rejects a task with a score below `0.5`, use this prompt
to decide how to route the rejection **before** dispatching a follow-up task.

---

## Classification Step

Read the verification notes and score. Ask: **can the agent fix this alone?**

### Infrastructure-Blocked (escalate — do NOT redispatch to agent)

Escalate if the notes contain any of:

- Authentication / credentials missing (`gh CLI not authenticated`, `GITHUB_TOKEN`, `permission denied`)
- Missing environment capability (`command not found`, `env var not set`, `container`)
- Network / connectivity issues (`connection refused`, `rate limit`, `DNS`, `quota exceeded`)
- Deployment / secret management (`secret`, `SSH key`, `certificate`)

**Action:** Create a GitHub issue on the agent's repo tagged `infrastructure` with:
1. The task ID and score
2. The exact capability that is missing
3. Steps the orchestrator must take to resolve it

Do **not** redispatch the task — it will fail again for the same reason.

---

### Fixable (dispatch revision guidance to agent)

Classify as fixable (dispatch revision guidance) if the notes describe:

- Wrong content (incorrect facts, missing sections, outdated data)
- Formatting / structure errors (YAML frontmatter invalid, markdown broken)
- Logic errors in tooling scripts
- Incomplete work (only some files written, branch not pushed)

**Action:** Dispatch a follow-up task to the agent **immediately** (do not wait
for the next supervisor cycle) with:

```
Task: Revise <original task description>
Previous score: <score>
Issues found:
<bullet list from verification notes>

Fix each issue above and push to the same branch.
```

---

## Routing Decision Tree

```
verifier score < 0.5?
│
├─ yes → classify_rejection(notes)
│         │
│         ├─ infrastructure-blocked → escalate to orchestrator
│         │                           create infra issue
│         │                           do NOT redispatch
│         │
│         └─ fixable → dispatch revision task immediately
│                       include specific correction steps
│                       reference original task ID
│
└─ no  → (score 0.5–0.74) → add to next supervisor review queue
         (score ≥ 0.75)   → accept, merge/close issue
```

---

## Tool Reference

The `tools/rejection_classifier.py` script implements the classification
logic and can be called programmatically:

```bash
# Returns exit 0 (fixable) or 1 (infrastructure-blocked)
python tools/rejection_classifier.py \
  --task-id 01KMC05Z \
  --score 0.35 \
  --notes "gh CLI not authenticated, GITHUB_TOKEN not set in container"

# JSON output for pipeline use
python tools/rejection_classifier.py --json \
  --task-id 01KMC05Z \
  --score 0.35 \
  --notes "gh CLI not authenticated"
```

Example JSON output:
```json
{
  "classification": "infrastructure-blocked",
  "confidence": 0.9,
  "matched_pattern": "not authenticated",
  "recommended_action": "Escalate to orchestrator...",
  "task_id": "01KMC05Z",
  "score": 0.35
}
```
