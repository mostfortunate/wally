# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

Remote: `https://github.com/mostfortunate/wally.git`

# Wally, a Monthly Budget Tracker — Developer Guide
A CLI tool that reads bank statement PDFs, categorises every transaction, and reports
whether each spending category is **within budget, underspending, or overspending**.

---

## 🔒 Privacy — statement files are off-limits

**Never open, read, or inspect any file under `statements/`** (e.g. `statements/cibc/*.pdf`,
`statements/rbc/*.pdf`) without explicit consent from the user **in the same conversation turn**.

Even when the user has granted consent:
1. Ask for confirmation a second time before opening the file.
2. Use the file only for the specific purpose consented to — do not read it for any other reason.

Statement PDFs contain real personal financial data. When in doubt, do not open them.

---

## ⚠️ Read this first: what kind of system this is

This is a **reconciliation system that happens to parse PDFs** — not a PDF parser that happens
to do budgeting. The success bar is *provable correctness of the numbers*, not "the parse looks
right." Every design decision flows from that.

Two facts an agent must internalize before touching anything:

1. **Money is `Decimal`, never `float`, everywhere.** A float-rounding penny will trip a
   reconciliation gate that exists to catch *real* errors, and you won't be able to tell the two
   apart. Parse strings straight into `Decimal`.

2. **The two reconciliation gates are runtime invariants, not just tests.** A failed gate
   **aborts the run with a diff** and produces no report. It does not silently emit a wrong
   budget. See `src/reconciliation/CLAUDE.md`.

If you find yourself about to (a) convert a statement to markdown/plain text before parsing,
(b) use a `float` for an amount, (c) silently drop a transaction, or (d) add transaction→month
date-attribution logic — stop. Each of those is a decision we already made and rejected, with
reasons recorded in the module-level CLAUDE.md files.

---

## Scope

> ⏳ Pre-v1: these out-of-scope constraints exist to keep the initial build focused. Revisit at v1.

- **No frontend, no banking-API integration, no notifications.** v1 is a CLI.
- **No transaction→budget-month attribution logic.** Because upload is manual and one statement
  at a time, **the statement *is* the scope.** We parse the transactions in the PDF and sum them.
  Do **not** add date-to-calendar-month mapping.

---

## Tech stack

| Concern         | Choice                                |
| --------------- | ------------------------------------- |
| Language        | Python 3.14+                          |
| PDF parsing     | `pdfplumber` (word-level coordinates) |
| Money type      | `decimal.Decimal`                     |
| Interface       | CLI over a clean library core         |
| Testing         | `pytest` + golden-file fixtures       |
| Env / packaging | `uv`                                  |
| Report output   | `rich` for colour & alignment         |

We chose Python specifically for the PDF/parsing ecosystem. **Do not reach for an LLM to parse
transactions** — extraction is deterministic and must be exact.

---

## Build, test & development commands

```bash
uv sync --extra dev                       # install app + dev dependencies
uv run wally                              # run (auto-discovers latest statements)
uv run wally --cibc <pdf> --rbc <pdf>     # explicit paths
uv run pytest                             # run the test suite
uv run ruff check src/ tests/             # lint
uv run ruff format --check src/ tests/    # formatting check
uv run pyright src/                       # type check
```

Before opening a PR: `uv run ruff check --fix src/ tests/` and `uv run ruff format src/ tests/`.

---

## Coding style

Ruff defaults, 99-character line length, 4-space indentation. snake_case for modules, functions,
and variables; PascalCase for classes. Prefer small, composable helpers over large functions.
Money-handling code stays in `Decimal` end to end (lint won't catch a stray `float` — reviewers must).

---

## Project structure

```
src/
  ingestion/        # load PDF, detect bank, dispatch to parser; auto-discover latest
  parsers/
    base.py         # frozen shared contract — see src/parsers/CLAUDE.md
    cibc.py         # credit-card parser (block-delimited)
    rbc.py          # chequing parser (coordinate-based)
  reconciliation/   # the two runtime gates (abort on failure)
  classification/   # transaction → disposition; configurable rules + exclusions
  budget/           # category limits, aggregation, within/under/over logic
  report.py         # rich terminal renderer
  cli.py            # entry point; wires the pipeline
statements/         # drop YYYY-MM.pdf files here (gitignored)
tests/
  fixtures/         # sample PDFs + hand-keyed expected totals (the oracle)
CLAUDE.md           # this file
IDEAS.md            # future features and Phase 3 backlog
```

Each `src/` subdirectory and `tests/` has its own `CLAUDE.md`. The shared data model is in
`src/parsers/base.py` — see `src/parsers/CLAUDE.md`.

---

## Git workflow

**NEVER commit or edit files directly on `main`. Always create a branch first, even for trivial
changes. No exceptions.** `main` is protected; all changes go through a PR.

### Branches — one per unit of work

```bash
git checkout main && git pull
git checkout -b feat/my-feature
```

Prefixes: `feat/`, `fix/`, `chore/`, `refactor/`, `test/`, `docs/`.

### Commits — Conventional Commits

```
<type>(<optional scope>): <description>
```

Types: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `build`, `ci`, `perf`.

Commits are **small and focused** — one logical unit each.

### Pull requests

Open with `gh pr create`. Title follows Conventional Commits. Body:

```
## What
## How
## Testing
```

### Investigation issues

When a GitHub issue asks for investigation or a summary (not implementation), **post findings as a comment on the issue** using `gh issue comment <number> --body "..."`. Do **not** open a PR and do **not** close the issue — the human decides what to do with the findings.

### Merging

- Always **merge, never rebase**; merge via a merge commit (not squash).
- **Do not delete branches after merging** — keep full history.
- **Never call `gh pr merge`** — opening PRs is the agent's job; merging is the human's.

---

## Parallel work with subagents

When work is split across multiple subagents running in parallel, **agree a shared contract
before spawning any of them.**

1. **Frozen shared types & signatures.** Pin data structures and function signatures first —
   `src/parsers/base.py` is the canonical example. Agents conform; they do not redesign.
2. **Disjoint file ownership.** Each agent touches only its own module + tests. No parallel agent
   edits `cli.py` or `src/parsers/base.py` — those are shared seams.
3. **Orchestrator-owned integration.** Cross-cutting wiring and branch merging is done by the
   orchestrator after agents finish, never by the parallel agents themselves.
4. **Name the branch yourself, before launching.** Use `git worktree add -b feat/<thing> <path>
   <base-ref>` — do not rely on worktree auto-naming (`worktree-agent-<id>`), which ignores
   Conventional Commits prefixes.

Untracked local files (e.g. statement PDFs) do not appear in a worktree checkout. Copy them in
explicitly if an agent needs one.

---

## Versioning

Semantic Versioning (`MAJOR.MINOR.PATCH`). Currently `0.x.y` — minor versions may include
breaking changes until `1.0.0`. Bump `version` in `pyproject.toml` in the same commit that
introduces the change.

Sections marked `⏳ Pre-v1` are explicitly temporary constraints. Remove them when v1 ships.
