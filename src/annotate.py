"""Rule-harvesting annotator for wally.

`wally annotate` finds UNCATEGORIZED transactions across parsed statements,
deduplicates by normalized description, and presents an all-at-once form where
the user can assign each unique merchant to a category. On Ctrl+D, patterns are
written to classification.toml as production config.

`wally annotate list` shows an interactive picker of every statement. Navigate
with ↑/↓, press Enter to annotate the selected statement, and press q or Escape
to quit.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import tomli_w
from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.styles import Style
from rich.console import Console

from src.classification import ClassificationRules, classify, load_rules, normalize
from src.ingestion.cache import cached_parse
from src.ingestion.discovery import find_all
from src.parsers.base import Classified, Disposition, Transaction
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser

_console = Console()

_FORM_HINT = "1-0 shortcut · type to search · ↑↓/Tab next · Ctrl+D save · Ctrl+C cancel"
_DESC_WIDTH = 40
_AMOUNT_WIDTH = 10
_INPUT_WIDTH = 22
_DIGIT_ORDER = list(range(1, 10)) + [0]  # 1-9 then 0 = 10 slots


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _guess_category(normalized: str, rules: ClassificationRules) -> str | None:
    """Return the single matching category, or None if 0 or 2+ match."""
    matches = [
        cat for cat, patterns in rules.categories.items() if any(p in normalized for p in patterns)
    ]
    return matches[0] if len(matches) == 1 else None


def _default_pattern(normalized: str) -> str:
    """Derive a reusable TOML pattern from a normalized description.

    'timhortons#2813' -> 'timhortons'
    'dollarama#1201'  -> 'dollarama'
    'amazonby8ue6y60' -> 'amazon'
    'bp'              -> 'bp'   (short name: returned as-is)
    """
    # Strip trailing #digits or bare digit run
    trimmed = re.sub(r"#?\d+$", "", normalized)
    # Take letters-only prefix up to first digit — no lower bound on length
    prefix_match = re.match(r"^[a-z$]+", trimmed)
    if prefix_match and len(prefix_match.group(0)) < len(trimmed):
        return prefix_match.group(0)
    return trimmed or normalized


def _append_rule(rules_path: Path, category: str, pattern: str) -> None:
    """Append pattern to category in classification.toml. Creates file if absent.

    Atomic write: temp file + rename. Idempotent: no-op if pattern already present.
    category is expected to already be normalized (lowercase, stripped).
    """
    if rules_path.exists():
        with rules_path.open("rb") as fh:
            data = tomllib.load(fh)
    else:
        data = {}
    cats: dict[str, list[str]] = data.setdefault("categories", {})
    existing = list(cats.get(category, []))
    if pattern not in existing:
        existing.append(pattern)
    cats[category] = existing
    tmp = rules_path.with_suffix(".toml.tmp")
    with tmp.open("wb") as fh:
        tomli_w.dump(data, fh)
    tmp.replace(rules_path)


def _unique_uncategorized(classified: list[Classified]) -> list[Transaction]:
    """Return one Transaction per unique merchant, UNCATEGORIZED only.

    Uniqueness is determined by the base pattern derived from the normalized description
    (via _default_pattern) so that e.g. "TIM HORTONS #2813" and "TIM HORTONS #9001" are
    treated as the same merchant and only the first-seen transaction is returned.
    """
    seen: set[str] = set()
    result: list[Transaction] = []
    for c in classified:
        if c.disposition is not Disposition.UNCATEGORIZED:
            continue
        key = _default_pattern(normalize(c.txn.raw_description))
        if key not in seen:
            seen.add(key)
            result.append(c.txn)
    return result


def _all_unique_with_category(
    classified: list[Classified],
) -> list[tuple[Transaction, str | None]]:
    """Return (txn, current_category) for every unique merchant, EXCLUDED skipped.

    CATEGORIZED rows carry their assigned category; UNCATEGORIZED rows carry None.
    Uniqueness key is the same _default_pattern used elsewhere.
    """
    seen: set[str] = set()
    result: list[tuple[Transaction, str | None]] = []
    for c in classified:
        if c.disposition is Disposition.EXCLUDED:
            continue
        key = _default_pattern(normalize(c.txn.raw_description))
        if key not in seen:
            seen.add(key)
            cat = c.category if c.disposition is Disposition.CATEGORIZED else None
            result.append((c.txn, cat))
    return result


# ---------------------------------------------------------------------------
# Session file helpers (kept for backward compatibility; tested in test_annotate.py)
# ---------------------------------------------------------------------------

_SESSION_VERSION = 1


def _load_session(session_path: Path) -> set[str]:
    """Load set of already-handled normalized descriptions from session file."""
    if not session_path.exists():
        return set()
    try:
        data = json.loads(session_path.read_text())
        if data.get("session_version") == _SESSION_VERSION:
            return set(data.get("handled", []))
    except json.JSONDecodeError, KeyError, TypeError:
        pass
    return set()


def _save_session(session_path: Path, normalized_desc: str) -> None:
    """Append one normalized description to session file. Atomic write via tmp + rename."""
    handled = _load_session(session_path)
    handled.add(normalized_desc)
    tmp = session_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"session_version": _SESSION_VERSION, "handled": sorted(handled)}))
    tmp.replace(session_path)


def _delete_session(session_path: Path) -> None:
    """Remove session file if it exists."""
    if session_path.exists():
        session_path.unlink()


# ---------------------------------------------------------------------------
# Interactive form (prompt_toolkit)
# ---------------------------------------------------------------------------


def _run_annotate_form(
    queue: list[tuple[Transaction, str | None]],
    rules: ClassificationRules,
) -> dict[int, str] | None:
    """All-at-once assignment form.

    queue is a list of (transaction, prefill_category) — prefill_category is the current
    classification or None when unknown.  Returns {queue_index: category_name} for every
    confirmed non-empty field, or None if aborted.
    """
    category_names = sorted(rules.categories.keys())
    # Digit shortcuts: 1-9 then 0, mapped to first 10 sorted categories
    shortcuts: dict[str, str] = {
        str(_DIGIT_ORDER[i]): cat for i, cat in enumerate(category_names[:10])
    }
    completer = WordCompleter(category_names, ignore_case=True, sentence=True)

    buffers: list[Buffer] = []
    for i, (txn, prefill) in enumerate(queue):
        # Use current category, fall back to guess from pattern matching
        text = prefill or _guess_category(normalize(txn.raw_description), rules) or ""
        doc = Document(text)
        buffers.append(
            Buffer(
                name=f"txn_{i}",
                document=doc,
                completer=completer,
                complete_while_typing=True,
                multiline=False,
            )
        )

    kb = KeyBindings()

    # Digit shortcuts — eager so they take priority over buffer character input
    for _key, _cat in shortcuts.items():

        @kb.add(_key, eager=True)
        def _assign(event: KeyPressEvent, _bound: str = _cat) -> None:
            cur = event.app.layout.current_buffer
            if cur is not None:
                cur.set_document(Document(_bound))

    @kb.add("down")
    @kb.add("tab")
    def move_next(event: KeyPressEvent) -> None:
        cur = event.app.layout.current_buffer
        for i, buf in enumerate(buffers):
            if buf is cur:
                event.app.layout.focus(buffers[(i + 1) % len(buffers)])
                return

    @kb.add("up")
    def move_prev(event: KeyPressEvent) -> None:
        cur = event.app.layout.current_buffer
        for i, buf in enumerate(buffers):
            if buf is cur:
                event.app.layout.focus(buffers[(i - 1) % len(buffers)])
                return

    @kb.add("enter")
    def enter_or_next(event: KeyPressEvent) -> None:
        cur = event.app.layout.current_buffer
        if cur is None:
            return
        cs = cur.complete_state
        if cs and cs.current_completion:
            cur.apply_completion(cs.current_completion)
            return
        for i, buf in enumerate(buffers):
            if buf is cur:
                event.app.layout.focus(buffers[(i + 1) % len(buffers)])
                return

    @kb.add("c-d")
    def confirm(event: KeyPressEvent) -> None:
        result = {i: buf.text.strip().lower() for i, buf in enumerate(buffers) if buf.text.strip()}
        event.app.exit(result=result)

    @kb.add("c-c")
    @kb.add("escape")
    def abort(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    def get_legend() -> StyleAndTextTuples:
        if not shortcuts:
            return [("class:dim", "  (no categories yet — type a name to create one)")]
        parts: StyleAndTextTuples = []
        items = list(shortcuts.items())
        for idx, (key_str, cat) in enumerate(items):
            if idx == 5:
                parts.append(("", "\n"))
            parts.append(("class:shortcut-key", f"  {key_str}"))
            parts.append(("", f" {cat}"))
        return parts

    def make_label(buf: Buffer, txn: Transaction) -> FormattedTextControl:
        desc = txn.raw_description[:_DESC_WIDTH]
        sign = "+" if txn.direction.name == "DEPOSIT" else ""
        amount_str = f"{sign}${txn.amount}"

        def get() -> StyleAndTextTuples:
            try:
                focused = get_app().layout.current_buffer is buf
            except Exception:
                focused = False
            label = f"  {desc:<{_DESC_WIDTH}}  {amount_str:>{_AMOUNT_WIDTH}}  "
            return [("class:label-focused" if focused else "class:label", label)]

        return FormattedTextControl(get)

    def make_row(buf: Buffer, txn: Transaction) -> VSplit:
        return VSplit(
            [
                Window(content=make_label(buf, txn), dont_extend_width=True, height=1),
                Window(
                    content=BufferControl(buffer=buf, focusable=True),
                    width=_INPUT_WIDTH,
                    height=1,
                ),
            ]
        )

    legend_height = 2 if len(shortcuts) > 5 else 1

    layout = Layout(
        HSplit(
            [
                Window(
                    content=FormattedTextControl(f"Assign categories — {len(queue)} merchants"),
                    height=1,
                ),
                Window(content=FormattedTextControl(get_legend), height=legend_height),
                Window(height=1),
                *[make_row(buf, txn) for buf, (txn, _) in zip(buffers, queue, strict=True)],
                Window(height=1),
                Window(
                    content=FormattedTextControl("  Ctrl+D save  ·  Ctrl+C cancel"),
                    height=1,
                ),
            ]
        ),
        focused_element=buffers[0],
    )

    style = Style.from_dict(
        {
            "label": "",
            "label-focused": "bold",
            "shortcut-key": "bold fg:ansicyan",
            "dim": "fg:ansibrightblack",
            "hint": "fg:ansigreen",
        }
    )

    app: Application[dict[int, str] | None] = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=False,
        mouse_support=False,
    )
    return app.run()


# ---------------------------------------------------------------------------
# PDF loading
# ---------------------------------------------------------------------------


def _collect_transactions(cibc_paths: list[str], rbc_paths: list[str]) -> list[Transaction]:
    """Parse all provided PDFs and return their combined transaction list."""
    txns: list[Transaction] = []
    cibc = CibcParser()
    rbc = RbcParser()
    for p in cibc_paths:
        stmt = cached_parse(p, cibc)
        txns.extend(stmt.transactions)
    for p in rbc_paths:
        stmt = cached_parse(p, rbc)
        txns.extend(stmt.transactions)
    return txns


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_annotate(
    cibc_paths: list[str],
    rbc_paths: list[str],
    rules_path: str = "classification.toml",
) -> int:
    """Entry point for `wally annotate`. Returns process exit code."""
    if not cibc_paths and not rbc_paths:
        print("error: provide at least one --cibc or --rbc PDF", file=sys.stderr)
        return 1

    rp = Path(rules_path)
    transactions = _collect_transactions(cibc_paths, rbc_paths)
    if not transactions:
        print("No transactions found.")
        return 0

    rules = load_rules(rp) if rp.exists() else ClassificationRules(categories={}, exclusions={})
    classified = classify(transactions, rules)
    queue = _all_unique_with_category(classified)

    if not queue:
        print("No transactions found.")
        return 0

    assignments = _run_annotate_form(queue, rules)

    if assignments is None:
        _console.print("\nCancelled — no changes saved.")
        return 0

    if not assignments:
        _console.print("\nNo categories assigned.")
        return 0

    for idx, category in assignments.items():
        txn, _ = queue[idx]
        pattern = _default_pattern(normalize(txn.raw_description))
        _append_rule(rp, category, pattern)

    count = len(assignments)
    _console.print(
        f"\n[bold]Done.[/bold] Wrote [green]{count}[/green] rule(s) to [bold]{rp}[/bold]."
    )
    return 0


def _build_list_rows(
    entries: list[tuple[str, str]],
    rules: ClassificationRules,
) -> list[tuple[str, str, int, int, bool]]:
    """Parse each statement and return display rows.

    Returns a list of (filename, bank, n_total, n_uncategorized, is_done) tuples.
    """
    cibc_parser = CibcParser()
    rbc_parser = RbcParser()
    rows: list[tuple[str, str, int, int, bool]] = []
    for bank, path in entries:
        parser = cibc_parser if bank == "CIBC" else rbc_parser
        stmt = cached_parse(path, parser)
        classified = classify(stmt.transactions, rules)
        n_uncategorized = sum(1 for c in classified if c.disposition is Disposition.UNCATEGORIZED)
        n_total = len(stmt.transactions)
        is_done = n_uncategorized == 0
        rows.append((Path(path).name, bank, n_total, n_uncategorized, is_done))
    return rows


def _run_list_picker(
    rows: list[tuple[str, str, int, int, bool]],
) -> int | None:
    """Interactive ↑/↓ picker for the statement list.

    Returns the 0-based index of the selected row, or None if the user quit.
    """
    cursor: list[int] = [0]  # mutable slot so closures can share it

    _FILE_W = 16
    _BANK_W = 6
    _TXN_W = 14
    _UNC_W = 15
    _DONE_W = 6

    def _header() -> StyleAndTextTuples:
        line = (
            f"  {'File':<{_FILE_W}}  {'Bank':<{_BANK_W}}  "
            f"{'Transactions':>{_TXN_W}}  {'Uncategorized':>{_UNC_W}}  {'Done':^{_DONE_W}}"
        )
        return [("class:header", line)]

    def _make_row_control(idx: int) -> FormattedTextControl:
        filename, bank, n_total, n_unc, is_done = rows[idx]
        done_char = "✓" if is_done else "✗"

        def get() -> StyleAndTextTuples:
            try:
                focused = get_app() is not None and cursor[0] == idx
            except Exception:
                focused = False
            style = "class:row-focused" if focused else "class:row"
            prefix = "> " if focused else "  "
            line = (
                f"{prefix}{filename:<{_FILE_W}}  {bank:<{_BANK_W}}  "
                f"{n_total:>{_TXN_W}}  {n_unc:>{_UNC_W}}  {done_char:^{_DONE_W}}"
            )
            return [(style, line)]

        return FormattedTextControl(get)

    def _footer() -> StyleAndTextTuples:
        total = len(rows)
        done_count = sum(1 for _, _, _, _, d in rows if d)
        remaining = total - done_count
        total_unc = sum(n for _, _, _, n, _ in rows)
        line = (
            f"  {total} statement(s) · {done_count} done · "
            f"{remaining} remaining ({total_unc} uncategorized transactions)"
        )
        return [("class:footer", line)]

    def _hint() -> StyleAndTextTuples:
        return [("class:hint", "  ↑/↓ navigate · Enter annotate · q/Esc quit")]

    kb = KeyBindings()

    @kb.add("up")
    def move_up(event: KeyPressEvent) -> None:
        cursor[0] = (cursor[0] - 1) % len(rows)
        event.app.invalidate()

    @kb.add("down")
    def move_down(event: KeyPressEvent) -> None:
        cursor[0] = (cursor[0] + 1) % len(rows)
        event.app.invalidate()

    @kb.add("enter")
    def select(event: KeyPressEvent) -> None:
        event.app.exit(result=cursor[0])

    @kb.add("q")
    @kb.add("c-c")
    @kb.add("escape")
    def quit_picker(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    layout = Layout(
        HSplit(
            [
                Window(content=FormattedTextControl(_header), height=1),
                Window(height=1),
                *[Window(content=_make_row_control(i), height=1) for i in range(len(rows))],
                Window(height=1),
                Window(content=FormattedTextControl(_footer), height=1),
                Window(content=FormattedTextControl(_hint), height=1),
            ]
        )
    )

    style = Style.from_dict(
        {
            "header": "bold underline",
            "row": "",
            "row-focused": "bold",
            "footer": "fg:ansibrightblack",
            "hint": "fg:ansigreen",
        }
    )

    app: Application[int | None] = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=False,
        mouse_support=False,
    )
    return app.run()


def run_annotate_list(
    rules_path: str = "classification.toml",
    statements_dir: str = "statements",
    cibc_paths: list[str] | None = None,
    rbc_paths: list[str] | None = None,
) -> int:
    """Entry point for `wally annotate list`. Returns process exit code.

    Presents an interactive ↑/↓ picker of all statements. Pressing Enter on a
    row launches `run_annotate` for that statement; pressing q/Escape/Ctrl+C exits.
    After annotating, the picker is re-shown so the user can annotate another file.
    """
    rp = Path(rules_path)

    entries: list[tuple[str, str]] = []  # (bank, path)
    if cibc_paths or rbc_paths:
        for p in cibc_paths or []:
            entries.append(("CIBC", p))
        for p in rbc_paths or []:
            entries.append(("RBC", p))
    else:
        base = Path(statements_dir)
        for p in find_all(base / "cibc"):
            entries.append(("CIBC", str(p)))
        for p in find_all(base / "rbc"):
            entries.append(("RBC", str(p)))

    if not entries:
        print("No statements found.")
        return 0

    while True:
        # Re-load rules each iteration so counts update after annotating
        no_rules = ClassificationRules(categories={}, exclusions={})
        rules = load_rules(rp) if rp.exists() else no_rules
        rows = _build_list_rows(entries, rules)

        choice = _run_list_picker(rows)
        if choice is None:
            return 0

        bank, path = entries[choice]
        if bank == "CIBC":
            run_annotate(cibc_paths=[path], rbc_paths=[], rules_path=rules_path)
        else:
            run_annotate(cibc_paths=[], rbc_paths=[path], rules_path=rules_path)


__all__ = [
    "_all_unique_with_category",
    "_append_rule",
    "_build_list_rows",
    "_default_pattern",
    "_delete_session",
    "_guess_category",
    "_load_session",
    "_save_session",
    "_unique_uncategorized",
    "run_annotate",
    "run_annotate_list",
]
