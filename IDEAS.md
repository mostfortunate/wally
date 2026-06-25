# Ideas & Future Features

- Onboarding prompts (choose categories and set budget limits interactively)
- Annotation tool (tag or correct individual transactions inline)
How difficult would it be to create a minimal data annotation tool that is 100% parseable, or is there a tool out there that does this already? I have like 50 statements to go through, so if I could just: open pdf -> highlight transaction -> choose which category it belongs to from a dropdown, or add a new category & add it to that -> save, and go next. 2) What are some more insights we could get from statements? Before building a frontend, I'd like some more value from the app.
--
**On the annotation tool:**
Since Wally already parses the transactions, you don't actually need to open a PDF at all — the hard part is done. What you'd really be building is "show me each UNCATEGORIZED transaction, let me pick a category, save the pattern to `classification.toml`." That's a training/labeling tool that outputs rules, not raw data.
Difficulty: **low**. The existing parsed output is the input. Two realistic paths:
- **Terminal (1-2 days):** Use `textual` (TUI framework, same author as `rich`) — render a table of uncategorized transactions, arrow keys to navigate, dropdown/autocomplete for categories, saves patterns to `classification.toml`. Clean, no browser needed, fits the Pi workflow.
- **Browser (3-5 days):** Tiny FastAPI server + vanilla HTML form. More comfortable if you're doing 50 statements over multiple sessions and want to come back to it.
Nothing existing really fits — Label Studio, Prodigy, Doccano are ML annotation tools for NLP/CV, not financial classification. They'd require significant configuration to squeeze into this use case and output the wrong format. Building a focused 200-line tool is genuinely faster than adapting one.
The cleanest design: `wally annotate --rbc 2026-06.pdf` — parses, shows only UNCATEGORIZED transactions one at a time, asks for a category or "skip", then writes the new patterns into `classification.toml` automatically. 50 statements becomes a one-afternoon job.
---
**On more insights:**
Things that are valuable and don't require a frontend, roughly in order of effort:
1. **Top merchants per category** — within "gas", are you mostly at Shell vs Petro? Surfaces what's actually driving each category total. Low effort, very actionable.
2. **Recurring charge detection** — same merchant, same amount (±$1), monthly cadence = likely a subscription. Catches forgotten subscriptions. Medium effort.
3. **Savings rate** — deposits minus withdrawals (excluding inter-account transfers) as a % of deposits. One clean number per month. Very low effort given the data you already have.
4. **Uncategorized merchant frequency** — rank uncategorized transactions by how often a merchant appears. Tells you exactly which classification rules to write first. Could directly feed the annotation tool above.
5. **Month-over-month delta** (once you have 2+ months) — "you spent $40 more on takeout than last month." Requires the history feature you're about to plan but pays off immediately once it exists.
6. **Large transaction flag** — anything above a configurable threshold (e.g. $200 single transaction) gets surfaced separately. Catches one-time expenses that inflate a category.
7. **Spending by day-of-week or week-of-month** — RBC already has dates on every transaction. Useful for catching "I always overspend in the last week of the month" patterns.
The first four can ship as additional sections in the existing CLI report with no frontend at all — just extra rows below the budget table.
- A beautiful frontend
- Use CIBC categories:
Transportation: Gas, public transit, and vehicle maintenance.
Restaurants: Dining out, fast food, and coffee shops.
Groceries: Supermarkets and food markets.
Entertainment: Movies, events, and leisure.
Shopping: Retail stores and online shopping.
Personal Care: Salons, pharmacies, and fitness.
Home & Garden: Furniture, hardware, and repairs.
Travel: Flights, hotels, and vacation packages.
Utilities: Monthly household bills and subscriptions.
Services: Professional and financial services.

## Near-term (Phase 3 — pre-v1 hardening)

- Refund netting against the offset category
- Multi-page statement support
- Broader statement corpus (more edge cases, oddballs)

## API Portability

*Investigation for issue #20: can the library core be exposed over HTTP without major restructuring?*

### Separation of concerns

The pipeline functions (`parse → reconcile → classify → aggregate`) are clean of console/print
calls. No `print()` or `sys.stdout` appears in any of them. The only I/O in the hot path is
`pdfplumber.open(pdf_path)` inside each parser's `parse()` method, which reads from the
filesystem. `render()` in `src/report.py` writes to a `rich.Console`, but it is called from
`cli.py` *after* `aggregate()` returns — it is not mixed into the computation. The pipeline is
already a clean data transformation chain.

One minor observation: `src/cli.py`'s `run()` function calls `render()` directly and returns an
exit code (`int`). For an API, `run()` would be replaced by a library function that returns the
structured data instead of printing it. `run()` is thin enough that this would be a small
rewrite, not a refactor of the pipeline itself.

### Return types

All pipeline stages return typed dataclasses or plain Python types:

| Stage     | Function          | Return type             |
| --------- | ----------------- | ----------------------- |
| Parse     | `Parser.parse()`  | `Statement`             |
| Reconcile | `check_balance()` | `None` (raises on fail) |
| Classify  | `classify()`      | `list[Classified]`      |
| Aggregate | `aggregate()`     | `list[CategoryReport]`  |

`Transaction`, `Classified`, `Statement`, and `CategoryReport` are all `@dataclass` instances
with typed fields. They are not render-coupled — `report.py` consumes them but does not own
them. Serialising them for a JSON API response requires a thin adapter (e.g. `dataclasses.asdict`
plus a `Decimal`-to-string pass), not a restructuring of the types themselves.

`Direction`, `Disposition`, and `Status` are `Enum`s. Their `.name` or `.value` attributes
serialise cleanly.

