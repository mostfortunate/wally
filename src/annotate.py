"""Rule-harvesting annotator for wally.

`wally annotate` finds UNCATEGORIZED transactions across parsed statements, deduplicates
them by normalized description, and presents a keyboard-driven menu so the user can label
each unique merchant — writing patterns directly to classification.toml as production config.

`wally annotate list` shows an interactive picker of every statement. Navigate with ↑/↓ or
j/k, press Enter to annotate the selected statement, and press q or Escape to quit.
"""

from __future__ import annotations

import json
import re
import sys
import termios
import tomllib
import tty
from pathlib import Path

import tomli_w
from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, Window
from prompt_toolkit.styles import Style
from rich.console import Console

from src.classification import ClassificationRules, classify, load_rules, normalize
from src.ingestion.cache import cached_parse
from src.ingestion.discovery import find_all
from src.parsers.base import Classified, Disposition, Transaction
from src.parsers.cibc import CibcParser
from src.parsers.rbc import RbcParser

_console = Console()


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


def _build_menu(rules: ClassificationRules) -> dict[int, str]:
    """Build stable int->category mapping. Sorted alphabetically, keys 1-0 (10 slots)."""
    keys = list(range(1, 10)) + [0]  # 1-9 then 0 = 10 slots
    cats = sorted(rules.categories.keys())
    return {keys[i]: cat for i, cat in enumerate(cats) if i < len(keys)}


# ---------------------------------------------------------------------------
# Session file helpers
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
# Terminal I/O
# ---------------------------------------------------------------------------


def _read_key() -> str:
    """Read a single keypress from stdin in raw mode. Enter returns '\\r'."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def _format_direction(txn: Transaction) -> str:
    return txn.direction.name


def _format_bank_category(txn: Transaction) -> str:
    if txn.bank_category:
        return f"  CIBC: {txn.bank_category}"
    return ""


def _print_menu(menu: dict[int, str]) -> None:
    slots: list[str] = []
    for key in list(range(1, 10)) + [0]:
        if key in menu:
            slots.append(f"  [bold]{key}[/bold] {menu[key]}")
    _console.print("  " + "   ".join(slots))


def _prompt_loop(
    txn: Transaction,
    menu: dict[int, str],
    rules: ClassificationRules,
    done: int,
    total: int,
) -> str | None:
    """Interactively prompt for a category. Returns category string or None (skip)."""
    norm = normalize(txn.raw_description)
    guess = _guess_category(norm, rules)

    _console.print()
    _console.print(
        f"[bold][{done + 1}/{total}][/bold] {txn.raw_description:<40} "
        f"[green]${txn.amount}[/green]  {_format_direction(txn)}"
        f"{_format_bank_category(txn)}"
    )

    if guess:
        _console.print(f"  Guess: [bold cyan]↵ {guess}[/bold cyan]")
    else:
        _console.print("  Guess: [dim](none)[/dim]")

    _console.print()
    _print_menu(menu)
    _console.print()

    while True:
        _console.print("  [bold]>[/bold] ", end="")
        sys.stdout.flush()
        key = _read_key()

        # Ctrl-C
        if key == "\x03":
            raise KeyboardInterrupt

        # Enter — accept guess
        if key == "\r":
            if guess:
                _console.print(f"{guess}")
                return guess
            _console.print("[dim](no guess — skipped)[/dim]")
            return None

        # Digit keys
        if key.isdigit():
            digit = int(key)
            if digit in menu:
                _console.print(menu[digit])
                return menu[digit]
            _console.print(f"[yellow]No category at slot {key}[/yellow]")
            continue

        # n — new category
        if key == "n":
            _console.print()
            name = input("  New category name: ").strip().lower()
            if name:
                return name
            _console.print("[yellow]Empty name — skipped.[/yellow]")
            return None

        # s — skip
        if key == "s":
            _console.print("[dim]skipped[/dim]")
            return None

        # Unknown key
        _console.print(f"[dim](unknown key '{key}' — try 1-9, 0, n, s, or ↵)[/dim]")


def _print_summary(assigned: int, misc: int, skipped: int) -> None:
    _console.print()
    _console.print(
        f"[bold]Done.[/bold]  "
        f"assigned [green]{assigned}[/green]  "
        f"misc [yellow]{misc}[/yellow]  "
        f"skipped [dim]{skipped}[/dim]"
    )


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
    unique = _unique_uncategorized(classified)

    session_path = rp.with_name(rp.name + ".session.json")
    handled = _load_session(session_path)
    queue = [t for t in unique if normalize(t.raw_description) not in handled]

    total = len(unique)
    done = total - len(queue)

    if not queue:
        print(f"Nothing left to annotate ({total} merchants already labeled).")
        _delete_session(session_path)
        return 0

    menu = _build_menu(rules)
    misc_count = skip_count = assigned_count = 0

    try:
        for txn in queue:
            category = _prompt_loop(txn, menu, rules, done, total)
            if category is None:
                skip_count += 1
            else:
                category = category.strip().lower()
                pattern = _default_pattern(normalize(txn.raw_description))
                _append_rule(rp, category, pattern)
                rules = load_rules(rp)  # reload so autofill improves in-session
                menu = _build_menu(rules)  # rebuild menu if new category was added
                if category == "miscellaneous":
                    misc_count += 1
                else:
                    assigned_count += 1
            _save_session(session_path, normalize(txn.raw_description))
            done += 1
    except KeyboardInterrupt:
        print("\nInterrupted — progress saved.")

    _print_summary(assigned_count, misc_count, skip_count)
    if done >= total:
        _delete_session(session_path)
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
        return [("class:hint", "  ↑/↓ or j/k navigate · Enter annotate · q/Esc quit")]

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def move_up(event: KeyPressEvent) -> None:
        cursor[0] = (cursor[0] - 1) % len(rows)
        event.app.invalidate()

    @kb.add("down")
    @kb.add("j")
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
    rules = load_rules(rp) if rp.exists() else ClassificationRules(categories={}, exclusions={})

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
    "_append_rule",
    "_build_list_rows",
    "_build_menu",
    "_default_pattern",
    "_delete_session",
    "_guess_category",
    "_load_session",
    "_read_key",
    "_save_session",
    "_unique_uncategorized",
    "run_annotate",
    "run_annotate_list",
]
