"""Terminal budget report renderer using rich for colour and alignment."""

from __future__ import annotations

import io
from decimal import Decimal

from rich import box
from rich.console import Console
from rich.table import Table

from src.budget import CategoryReport, Status
from src.parsers.base import Classified, Direction, Disposition

ZERO = Decimal("0")

_STATUS_LABEL = {
    Status.WITHIN: "✓ WITHIN",
    Status.UNDER: "↓ UNDER",
    Status.OVER: "↑ OVER",
}
_STATUS_STYLE = {
    Status.WITHIN: "green",
    Status.UNDER: "yellow",
    Status.OVER: "bold red",
}


def render(
    reports: list[CategoryReport],
    classified: list[Classified],
    console: Console | None = None,
) -> None:
    """Print the Wally Summary table and any uncategorized warning to stdout."""
    if console is None:
        console = Console()
    _render_table(reports, console)
    _render_uncategorized_warning(classified, console)


def render_to_str(
    reports: list[CategoryReport],
    classified: list[Classified],
) -> str:
    """Render to a plain string (no colour). Used by tests."""
    buf = io.StringIO()
    render(reports, classified, console=Console(file=buf, no_color=True, highlight=False))
    return buf.getvalue()


def _pct(spent: Decimal, limit: Decimal | None) -> str:
    if limit is None or limit == ZERO:
        return "-"
    return f"{int(spent / limit * 100)}%"


def _render_table(reports: list[CategoryReport], console: Console) -> None:
    if not reports:
        return

    table = Table(
        title="[bold]Wally Summary[/bold]",
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold",
        title_justify="left",
        pad_edge=False,
    )
    table.add_column("CATEGORY", style="bold")
    table.add_column("SPENT", justify="right")
    table.add_column("LIMIT", justify="right")
    table.add_column("USED", justify="right")
    table.add_column("STATUS")

    for r in sorted(reports, key=lambda r: r.category):
        status_label = _STATUS_LABEL.get(r.status, "-") if r.status is not None else "-"
        status_style = _STATUS_STYLE.get(r.status, "dim") if r.status is not None else "dim"
        spent_str = f"${r.spent:,.2f}"
        # Colour the spent amount red when over budget so the problem stands out.
        if r.status is Status.OVER:
            spent_str = f"[bold red]{spent_str}[/bold red]"
        table.add_row(
            r.category.upper(),
            spent_str,
            f"${r.limit:,.2f}" if r.limit is not None else "-",
            _pct(r.spent, r.limit),
            f"[{status_style}]{status_label}[/{status_style}]",
        )

    console.print()
    console.print(table)


def _render_uncategorized_warning(classified: list[Classified], console: Console) -> None:
    uncategorized = [c for c in classified if c.disposition is Disposition.UNCATEGORIZED]
    if not uncategorized:
        return

    withdrawals = sum(
        (c.txn.amount for c in uncategorized if c.txn.direction is Direction.WITHDRAWAL), ZERO
    )
    deposits = sum(
        (c.txn.amount for c in uncategorized if c.txn.direction is Direction.DEPOSIT), ZERO
    )
    count = len(uncategorized)

    parts = [f"${withdrawals:,.2f} in withdrawals"]
    if deposits:
        parts.append(f"${deposits:,.2f} in deposits")

    console.print(
        f"[yellow]⚠  {count} uncategorized transaction(s) — {', '.join(parts)}[/yellow]"
    )
    console.print()


__all__ = ["render", "render_to_str"]
