# Budget

Aggregates CATEGORIZED spend per category and compares against configured monthly limits. EXCLUDED and UNCATEGORIZED are intentionally not folded in — see `src/classification/CLAUDE.md`.

Status thresholds: **OVER** when spend exceeds limit; **UNDER** when spend is below 50% of limit; **WITHIN** otherwise.

---

## Semantics gotchas — wrong totals even when parsing is perfect

Most bugs live here, not in the parsers.

**1. CIBC card payment double-count.**  
The card auto-pays from the RBC chequing account. The payment appears **on the RBC statement as a withdrawal** *and* the card's purchases appear on the CIBC statement. Counting both doubles your spend. Both sides must be EXCLUDED — see `src/classification/CLAUDE.md`.

**2. CIBC "credits" are a mix.**  
On a credit card, charges = purchases = the expense we want. Credits split into: refunds/returns (net against their category), the payment (EXCLUDE), and rewards/statement credits. An unrecognized credit is most likely a refund or rewards credit. Confirm against the per-card `Total for` line.

**3. Uncategorized cash & e-transfers must surface, not vanish.**  
Cash withdrawn was spent on *something*; an unlabeled e-transfer moved real money. Dropping them makes the app under-report. Route to UNCATEGORIZED and warn — never silently drop.

**4. No date/month attribution.**  
Statement = scope. Parse and sum what's in the PDF. Transaction dates are for audit/ordering only. Do not add logic to map transactions to calendar months or billing cycles.
