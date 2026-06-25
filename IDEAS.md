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

## Caching

> Issue #19: skip re-parsing static statements on re-runs.

Wally re-parses every PDF from scratch on each run. Parsing is CPU-bound pdfplumber geometry
extraction — notably slow on multi-page statements. Statements named `YYYY-MM.pdf` are static
after upload (~1% amendment rate), making them ideal cache targets.

### Cache key: file hash, not filename stem

Two options:

- **Filename stem (e.g. `2026-05`)** — fast (no file read), but wrong: if the user overwrites a
  `YYYY-MM.pdf` with an amended statement the cache silently serves stale data. A cache that
  can be invalidated by an event it cannot observe is not safe for a reconciliation system.
- **SHA-256 of the PDF content** — requires one pass over the file bytes (cheap compared to
  pdfplumber), but is correct: a changed file produces a different hash and misses the cache.
  The cache entry key becomes `sha256:<hex-digest>`.

**Decision: SHA-256.** The overhead is negligible; the correctness guarantee is not optional
for a system whose success bar is provable-correct numbers. Filename stems may be included as
metadata in the cache entry for human readability (e.g. in `wally cache list`) but must never
be the lookup key.

### Where the cache should live

Options:

- **`~/.cache/wally/`** — follows XDG Base Directory convention; survives across project
  copies; shared if the user runs wally from multiple directories. Downside: a bit distant
  from the statements.
- **`statements/.cache/`** — co-located with the PDFs; intuitive to find; already in the
  `.gitignore` path (the `statements/` dir is gitignored). Downside: if the user moves the
  statements directory the cache moves with it (acceptable, since the hash key still works).
- **Next to each PDF** — e.g. `statements/cibc/2026-05.cache` — maximally obvious, but
  pollutes the statement directory with paired sidecar files and complicates `find_latest`.

