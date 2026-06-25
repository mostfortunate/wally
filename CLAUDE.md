# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

Remote: `https://github.com/mostfortunate/wally.git`

# Wally, a Budget Reconciliation CLI — Developer Guide

A backend-only service that ingests manually-uploaded bank statement PDFs, extracts and
classifies every transaction, aggregates spending against monthly budget limits, and reports
whether each category is **within budget, underspending, or overspending**.

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

## What it answers

> For each budget category this period: did I spend within my limit, under it, or over it?

Input: one statement PDF at a time, uploaded manually. Output (v1): terminal report.

---

## Scope

### In scope (v1)

- Parse RBC chequing/debit statements and CIBC credit-card statements (different layouts).
- Classify every transaction via a configurable, extensible engine.
- Aggregate against per-category monthly limits.
- Emit a monthly report (terminal output) with within/under/over status per category.

### Out of scope — and *why* (so it doesn't get reintroduced)

- **No frontend, no banking-API integration, no notifications.** v1 is a CLI.
- **No automated statement download (Playwright etc.).** Rejected: would require storing banking
  credentials on the host (Raspberry Pi) — not worth it for a once-a-month task. Also RBC's 2FA
  requires tapping a push notification in the app, which is impractical to automate. Statements
  are uploaded **manually**.
- **No transaction→budget-month attribution logic.** Because upload is manual and one statement
  at a time, **the statement *is* the scope.** We parse the transactions in the PDF and sum them;
  there is no need to map a transaction's date to a calendar month or reconcile a billing cycle
  (e.g. CIBC's 25th–24th cycle) against a calendar month. Do **not** add this.

---

## Tech stack

| Concern         | Choice                                | Status     |
| --------------- | ------------------------------------- | ---------- |
| Language        | Python 3.14+                          | decided    |
| PDF parsing     | `pdfplumber` (word-level coordinates) | decided    |
| Money type      | `decimal.Decimal`                     | decided    |
| Interface       | CLI over a clean library core         | decided    |
| Testing         | `pytest` + golden-file fixtures       | convention |
| Env / packaging | `uv`                                  | convention |
| Report output   | `rich` for colour & alignment         | convention |

We chose Python specifically for the PDF/parsing ecosystem. **Do not reach for an LLM to parse
transactions** — extraction is deterministic and must be exact; an LLM belongs nowhere near the
numbers.

---

## Build, test & development commands

Python 3.14+ with `uv`.

```bash
uv sync --extra dev                 # install app + dev dependencies
uv run wally                        # run against statements/ (auto-discovers latest)
uv run wally --cibc <pdf> --rbc <pdf>  # explicit paths
uv run pytest                       # run the test suite
uv run ruff check src/ tests/       # lint
uv run ruff format --check src/ tests/  # formatting check
uv run pyright src/                 # type check
```

Before opening a PR: `uv run ruff check --fix src/ tests/` and `uv run ruff format src/ tests/`.

---

## Coding style

Ruff defaults, 99-character line length, 4-space indentation. snake_case for modules, functions,
and variables; PascalCase for classes. Prefer small, composable helpers over large functions —
this matters most in the parsers, where row-stitching and x-band logic should each be testable
units. Money-handling code stays in `Decimal` end to end (lint won't catch a stray `float` —
reviewers must).

---

## Project structure

```
src/
  ingestion/        # load PDF, detect bank, dispatch to parser; auto-discover latest statement
  parsers/
    base.py         # frozen shared contract: Transaction, Classified, Statement, Parser ABC
    cibc.py         # credit-card parser (block-delimited)
    rbc.py          # chequing parser (coordinate-based)
  reconciliation/   # the two runtime gates (abort on failure)
  classification/   # transaction → disposition; configurable rules + exclusions
  budget/           # category limits, aggregation, within/under/over logic
  report.py         # rich terminal renderer
  cli.py            # entry point; wires the pipeline
statements/
  cibc/             # drop YYYY-MM.pdf files here
  rbc/              # drop YYYY-MM.pdf files here
tests/
  fixtures/         # sample statement PDFs + hand-keyed expected totals (the oracle)
  ...               # mirrors src/
CLAUDE.md           # this file — repo-wide conventions
IDEAS.md            # future features backlog
```

Each `src/` subdirectory has its own `CLAUDE.md` with module-specific design decisions.

**Parsers are the only bank-specific code.** Everything downstream of a parsed `Statement` is
shared and bank-agnostic.

---

## Core data model

The shared contract — defined in `src/parsers/base.py`, never redesigned by individual modules.

```python
class Direction(Enum):    WITHDRAWAL, DEPOSIT
class Disposition(Enum):  CATEGORIZED, EXCLUDED, UNCATEGORIZED

@dataclass
class Transaction:
    raw_description: str
    amount: Decimal           # Decimal, never float
    direction: Direction
    date: date | None         # audit/ordering only
    balance: Decimal | None   # RBC running balance; feeds Gate 1

@dataclass
class Classified:
    txn: Transaction
    disposition: Disposition
    category: str | None      # set iff CATEGORIZED
    reason: str | None        # set iff EXCLUDED

@dataclass
class Statement:
    bank: str
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transactions: list[Transaction]
```

---

## Build sequence

Each phase's "done" is defined by a gate or the oracle — not by "looks right."

- **Phase 0 — Foundations + test oracle.** Lock the data model and interfaces. Collect 2–3 real
  statements per bank and **hand-key the expected category totals.** Nothing else starts until
  this oracle exists.
- **Phase 1 — CIBC vertical slice, end to end.** Build the whole pipeline on the clean parser
  first. Validates architecture and both gates against the easy bank.
  *Done when:* CIBC report matches hand-keyed totals and the partition gate holds.
- **Phase 2 — RBC parser.** Drop the hard parser onto the proven pipeline.
  *Done when:* RBC reconciles to the penny and matches hand-keyed totals.
- **Phase 3 — Hardening.** Refund netting, multi-page statements, broader corpus.
  *Done when:* full corpus passes both gates with zero manual intervention.

---

## Testing

```bash
uv run pytest
```

- **Golden-file tests** per statement, keyed to hand-verified totals (the Phase-0 oracle).
- **Reconciliation gates run at runtime** — failure aborts with a diff, not just a red test.
- **Unit tests** for every pure, deterministic function, written in the same commit as the function.
- Tests live under `tests/` mirroring `src/`.
- Commit real statement fixtures with care — see [Sensitive data](#sensitive-data).

---

## Sensitive data

Statement PDFs contain full account PII. Keep them out of any public remote unless scrubbed, and
**never send statement contents to an external API.** Personal config (`wally.toml`,
`classification.toml`) is gitignored — commit only the `*.example.toml` templates.

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

---

## Inputs needed from the human

1. **Sample statements** — 2–3 per bank, including oddballs (multi-page, a refund, an unrecognized credit).
2. **The CIBC-payment description string** on the RBC statement — so the exclusion rule is data, not a guess. *(Resolved: "Misc Payment CIBC CPD")*
3. **Budget categories + monthly limits** — so the report has something to measure against.
