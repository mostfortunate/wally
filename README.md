# Wally

A backend-only **budget reconciliation CLI**. It ingests manually-uploaded bank-statement
PDFs (RBC chequing/debit, CIBC credit card), extracts and classifies every transaction,
aggregates spending against monthly budget limits, and reports whether each category is
**within budget, underspending, or overspending**.

This is a reconciliation system that happens to parse PDFs — the success bar is *provable
correctness of the numbers*. Two non-negotiables:

- **Money is `Decimal`, never `float`, everywhere.**
- **Two reconciliation gates run at runtime.** A failed gate aborts the run with a diff and
  emits no report.

See [CLAUDE.md](CLAUDE.md) for the full developer guide and the design decisions behind
every module.

## Quick start

```bash
uv sync --extra dev                          # install app + dev dependencies
uv run python -m src.cli <statement.pdf>     # run against one statement
uv run pytest                                # run the suite
ruff check src/ tests/                        # lint
uv run pyright src/                          # type check
```

## Status

Phase 0 scaffold: core data model, parser/reconciliation interfaces, and the two gates are
in place (with tests). Parsers, classification, budget aggregation, and the terminal report
are stubbed for Phases 1–3. See the build sequence in CLAUDE.md.