**Decision: `~/.cache/wally/`** using `platformdirs.user_cache_dir("wally")`. This is the
standard location for application caches on all three platforms (Linux/macOS/Windows), it
doesn't pollute the repo directory, and it survives worktree switches. If a frontend/API is
added later (issue #20) it will naturally share the same cache without any wiring. Structure:

```
~/.cache/wally/
  statements/
    sha256-<hex>.json   # one file per unique PDF content
```

The `statements/` subdirectory keeps the cache organised if other cache namespaces are added
later (e.g. a future classification cache).

### Serialisation format: JSON with string amounts

Constraints: must round-trip `Decimal` exactly (no float), must be readable without special
tools, must not require a new dependency.

Options:

| Format         | Decimal-safe?           | Stdlib? | Notes                                                         |
| -------------- | ----------------------- | ------- | ------------------------------------------------------------- |
| JSON (floats)  | No                      | Yes     | Rejected — breaks the reconciliation gate                     |
| JSON (strings) | Yes, with care          | Yes     | Amounts stored as `"30.52"`, loaded via `Decimal("30.52")`   |
| `pickle`       | Yes                     | Yes     | Not human-readable; format ties to CPython version            |
| `msgpack`      | Only with ext type      | No      | Extra dependency; overkill for the volume                     |
| `tomllib`      | No native Decimal       | Yes (read-only in 3.11+) | Not designed for serialisation              |

**Decision: JSON with string amounts.** Store every `Decimal` field as a plain string
(`"30.52"`, not `30.52`). The loader reconstructs via `Decimal(s)`. This is the same
discipline as the parsers themselves ("parse strings straight into Decimal"). No new
dependency, human-readable, diff-friendly. The cache file schema:

```json
{
  "cache_version": 1,
  "pdf_sha256": "abc123...",
  "bank": "RBC",
  "opening_balance": "1234.56",
  "closing_balance": "987.00",
  "transactions": [
    {
      "raw_description": "Online transfer received",
      "amount": "500.00",
      "direction": "DEPOSIT",
      "date": "2026-05-04",
      "balance": "1734.56"
    }
  ]
}
```

A `cache_version` field allows the schema to evolve without serving stale entries from an
older format — increment it on any breaking change and treat a version mismatch as a cache
miss.

### Where caching slots into the pipeline

The natural seam is at the `Parser.parse()` call boundary in `src/cli.py`'s `run()` function.
The calls today are:

```python
cibc_stmt = CibcParser().parse(cibc_path)
rbc_stmt  = RbcParser().parse(rbc_path)
```

A thin `cached_parse(parser, pdf_path, *, cache_dir, no_cache)` wrapper in
`src/ingestion/cache.py` intercepts both calls with the same interface:

1. Compute SHA-256 of `pdf_path`.
2. Look up `<cache_dir>/statements/sha256-<hex>.json`.
3. On hit: deserialise and return the `Statement` (microseconds).
4. On miss: call `parser.parse(pdf_path)`, serialise the result, write the cache file, return.

This keeps the cache logic out of the parsers (they stay pure) and out of `cli.py` (it stays
thin). The `Parser` interface in `src/parsers/base.py` is not touched. `cli.py` gains one
import and two wrapper calls — the rest of the pipeline (reconciliation gates, classification,
budget aggregation) is unchanged and unaware of caching.

`src/ingestion/cache.py` owns:
- `pdf_sha256(path: str | Path) -> str`
- `load_cached(sha256: str, cache_dir: Path) -> Statement | None`
- `save_cached(stmt: Statement, sha256: str, cache_dir: Path) -> None`
- `cached_parse(parser: Parser, pdf_path: str, *, cache_dir: Path, no_cache: bool) -> Statement`

This design also means a future API layer (issue #20) can call `cached_parse` directly from
its own handler without going through the CLI, keeping the cache benefit without coupling to
argparse.

### UX for cache busting

Two options under consideration in the issue:

- **`--no-cache` flag** — explicit opt-out for a single run; cache is still read on future
  runs. Communicates "skip the cache this time."
- **`wally cache clear`** — subcommand to wipe the cache directory entirely. Useful for
  recovering disk space or resetting after a parser bug.

**Decision: both, in that order of priority.**

1. `--no-cache` flag on `wally` bypasses both reading and writing the cache for that run. It
   is the escape hatch for the ~1% amended-statement case.
2. `wally cache clear` as a subcommand (alongside the existing `wally init`) for full cache
   eviction. Low implementation cost: `shutil.rmtree(cache_dir / "statements")`.
3. A `wally cache list` subcommand (lower priority) to show cached statement hashes and the
   stems they were computed from — useful for debugging.

A `--dry-run` flag is not the right vehicle for cache busting: its meaning ("show what would
happen without side effects") conflicts with "force a fresh parse but still write the result."
Keep `--dry-run` for its conventional meaning if it is ever added.

### Opt-in vs opt-out

**Opt-out by default (cache is on unless `--no-cache` is passed).** The cache is safe —
correctness is protected by the hash key — and the user benefit (sub-second re-runs) is
immediate and universal. An opt-in cache would require every user to discover the flag before
getting the speedup. The only reason to make it opt-in would be if the cache risked correctness
errors, and the hash-keyed design eliminates that risk.

The cache directory is created on first use; no `wally init` step is needed.

### Summary of decisions

| Question              | Decision                                                                    |
| --------------------- | --------------------------------------------------------------------------- |
| Cache key             | SHA-256 of PDF content                                                      |
| Cache location        | `~/.cache/wally/statements/sha256-<hex>.json` (via `platformdirs`)         |
| Serialisation         | JSON with Decimal fields stored as strings; `cache_version` field          |
| Pipeline seam         | `src/ingestion/cache.py` wrapping parser calls in `cli.py`                 |
| Cache busting         | `--no-cache` flag + `wally cache clear` subcommand                         |
| Default behaviour     | Opt-out (cache on by default)                                               |

---

## Near-term (Phase 3 — pre-v1 hardening)

- Refund netting against the offset category
- Multi-page statement support
- Broader statement corpus (more edge cases, oddballs)
