# Clearway — CLAUDE.md

Behavioral contract for Claude Code on this repo. This is not documentation — every line should change how the agent acts. Keep under ~200 lines.

## Source of truth — read first, don't duplicate

- **Architecture / decisions:** `ARCHITECTURE.md`.
- **Schemas:** `CONTRACTS.md` §3 — the only place a cross-module shape is defined. To change one: edit §3, then its §5 + §6 in the same change. Never redefine a schema elsewhere.
- **Milestone tickets:** `specs/` — start with `specs/M0-walking-skeleton.md`.

## Progress / state

We use Claude Code's auto-memory (`MEMORY.md`) as the progress log — **`PROGRESS.md` === `MEMORY.md`; there is no separate progress file.** Read it at the start of each session. At the end of a work session, record what was completed and what's next in `MEMORY.md` so the next session resumes without re-deriving state.

## Stack & conventions

- Python 3.13+. Deps/env: `uv`. Format + lint: `ruff`. Types: `mypy`. Tests: `pytest`.
- Data models: **Pydantic v2** (see `CONTRACTS.md`). Contracts are strict (`extra="forbid"`); SC ids are canonical dotted form (`"1.1.1"`), never `wcag111`.
- Monorepo; module boundaries are in `ARCHITECTURE.md` §6. Work inside one module per branch / `git worktree`. Everything depends on `schemas/`; nothing depends on `orchestrator/` or `api/`.

## Commands

- Install: `uv sync`
- Local stack: `docker compose up -d` — services + rationale live in `ARCHITECTURE.md` §4 (SSOT). *Compose file is a setup prerequisite; create it at M0 observability work.*
- Test: `uv run pytest`
- Lint / format: `uv run ruff check .` / `uv run ruff format .`
- Types: `uv run mypy clearway`

## Rules of engagement

- Do not add a dependency without asking first.
- Do not edit `CONTRACTS.md` schemas without updating its §5 + §6 in the same change.
- Never commit secrets. API keys / DB URL / Ollama endpoint come from `.env` (see `.env.example`).
- Scraping: respect robots.txt, rate-limit, set an explicit User-Agent. Prefer fixture pages; live scanning is a demo feature only.
- Prefer surgical edits over rewrites. Write a test for each new behavior.
- Pin versions that affect reproducibility (axe-core, models).
- The human reviews all code and tests — surface a plan before large or cross-module changes.
- Each ticket in `specs/` is **self-contained**: complete it from the ticket + `CONTRACTS.md` alone — a subagent won't see the rest of a conversation. One ticket ≈ one branch / `git worktree`.

## Commit workflow

- Before every commit: run `uv run ruff check .`, `uv run ruff format .`, `uv run mypy clearway`, and `uv run pytest`. All must pass green. Do not commit if any fail — fix and rerun instead.
- Commit only currently staged files. Never `git add` more to broaden a commit.
- Each commit = exactly one small thing (one fix, one feature, one improvement). If staged files span more than one concern, stop and ask how to split them.
- Propose the commit message before committing: Conventional Commits format, title only — `type(scope): concise description`. No body/description.
- Never commit without explicit user approval, even in Accept All / Auto mode.

## Definition of done (per ticket)

A ticket is done when code + tests pass, it matches the `CONTRACTS.md` shapes it touches, and its acceptance criteria in the milestone spec are met — **not** when the code is merely written.
