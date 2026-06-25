# Reconciliation

Two gates, two *different* guarantees. Both run at runtime; a failure aborts the run with a diff and a non-zero exit — no report is emitted.

## Gate 1 — Balance gate

*Did we parse every transaction?*

Primarily for RBC, which prints a running balance:

```
opening_balance + Σ(deposits) − Σ(withdrawals) == closing_balance
```

If a single amount is missed or mis-signed (e.g. a withdrawal classified as a deposit), this identity breaks. This is why we keep the Deposits and Balance columns even though budgets only care about withdrawals — they make the withdrawal set *self-verifying*.

For CIBC, the analogous anchor is the per-card **"Total for [card]"** line: `charges − credits` must equal it. This check runs inside the parser per block, not at the statement level (CIBC has no statement-level opening/closing balance).

## Gate 2 — Partition gate

*Did we account for every parsed transaction?*

```
Σ(categorized) + Σ(excluded) + Σ(uncategorized) == Σ(all transactions)
```

Gate 1 proves nothing fell out of *parsing*. Gate 2 proves nothing fell out of *budgeting*. Together: nothing leaks.
