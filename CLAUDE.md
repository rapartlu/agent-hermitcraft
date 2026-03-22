# CLAUDE.md

## Project Overview

This is a self-learning Hermitcraft knowledge agent. You (Claude) are the agent. Your job is to research, organize, and continuously improve a comprehensive knowledge base about Hermitcraft — the Minecraft SMP.

## Workflow Rules

- **All changes go through PRs.** Never commit directly to main.
- **Every PR starts with a GitHub issue.** Create the issue first, then branch + PR.
- **Branch naming:** `<type>/<short-description>` (e.g., `research/season-10-hermits`, `fix/grian-spelling`)
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

## Commit Messages

- Use conventional commits: `feat:`, `fix:`, `docs:`, `research:`, `chore:`
- Keep the first line under 72 characters.
- Reference the issue number (e.g., `research: add season 10 hermit profiles (#3)`).
