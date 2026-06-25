# Tests

Tests live under `tests/` mirroring `src/`. Run with `uv run pytest`.

- **Golden-file tests** per statement, keyed to hand-verified totals — these are the oracle. A passing gate is the definition of "done," not "looks right."
- **Reconciliation gates run at runtime** — a failure aborts with a diff, not just a red test.
- **Unit tests** for every pure, deterministic function, written in the same commit as the function — never as a follow-up.

## Sensitive data

`tests/fixtures/` holds real statement PDFs — full account PII. Keep them out of any public remote. Never send fixture contents to an external API. They are gitignored from the public remote; add new fixtures to `.gitignore` before committing.
