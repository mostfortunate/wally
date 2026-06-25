# Parsers

`base.py` is the **frozen shared contract** — `Transaction`, `Classified`, `Statement`, `Direction`, `Disposition`, `Parser`. Do not redesign it; both parsers and everything downstream conform to it.

Parsers are the only bank-specific code. Everything downstream of a parsed `Statement` is bank-agnostic.

---

## Why coordinate-based, not markdown (a settled lesson)

We tested Microsoft `markitdown` on real statements. **CIBC converted cleanly; RBC broke.** On RBC, column alignment was unstable (amounts landed in spacer columns) and the withdrawal-vs-deposit signal was destroyed.

The root cause: in the RBC PDF, **withdrawal vs deposit is encoded as horizontal position** — the amount sits under the Withdrawals or Deposits column at a specific x-coordinate. Flattening to markdown throws that information away. The fix: read word geometry with `pdfplumber.extract_words()` (each word has `x0, x1, top, text`) and bucket amounts by column. Do not rescue flattened text with regex — parse coordinates.

---

## RBC parser (`rbc.py`) — coordinate-based

Layout: columns `Date | Description | Withdrawals($) | Deposits($) | Balance($)`, borderless (no ruled lines — work from word coordinates, not table-border detection).

- **Classify amounts by column x-band.** Anchor on the header tokens' right edges (Withdrawals/Deposits/Balance are right-aligned); bucket each money token to the nearest column edge. This is deterministic and must have unit tests.
- **Sticky dates.** The date cell is blank on continuation rows; a row inherits the date of the row above. Carry the last-seen date forward.
- **Wrapped descriptions.** Cluster tokens by `top` (shared baseline, small tolerance), then stitch description fragments. Real example: an "Online transfer received" row has the payer (`2393162ONTARIOINC.`) on its own line below.
- **Orphaned type tokens.** Lines like `ContactlessInteracpurchase-####`, `ContactlessInteracrefund-####`, `Onlinetransferreceived-####` carry the purchase/refund/transfer signal — keep them attached to their row.
- First/last rows carry `OpeningBalance` / closing balance — feed Gate 1 in `src/reconciliation/`.

---

## CIBC parser (`cibc.py`) — block-delimited

Transactions sit between a `Card number [snipped]` line and a `Total for [card]` line — those are the **block delimiters**. A row looks like:

```
Apr 26   Apr 27   AMAZON* … VANCOUVER BC   Personal and Household Expenses   30.52
```

i.e. transaction date, posting date, merchant/description, CIBC's own category label, amount. The section is titled **"YOUR NEW CHARGES AND CREDITS."** The `Total for` line is the Gate-1 anchor: charges minus credits must tie out to it, or `parse` aborts with a diff.

**Don't use `find_tables`/`extract_tables` (tested, rejected).** The CIBC PDF is borderless, so pdfplumber's line strategy finds **0 tables**, and the text strategy yields a fragmented grid that breaks words mid-token. Extract words and anchor columns from the header tokens' x-positions instead.
