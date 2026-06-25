# Classification

Every transaction is parsed first, then classified. The engine outputs a **disposition**, not just a category:

- **CATEGORIZED** — maps to a real budget category (configurable, merchant-specific, extensible).
- **EXCLUDED** — money that moved or is counted elsewhere; deliberately *not spend*. Always carries a `reason`. Examples: inter-account transfers, the CIBC card payment. EXCLUDED means *not spending*.
- **UNCATEGORIZED** — real spend we couldn't attribute. **Never silently dropped.** Surfaces in the report as a warning. UNCATEGORIZED means *spending we can't label*.

Keep EXCLUDED and UNCATEGORIZED distinct — collapsing both into "ignore" was explicitly rejected. A transfer (correctly zero budget impact) and unlabeled cash (real budget impact we just can't slot) are different claims.

## Precedence

EXCLUDED > CATEGORIZED > UNCATEGORIZED. An ambiguous match (two rules match the same transaction) raises rather than guesses.

## CIBC card payment exclusion

The CIBC card auto-pays from the RBC chequing account, so the payment appears **on both statements**. Both sides must be excluded:

- RBC side: description normalizes to `"cibc cpd"` (exact string: `"Misc Payment CIBC CPD"`)
- CIBC side: description normalizes to `"payment thank you"`

Both are configured under the same exclusion reason in `classification.toml`.
