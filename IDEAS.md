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

## Statement auto-download (`wally download`)

A `wally download` command that uses Playwright to navigate to the CIBC and RBC online banking
statement pages and download PDFs automatically — no manual save required.

**Why bother:** The one-time cost is downloading ~50 historical statements. After that it's just
2 PDFs a month (one CIBC, one RBC), which is trivial — but having it scripted means a monthly
`wally download && wally` just works.

**Key design constraint — no credential storage:**
Use `playwright.chromium.launch_persistent_context(user_data_dir=<chrome-profile-path>)`.
This opens a real Chrome window with the user's existing profile (cookies, saved sessions
intact). If the user is already logged in to both banks, Playwright goes straight to the
statements page and downloads. If the session has expired, the user logs in and completes 2FA
manually in the opened window, then Playwright takes over. No passwords or OTPs ever touch
Wally config.

This sidesteps the main blockers:
- No credential storage risk — session lives in the browser profile as normal
- No RBC mobile-app 2FA problem — user completes it once in the window if needed
- No bot-detection issues — runs in a real, non-headless Chrome with the user's real fingerprint

**Scope:**
- `wally download --cibc` — navigates to CIBC online banking statements, downloads the latest
  (or a date range) as PDF into `statements/cibc/`
- `wally download --rbc` — same for RBC into `statements/rbc/`
- CIBC and RBC have different DOM structures; two separate scraper implementations needed
- New dependency: `playwright` + `playwright install chromium`

**What it is not:** A headless cron job. The user must have Chrome open or Wally opens it.
Fully unattended automation is a non-goal — 2FA and session expiry make it unreliable.

## Near-term (Phase 3 — pre-v1 hardening)

- Refund netting against the offset category
- Multi-page statement support
- Broader statement corpus (more edge cases, oddballs)