### Config loading

Both config modules follow the same pattern: a pure `parse_*` function that accepts an
already-parsed `dict`, plus a `load_*` wrapper that opens a TOML file and calls it.

- `src/budget/config.py`: `parse_budget_limits(data: dict) -> BudgetLimits` (pure) and
  `load_budget_limits(path) -> BudgetLimits` (file wrapper).
- `src/classification/config.py`: `parse_rules(data: dict) -> ClassificationRules` (pure) and
  `load_rules(path) -> ClassificationRules` (file wrapper).

An API endpoint that receives config as a request body (JSON or form-encoded TOML) would call
the `parse_*` functions directly, bypassing the file wrappers entirely. No changes needed to
support this; the separation already exists.

### Error model

`ReconciliationError` (a subclass of `AssertionError`) is raised by both reconciliation gates
when a gate fails. `ClassificationError` is raised on ambiguous classification rules. Both carry
a human-readable diff string in their message.

These are clean exception types — they are not coupled to `sys.exit` or `print`. In `cli.py`,
`main()` catches `ReconciliationError` and converts it to `stderr` + exit code 2. An HTTP
adapter would catch the same exception and convert it to a structured JSON error response
(e.g. `{"error": "reconciliation_failed", "detail": str(exc)}`). No changes to the gate
functions themselves are needed; the boundary is already clean.

`ValueError` is raised by `check_balance()` when opening/closing balances are absent. An API
should handle this the same way as `ReconciliationError` — caught at the handler boundary.

### PDF ingestion

Both parsers accept a `pdf_path: str` and open the file directly inside `parse()`. An HTTP API
receives PDFs as file uploads (bytes), not filesystem paths. This is the one structural seam
that needs to change.

Current signature:
```python
def parse(self, pdf_path: str) -> Statement:
    with pdfplumber.open(pdf_path) as pdf:
        ...
```

`pdfplumber.open()` accepts a `Path`, a `str`, or a file-like object (`io.BytesIO`). The change
is a one-liner per parser: accept `str | Path | BinaryIO` and pass the argument through. The
`Parser` ABC in `src/parsers/base.py` would need its signature updated to match, since it
currently types the argument as `str`.

### What is already clean

- The full computation pipeline (`parse → reconcile → classify → aggregate`) has no console I/O
  or side effects; it is pure data transformation.
- `Statement`, `Transaction`, `Classified`, and `CategoryReport` are typed dataclasses that
  serialise without modification.
- Config loading is already split into pure `parse_*` and file-loading `load_*` functions; an
  API can call the pure functions directly with request body data.
- `ReconciliationError` and `ClassificationError` are ordinary exception types, not coupled to
  process exit; an HTTP handler catches and converts them without touching the gate functions.
- `render()` accepts an optional `Console` parameter, so it is already decoupled from stdout and
  testable in isolation. An API would simply not call it.
- `ingestion/discovery.py` (`find_latest`) is the CLI auto-discovery path only; it is never
  called from the library core and an API would not use it at all.

### What needs changing

1. **`Parser.parse()` signature** (`src/parsers/base.py`, `src/parsers/cibc.py`,
   `src/parsers/rbc.py`): Change `pdf_path: str` to `pdf_path: str | Path | BinaryIO`.
   `pdfplumber.open()` already supports all three. The `Parser` ABC, `CibcParser`, and
   `RbcParser` each need one-line updates to their method signatures. **This is the only
   structural change required.**

2. **`cli.py`'s `run()` function**: This is a CLI orchestrator that calls `render()` and returns
   an exit code. For an API, a new `pipeline()` library function should return
   `(list[CategoryReport], list[Classified])` and leave rendering to the caller. The existing
   `run()` can remain as a thin CLI wrapper over it. No existing module-level code needs
   deletion — it is additive.

3. **`ReconciliationError` as `AssertionError` subclass** (minor): Inheriting from
   `AssertionError` is unusual for an error that represents a legitimate data invariant failure
   rather than a programming bug. For API use, re-basing it on `Exception` directly would make
   the error model clearer, though this is cosmetic and not blocking.

### Recommended layering

The architecture is already correct: a clean library core with a thin CLI adapter on top. The
HTTP layer would sit alongside the CLI adapter, not replace the core.

```
                  +--------------------------------------+
                  |           library core               |
                  |  parse -> reconcile -> classify ->   |
                  |  aggregate  (no I/O, no rendering)   |
                  +----------+-------------+------------+
                             |             |
               +-------------+--+   +------+---------------+
               |   cli.py       |   |   api/handler.py     |
               |  (existing)    |   |  (new; FastAPI/Flask)|
               |  argparse +    |   |  multipart upload +  |
               |  render()      |   |  JSON response       |
               +----------------+   +----------------------+
```

Concrete steps to expose the core over HTTP:

1. Change `Parser.parse()` to accept `BinaryIO` (one-liner per parser; ~3 files).
2. Extract a `pipeline(cibc_bytes, rbc_bytes, limits, rules)` function from `cli.py`'s `run()`
   that returns `(list[CategoryReport], list[Classified])` without calling `render()`.
3. Add a `src/api/` module with a single route (e.g. FastAPI `POST /reconcile`) that accepts
   two PDF file uploads + optional config body, calls `parse_budget_limits` /
   `parse_rules` on the request config, calls `pipeline()`, and serialises the result to JSON.
4. Catch `ReconciliationError` and `ClassificationError` in the HTTP handler and return
   structured `422` error responses.

Total scope: ~3 one-line signature changes, one new `pipeline()` function extracted from existing
code, one new `src/api/` module. The library core itself is not restructured.
