# Statements

Drop bank statement PDFs here before running `wally`. All PDFs are gitignored — never commit them.

```
statements/
  cibc/   ← YYYY-MM.pdf  (e.g. 2026-06.pdf)
  rbc/    ← YYYY-MM.pdf
```

`wally` with no flags auto-discovers the alphabetically last (i.e. most recent) PDF in each subfolder. Name files `YYYY-MM.pdf` so sort order equals chronological order.
