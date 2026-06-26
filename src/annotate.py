"""Rule-harvesting annotator for wally.

`wally annotate` finds UNCATEGORIZED transactions across parsed statements,
deduplicates by normalized description, and presents an all-at-once form where
the user can assign each unique merchant to a category. On Ctrl+D, patterns are
written to classification.toml as production config.

`wally annotate list` shows a summary table of every statement and how many
transactions remain uncategorized, without entering interactive mode.
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
from rich import box
from rich.console import Console
from rich.table import Table

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
    queue: list[Transaction],
    rules: ClassificationRules,
) -> dict[int, str] | None:
    """All-at-once assignment form.

    Returns {queue_index: category_name} for confirmed assignments, or None if aborted.
    Empty fields are silently skipped (merchant will reappear on next run).
    """
    category_names = sorted(rules.categories.keys())
    # Digit shortcuts: 1-9 then 0, mapped to first 10 sorted categories
    shortcuts: dict[str, str] = {
        str(_DIGIT_ORDER[i]): cat for i, cat in enumerate(category_names[:10])
    }
    completer = WordCompleter(category_names, ignore_case=True, sentence=True)

    buffers: list[Buffer] = []
    for i, txn in enumerate(queue):
        guess = _guess_category(normalize(txn.raw_description), rules)
        doc = Document(guess) if guess else Document()
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

    def get_status() -> StyleAndTextTuples:
        assigned = sum(1 for b in buffers if b.text.strip())
        msg = f"{assigned}/{len(queue)} assigned  ·  {_FORM_HINT}"
        return [("class:hint", msg)]

    legend_height = 2 if len(shortcuts) > 5 else 1

    layout = Layout(
        HSplit(
            [
                Window(
                    content=FormattedTextControl(
                        f"Assign categories — {len(queue)} uncategorized merchants"
                    ),
                    height=1,
                ),
                Window(content=FormattedTextControl(get_legend), height=legend_height),
                Window(height=1),
                *[make_row(buf, txn) for buf, txn in zip(buffers, queue, strict=True)],
                Window(height=1),
                Window(content=FormattedTextControl(get_status), height=1),
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
    if not rules.categories:
        _console.print(
            f"[yellow]No categories found in {rp}. "
            "Press [bold]n[/bold] to create categories as you go "
            "or [bold]m[/bold] for miscellaneous.[/yellow]"
        )
    classified = classify(transactions, rules)
    unique = _unique_uncategorized(classified)

    if not unique:
        print("All transactions are already categorized.")
        return 0

    assignments = _run_annotate_form(unique, rules)

    if assignments is None:
        _console.print("\nCancelled — no changes saved.")
        return 0

    if not assignments:
        _console.print("\nNo categories assigned.")
        return 0

    for idx, category in assignments.items():
        txn = unique[idx]
        pattern = _default_pattern(normalize(txn.raw_description))
        _append_rule(rp, category, pattern)

    count = len(assignments)
    _console.print(
        f"\n[bold]Done.[/bold] Wrote [green]{count}[/green] rule(s) to [bold]{rp}[/bold]."
    )
    return 0


def run_annotate_list(
    rules_path: str = "classification.toml",
    statements_dir: str = "statements",
    cibc_paths: list[str] | None = None,
    rbc_paths: list[str] | None = None,
) -> int:
    """Entry point for `wally annotate list`. Returns process exit code."""
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

    cibc_parser = CibcParser()
    rbc_parser = RbcParser()

    table = Table(box=box.SIMPLE_HEAD, show_footer=False)
    table.add_column("File")
    table.add_column("Bank")
    table.add_column("Transactions", justify="right")
    table.add_column("Uncategorized", justify="right")
    table.add_column("Done", justify="center")

    total_statements = 0
    done_count = 0
    total_uncategorized = 0

    for bank, path in entries:
        parser = cibc_parser if bank == "CIBC" else rbc_parser
        stmt = cached_parse(path, parser)
        classified = classify(stmt.transactions, rules)
        n_uncategorized = sum(1 for c in classified if c.disposition is Disposition.UNCATEGORIZED)
        n_total = len(stmt.transactions)
        is_done = n_uncategorized == 0
        done_label = "[green]✓[/green]" if is_done else "[yellow]✗[/yellow]"

        table.add_row(
            Path(path).name,
            bank,
            str(n_total),
            str(n_uncategorized),
            done_label,
        )

        total_statements += 1
        if is_done:
            done_count += 1
        total_uncategorized += n_uncategorized

    _console.print(table)
    remaining = total_statements - done_count
    _console.print(
        f"{total_statements} statement(s) · {done_count} done · "
        f"{remaining} remaining ({total_uncategorized} uncategorized transactions)"
    )
    return 0


__all__ = [
    "_append_rule",
    "_default_pattern",
    "_delete_session",
    "_guess_category",
    "_load_session",
    "_save_session",
    "_unique_uncategorized",
    "run_annotate",
    "run_annotate_list",
]
