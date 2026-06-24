# Fixtures — the test oracle

This is where the Phase-0 oracle lives: real statement PDFs paired with **hand-keyed
expected category totals**. Golden-file tests assert the pipeline reproduces those totals
to the penny.

Per bank, collect 2–3 statements including oddballs (multi-page, a refund, an unrecognized
credit). For each, hand-key the expected totals into a sibling file (e.g.
`rbc_2024_03.pdf` + `rbc_2024_03.expected.json`).

## ⚠️ Sensitive data

Statement PDFs contain full account PII.

- **Never** commit unscrubbed statements to a public remote.
- **Never** send statement contents to an external API.
- Decide deliberately where these fixtures live; this is a data-handling decision, not
  just a technical one. See CLAUDE.md → *Sensitive data*.
