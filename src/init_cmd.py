"""Interactive wizard for `wally init` — scaffolds wally.toml.

Presents all categories in a compact navigable form (prompt_toolkit),
collects an optional monthly limit for each, and writes wally.toml.
Empty field = category ignored. 0 = tracked with no cap.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import FormattedTextControl, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.processors import Processor, Transformation, TransformationInput
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.prompt import Confirm, Prompt

# Ordered default categories. Key becomes the TOML key; label is displayed.
CATEGORIES: list[tuple[str, str]] = [
    ("Groceries", "Groceries"),
    ("Restaurants", "Restaurants"),
    ("Transportation", "Transportation"),
    ("Entertainment", "Entertainment"),
    ("Shopping", "Shopping"),
    ("Personal", "Personal"),
    ("Home & Garden", "Home & Garden"),
    ("Travel", "Travel"),
    ("Utilities", "Utilities"),
    ("Services", "Services"),
]

_HINT = "↑↓ navigate · empty to skip · Ctrl+D confirm · Ctrl+C cancel"
_INPUT_WIDTH = 12


class _ZeroPlaceholder(Processor):
    """Show a grey '0' when the buffer is empty (placeholder hint)."""

    def apply_transformation(self, transformation_input: TransformationInput) -> Transformation:
        if not transformation_input.buffer_control.buffer.text:
            return Transformation([("class:placeholder", "0")])
        return Transformation(transformation_input.fragments)


def _run_category_form() -> dict[str, Decimal] | None:
    """Compact inline form — returns key→Decimal for confirmed categories, or None on abort."""
    buffers = [Buffer(name=key, multiline=False) for key, _ in CATEGORIES]
    status: list[str] = [""]  # mutable slot shared across closures

    kb = KeyBindings()

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

    @kb.add("c-d")
    def confirm(event: KeyPressEvent) -> None:
        result: dict[str, Decimal] = {}
        first_bad: Buffer | None = None
        for buf, (key, label) in zip(buffers, CATEGORIES, strict=True):
            raw = buf.text.strip()
            if not raw:
                continue
            try:
                value = Decimal(raw.lstrip("$").replace(",", ""))
                if value < 0:
                    raise InvalidOperation
                result[key] = value
            except InvalidOperation:
                if first_bad is None:
                    first_bad = buf
                    status[0] = f"Invalid: {label} must be a number ≥ 0 or left empty"
        if first_bad is not None:
            event.app.layout.focus(first_bad)
            event.app.invalidate()
            return
        status[0] = ""
        event.app.exit(result=result)

    @kb.add("c-c")
    @kb.add("escape")
    def abort(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    def make_label(buf: Buffer, label: str) -> FormattedTextControl:
        def get() -> StyleAndTextTuples:
            try:
                focused = get_app().layout.current_buffer is buf
            except Exception:
                focused = False
            style = "class:label-focused" if focused else "class:label"
            return [(style, f"{label}: ")]

        return FormattedTextControl(get)

    def make_row(buf: Buffer, label: str) -> VSplit:
        return VSplit(
            [
                Window(content=FormattedTextControl("  "), width=2, height=1),
                Window(content=make_label(buf, label), dont_extend_width=True, height=1),
                Window(
                    content=BufferControl(
                        buffer=buf,
                        focusable=True,
                        input_processors=[_ZeroPlaceholder()],
                    ),
                    width=_INPUT_WIDTH,
                    height=1,
                ),
            ]
        )

    def get_total() -> StyleAndTextTuples:
        total = Decimal(0)
        for buf in buffers:
            raw = buf.text.strip()
            if raw:
                try:
                    val = Decimal(raw.lstrip("$").replace(",", ""))
                    if val >= 0:
                        total += val
                except InvalidOperation:
                    pass
        return [("class:total", f"Total Monthly Budget: ${total:,.2f}")]

    def get_status() -> StyleAndTextTuples:
        msg = status[0]
        return [("class:error" if msg else "class:hint", msg or _HINT)]

    layout = Layout(
        HSplit(
            [
                Window(content=FormattedTextControl("Configure your budget"), height=1),
                *[
                    make_row(buf, label)
                    for buf, (_, label) in zip(buffers, CATEGORIES, strict=True)
                ],
                Window(content=FormattedTextControl(get_total), height=1),
                Window(content=FormattedTextControl(get_status), height=1),
            ]
        ),
        focused_element=buffers[0],
    )
    style = Style.from_dict(
        {
            "placeholder": "fg:ansibrightblack",
            "label": "",
            "label-focused": "bold",
            "error": "fg:ansired bold",
            "hint": "fg:ansigreen",
            "total": "bold",
        }
    )
    app: Application[dict[str, Decimal] | None] = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=False,
        mouse_support=False,
    )
    return app.run()


def build_toml(limits: dict[str, Decimal], statements_dir: str = "statements") -> str:
    """Render wally.toml content from a key→Decimal mapping and a statements path."""
    lines = [
        "# Wally budget config — generated by `wally init`.",
        "# Amounts are quoted strings to preserve exact decimal values.",
        "",
        "[budget.limits]",
    ]
    for key, amount in limits.items():
        toml_key = f'"{key}"' if any(c in key for c in " &") else key
        lines.append(f'{toml_key} = "{amount:.2f}"')
    lines += [
        "",
        "[statements]",
        f'dir = "{statements_dir}"',
    ]
    return "\n".join(lines) + "\n"


def run_init(config_path: str, console: Console | None = None) -> int:
    """Run the interactive init wizard. Returns a process exit code."""
    if console is None:
        console = Console()

    path = Path(config_path)
    if path.exists():
        try:
            overwrite = Confirm.ask(
                f"[yellow]{path}[/yellow] already exists. Overwrite?", default=False
            )
        except KeyboardInterrupt:
            console.print("\nAborted.")
            return 1
        if not overwrite:
            console.print("Aborted — existing config unchanged.")
            return 1

    limits = _run_category_form()

    if limits is None:
        console.print("\nAborted.")
        return 1
    if not limits:
        console.print("[yellow]No limits set — nothing written.[/yellow]")
        return 1

    try:
        statements_dir = Prompt.ask("Statements directory", default="statements")
    except KeyboardInterrupt:
        console.print("\nAborted.")
        return 1

    path.write_text(build_toml(limits, statements_dir))
    console.print(f"\n[green]✓[/green] Written to [bold]{path}[/bold]\n")
    console.print("Run [bold]wally[/bold] to generate your first report.")
    return 0
