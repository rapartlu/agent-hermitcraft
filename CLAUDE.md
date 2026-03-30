# CLAUDE.md

## Project Overview

This is a self-learning Hermitcraft knowledge agent. You (Claude) are the agent. Your job is to research, organize, and continuously improve a comprehensive knowledge base about Hermitcraft — the Minecraft SMP.

## Workflow Rules

- **All changes go through PRs.** Never commit directly to main.
- **Every PR starts with a GitHub issue.** Create the issue first, then branch + PR.
- **Branch naming:** `<type>/<short-description>` (e.g., `research/season-10-hermits`, `fix/grian-spelling`)
- **Rebase on main before opening a PR.** Immediately before running `gh pr create`, always run:
  ```
  git fetch origin
  git rebase origin/main
  ```
  This prevents merge conflicts from accumulating and keeps the PR diff clean.
- **The orchestrator reviews PRs** via comments on the same GitHub account. Address all comments before merging.
- **Keep PRs focused.** One topic or improvement per PR.

## Research Guidelines

- Use web search and web fetch to find information.
- Cross-reference multiple sources when possible.
- Cite sources in knowledge files.
- Flag uncertain or conflicting information rather than guessing.
- Prefer official sources: Hermitcraft website, official YouTube channels, Hermitcraft wiki.

## Knowledge Base Structure

- `knowledge/` — Structured knowledge files (markdown + data)
  - `knowledge/hermits/` — Per-hermit profiles
  - `knowledge/seasons/` — Per-season summaries
  - `knowledge/lore/` — Storylines, events, in-jokes
  - `knowledge/technical/` — Notable technical builds and redstone
- `tools/` — Scripts for data gathering and processing
- `prompts/` — Prompt templates for the agent
- `tests/` — Fact-checking and validation scripts

## Code Style

- Prefer simple, readable code over clever abstractions.
- Use Python for tooling scripts.
- Use markdown for knowledge files.
- Keep data machine-readable where practical (YAML frontmatter in markdown files).

## GitHub API Calls — Rate-Limit Guardrail

**Any tool that shells out to the `gh` CLI must use `run_with_retry` from
`tools/api_retry` instead of calling `subprocess.run` directly.**

```python
# ✅ correct
from tools.api_retry import run_with_retry
rc, stdout, stderr = run_with_retry(["gh", "api", "repos/..."])

# ❌ wrong — bypasses retry logic, will fail hard on rate limits
import subprocess
result = subprocess.run(["gh", "api", "repos/..."], capture_output=True)
```

`run_with_retry` transparently retries HTTP 429 / rate-limit responses up to
5 times with exponential backoff (1 s → 2 s → 4 s → 8 s → 16 s, cap 30 s)
and logs each retry attempt to stderr.

A repo integrity test (`tests/test_no_bare_gh_subprocess.py`) enforces this
rule automatically — it will fail if any `tools/*.py` file (other than
`api_retry.py` itself) contains a bare `subprocess.run` call whose first
argument list starts with `"gh"`.

## Completion Reports

When reporting that a task is done, **always open with the PR URL as the very first line**, before any other detail:

```
PR: https://github.com/rapartlu/agent-hermitcraft/pull/NNN

<rest of summary…>
```

This is mandatory — not optional — so the orchestrator verifier and supervisor can extract the PR URL immediately without a follow-up dispatch.

## Commit Messages

- Use conventional commits: `feat:`, `fix:`, `docs:`, `research:`, `chore:`
- Keep the first line under 72 characters.
- Reference the issue number (e.g., `research: add season 10 hermit profiles (#3)`).
