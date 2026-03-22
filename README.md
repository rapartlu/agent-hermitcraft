# Hermitcraft Agent

A self-learning AI agent that builds comprehensive knowledge about [Hermitcraft](https://hermitcraft.com) — the Minecraft SMP (Survival Multiplayer) series. The agent continuously discovers, organizes, and refines information about Hermitcraft's players, seasons, builds, lore, in-jokes, and history.

## How It Works

The agent operates in a continuous improvement loop:

1. **Orchestrator** assigns tasks (research topics, knowledge gaps, improvements)
2. **Agent** researches via web scraping/searching, then proposes changes
3. Changes go through a **PR-based review workflow** (issue -> branch -> PR -> review -> merge)
4. Knowledge and capabilities compound over time

## Knowledge Domains

The agent aims to build expertise across all aspects of Hermitcraft:

- **Players/Hermits** — current and past members, real names, channels, specialties
- **Seasons** — timeline, world seeds, major events, server rules
- **Builds & Mega-projects** — notable builds, shopping districts, community projects
- **Lore & Storylines** — Demise, Turf War, civil wars, tag games, etc.
- **In-jokes & Memes** — "Grain" vs Grian, Mumbo's moustache, Scar's landscaping, etc.
- **Collaborations** — notable collabs, rivalries, recurring duos
- **Technical Minecraft** — notable redstone/technical builds from the server
- **Community** — fan culture, recap channels, wiki resources

## Architecture

```
hermitcraft-agent/
├── knowledge/          # Structured knowledge base (markdown + data files)
├── tools/              # Scripts for scraping, searching, data processing
├── prompts/            # Agent prompt templates and system instructions
├── tests/              # Validation and fact-checking
└── .claude/            # Agent configuration and memory
```

## Workflow

All changes follow a structured process:

1. **Issue** — Create a GitHub issue describing the task
2. **Branch** — Work on a feature branch
3. **PR** — Open a pull request with the changes
4. **Review** — Orchestrator reviews and leaves comments
5. **Iterate** — Address review comments
6. **Merge** — Merge to main once approved

## Getting Started

This project is designed to be operated by a Claude-based orchestrator. The agent template is used by a Claude proxy and agent orchestrator to continuously improve the knowledge base.
