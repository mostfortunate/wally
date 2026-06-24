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
   budget. See [Reconciliation gates](#reconciliation-gates).

If you find yourself about to (a) convert a statement to markdown/plain text before parsing,
(b) use a `float` for an amount, (c) silently drop a transaction, or (d) add transaction→month
date-attribution logic — stop. Each of those is a decision we already made and rejected, with
reasons recorded below.

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

| Concern        | Choice                                  | Status   |
| -------------- | --------------------------------------- | -------- |
| Language       | Python 3.14+.                           | decided  |
| PDF parsing    | `pdfplumber` (word-level coordinates)   | decided  |
| Money type     | `decimal.Decimal`                       | decided  |
| Interface      | CLI over a clean library core           | decided  |
| Testing        | `pytest` + golden-file fixtures         | convention |
| Env / packaging| `uv`                                    | convention |
| Report output  | stdout, `chalk` for clarity & richness  | convention |

We chose Python specifically for the PDF/parsing ecosystem. **Do not reach for an LLM to parse
transactions** — extraction is deterministic and must be exact; an LLM belongs nowhere near the
numbers. (If categorization ever needs fuzzy matching, that's the only place an LLM could earn a
spot, and we don't need it yet.)

---

## Build, test & development commands

Python 3.14+ with `uv`.

```bash
uv sync --extra dev                 # install app + dev dependencies
uv run python -m src.cli <statement.pdf>   # run the CLI against a statement
uv run pytest                       # run the test suite
ruff check src/ tests/              # lint
ruff format --check src/ tests/     # formatting check
uv run pyright src/                 # type check
```

Before opening a PR: `ruff check --fix src/ tests/` and `ruff format src/ tests/`.

> CI enforcement / pre-commit hooks for the above are not set up yet — TODO. For now run them
> locally.

## Coding style

Ruff defaults, 99-character line length, 4-space indentation. snake_case for modules, functions,
and variables; PascalCase for classes (e.g. `Transaction`, `Disposition`). Prefer small,
composable helpers over large functions — this matters most in the parsers, where row-stitching
and x-band logic should each be testable units, not one monolithic `parse()`. Money-handling code
stays in `Decimal` end to end (lint won't catch a stray `float` — reviewers must).

---

## Project structure

```
src/
  ingestion/        # load the uploaded PDF, detect bank, dispatch to parser
  parsers/
    base.py         # Statement / Transaction interface both banks implement
    cibc.py         # credit-card parser (block-delimited)
    rbc.py          # chequing parser (coordinate-based)
  reconciliation/   # the two gates, as assertions run on every parse
  classification/   # transaction -> disposition; configurable rules + exclusions
  budget/           # category limits, aggregation, within/under/over logic
  cli.py            # entry point + terminal report
tests/
  fixtures/         # sample statement PDFs + hand-keyed expected totals (the oracle)
  ...               # mirrors src/; golden-file + unit tests
CLAUDE.md
```

**Parsers are the only bank-specific code.** Everything downstream of a parsed `Statement` is
shared and bank-agnostic.

---

## Core data model

Pin this down before anything else — both gates and the disposition split depend on it.

```python
class Direction(Enum):    WITHDRAWAL, DEPOSIT
class Disposition(Enum):  CATEGORIZED, EXCLUDED, UNCATEGORIZED

@dataclass
class Transaction:
    raw_description: str
    amount: Decimal           # Decimal, never float
    direction: Direction
    date: date | None         # RBC dates are "sticky" (see parser notes); audit/ordering only
    balance: Decimal | None   # RBC running balance; feeds the balance gate

@dataclass
class Classified:
    txn: Transaction
    disposition: Disposition
    category: str | None      # set iff CATEGORIZED
    reason: str | None        # set iff EXCLUDED (e.g. "CIBC card payment")

@dataclass
class Statement:
    bank: str
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transactions: list[Transaction]
```

---

## Reconciliation gates

Two gates, two *different* guarantees. Both run at runtime; a failure aborts with a diff.

**Gate 1 — Balance gate (did we parse *every* transaction?).** Primarily for RBC, which prints a
running balance:

```
opening_balance + Σ(deposits) − Σ(withdrawals) == closing_balance
```

If a single amount is missed or mis-signed (e.g. a withdrawal classified as a deposit), this
identity breaks. This is why we keep the Deposits and Balance columns even though budgets only
care about withdrawals — they make the withdrawal set *self-verifying*. For CIBC, the analogous
anchor is the per-card **"Total for [card]"** line (charges − credits must tie out).

**Gate 2 — Partition gate (did we *account for* every parsed transaction?).** Every classified
transaction lands in exactly one disposition, and they must sum back to the whole:

```
Σ(categorized) + Σ(excluded) + Σ(uncategorized) == Σ(all transactions)
```

Gate 1 proves nothing fell out of *parsing*. Gate 2 proves nothing fell out of *budgeting*.
Together: nothing leaks.

---

## Parsing approach

### Why coordinate-based, not markdown (a settled lesson)

We tested Microsoft `markitdown` on real statements. **CIBC converted cleanly; RBC broke.** On
RBC, column alignment was unstable (amounts landed in spacer columns) and the
withdrawal-vs-deposit signal was destroyed.

The root cause: in the RBC PDF, **withdrawal vs deposit is encoded as horizontal position** — the
amount sits under the Withdrawals or Deposits column at a specific x-coordinate. Flattening to
markdown is exactly the step that throws that information away. The fix is to *not flatten*: read
the word geometry with `pdfplumber.extract_words()` (each word has `x0, x1, top, text`) and bucket
amounts by column. Do not try to rescue flattened text with regex — parse coordinates.

### RBC parser (chequing/debit) — coordinate-based

Known layout: columns `Date | Description | Withdrawals($) | Deposits($) | Balance($)`, borderless
(no ruled lines, so work from word coordinates, not table-border detection).

- **Classify amounts by column x-band.** Anchor on the header tokens' right edges
  (Withdrawals/Deposits/Balance are right-aligned); bucket each money token to the nearest column
  edge. This is deterministic and is the one piece that *must* have unit tests.
- **Sticky dates.** The date cell is blank on continuation rows; a row inherits the date of the
  row above. Carry the last-seen date forward. (No year-inference needed — one statement is one
  period.)
- **Wrapped descriptions.** Cluster tokens by `top` (shared baseline, small tolerance), then
  stitch description fragments. Real example: an "Online transfer received" row has the payer
  (`2393162ONTARIOINC.`) wrapped onto its own line below.
- **Orphaned type tokens.** Lines like `ContactlessInteracpurchase-####`,
  `ContactlessInteracrefund-####`, `Onlinetransferreceived-####` carry the
  purchase/refund/transfer signal — keep them attached to their row.
- First/last rows include `OpeningBalance` / closing balance — feed Gate 1.

### CIBC parser (credit card) — block-delimited

Known layout: transactions sit between a `Card number [snipped]` line and a `Total for [card]`
line — use those as **block delimiters**. A line looks like:

```
Apr 26   Apr 27   AMAZON* … VANCOUVER BC   Personal and Household Expenses   30.52
```

i.e. transaction date, posting date, merchant/description, CIBC's own category label, amount.
The section is titled **"YOUR NEW CHARGES AND CREDITS."** CIBC parses cleanly, but prefer
`pdfplumber` here too (one extraction philosophy, one validation path, and robust when CIBC
reflows its layout). The `Total for` line is the Gate-1 anchor.

---

## Classification & dispositions

Every transaction is parsed first, then classified. The engine outputs a **disposition**, not just
a category:

- **CATEGORIZED** — maps to a real budget category (configurable, merchant-specific, extensible).
- **EXCLUDED** — money that moved or is counted elsewhere; deliberately *not spend*. Always carries
  a `reason`. Examples: inter-account transfers, the CIBC card payment (see below). EXCLUDED means
  *not spending*.
- **UNCATEGORIZED** — real spend we couldn't attribute. **Never silently dropped.** Surfaces in the
  report as a warning. UNCATEGORIZED means *spending we can't label*.

Keep EXCLUDED and UNCATEGORIZED distinct — collapsing both into "ignore" was explicitly rejected,
because a transfer (correctly zero budget impact) and unlabeled cash (real budget impact we just
can't slot) are different claims.

---

## Budget-semantics gotchas (the expensive ones)

These cause *wrong totals even when parsing is perfect*. Most bugs will live here.

1. **CIBC card payment double-count.** The card auto-pays from the **RBC chequing account** (in
   this dataset). So the payment appears **on the RBC statement as a withdrawal** *and* the card's
   purchases appear on the CIBC statement. Counting both doubles your spend. The RBC card-payment
   line must be **EXCLUDED**.
   - Note: "pre-authorized debit" describes *how* the money is pulled, not *which* account — it
     does not tell you whether the line appears on RBC. It does, because RBC funds it.
   - **Action item (don't guess):** grep one RBC statement for the payment amount to get the exact
     description string, then make it a data-driven exclusion rule. (See [Inputs needed](#inputs-needed-from-the-human).)

2. **CIBC "credits" are a mix.** On a credit card, charges = purchases = the expense we want.
   Credits reduce what's owed (inflows to the card) and split into: refunds/returns (should
   **net against** the category they offset), the payment (**EXCLUDE** — not spending), and
   occasionally a rewards/statement credit. An unrecognized credit is most likely a small refund
   or a rewards credit. Confirm against the per-card `Total for` line.

3. **Uncategorized cash & e-transfers must surface, not vanish.** Cash withdrawn was spent on
   *something*; an unlabeled e-transfer moved real money. Dropping them makes the app
   under-report and falsely say "underspending." Route to UNCATEGORIZED and report as a warning,
   e.g.:
   ```
   Uncategorized: X transactions totalling $Y in withdrawals and $Z in deposits.
   ```

4. **No date/month attribution.** (Restated because it's tempting to add.) Statement = scope.
   Parse and sum what's in the PDF. Transaction dates are for audit/ordering only.

---

## Build sequence

Each phase's "done" is defined by a gate or the oracle — not by "looks right."

- **Phase 0 — Foundations + test oracle.** Lock the data model and the parser/reconciliation
  interfaces (designed for both banks now, so neither parser forces a refactor later). Collect
  2–3 real statements per bank and **hand-key the expected category totals.** Nothing else starts
  until this oracle exists.
- **Phase 1 — CIBC vertical slice, end to end.** Build the *whole* pipeline on the clean parser
  first (parser → classification/dispositions → budget report → CLI). This validates the
  architecture and **both gates** against the easy bank, so RBC's only unknown is its parser.
  *Done when:* CIBC report matches hand-keyed totals and the partition gate holds.
- **Phase 2 — RBC parser.** Drop the hard parser onto the proven pipeline: coordinate extraction,
  x-band amount classification, sticky dates, balance gate. Exclude the CIBC card payment here.
  *Done when:* RBC reconciles to the penny and matches hand-keyed totals.
- **Phase 3 — Hardening.** Refund netting against the offset category, multi-page statements,
  wrapped-description edge cases, broaden the corpus. *Done when:* the full corpus passes both
  gates with zero manual intervention.

---

## Testing

```bash
pytest
```

- **Golden-file tests** per statement, keyed to known hand-verified totals (the Phase-0 oracle).
- **Reconciliation assertions run as runtime gates** — a failure aborts the run with a diff, not
  just a red test.
- **Unit tests** focused on the two fiddly, deterministic pieces: column-bucketing by
  x-coordinate, and sticky-date inheritance.
- **Any pure function (deterministic, no side effects) must have a test, written in the same
  commit as the function** — not as a follow-up. Tests live under `tests/` mirroring `src/`
  (the one adaptation from co-located tests, since golden fixtures need a home).
- Commit real statement fixtures with care — see [Sensitive data](#sensitive-data).

---

## Sensitive data

Statement PDFs contain full account PII. Decide deliberately where fixtures live, keep them out of
any public remote unless scrubbed, and **never send statement contents to an external API.** This
is a data-handling decision, not just a technical one.

---

## Git workflow

**NEVER commit or edit files directly on `main`. Always create a branch first, even for trivial
changes. No exceptions.** `main` is protected; all changes go through a PR.

### Branches — one per unit of work

```bash
git checkout main && git pull
git checkout -b feat/rbc-coordinate-parser
```

Prefixes: `feat/`, `fix/`, `chore/`, `refactor/`, `test/`, `docs/`.

### Commits — Conventional Commits

```
<type>(<optional scope>): <description>

[optional body]
```

Types: `feat`, `fix`, `chore`, `refactor`, `test`, `docs`, `build`, `ci`, `perf`. Examples:

```bash
git commit -m "feat(rbc): classify amounts by column x-band"
git commit -m "fix(classify): exclude CIBC card payment from RBC withdrawals"
git commit -m "test(reconciliation): balance-gate diff on mis-signed withdrawal"
```

Commits are **small and focused** — one logical unit each. Separate commits for: adding a
dependency, implementing a module, and wiring it together. Batching makes review harder.

### Pull requests

Open with `gh pr create` after pushing. Title follows Conventional Commits. Body:

```
## What
What changed and why.

## How
Any non-obvious implementation detail.

## Testing
How to verify (which fixtures, which gate).
```

### Merging

- Always **merge, never rebase**; merge via a merge commit (not squash).
- **Do not delete branches after merging** — keep full history.

---

## Versioning

Semantic Versioning (`MAJOR.MINOR.PATCH`). Currently `0.x.y` — public API not yet stable; minor
versions may include breaking changes until `1.0.0`. Bump `version` (in `pyproject.toml`) in the
same commit that introduces the change.

---

## Inputs needed from the human

These are required before/at Phase 0 and are inputs, not things to guess:

1. **Sample statements** — 2–3 per bank, including oddballs (multi-page, a refund, an unrecognized
   credit).
2. **The CIBC-payment description string** on the RBC statement (grep one statement for the
   payment amount) — so the exclusion rule is data, not a guess.
3. **Budget categories + monthly limits** (e.g. takeout $100, gas $300) — so the report has
   something to measure against.