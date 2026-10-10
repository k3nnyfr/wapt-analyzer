"""Interactive checklist in the terminal, with a filter typed on the keyboard."""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import BufferControl, Dimension, FormattedTextControl, HSplit, Layout, Window
from prompt_toolkit.styles import Style

HELP = "↑↓ déplacer · Espace cocher · Ctrl+A tout · Ctrl+D rien · Entrée valider · Échap annuler"

STYLE = Style.from_dict({
    "title": "bold",
    "cursor": "reverse",
    "selected": "ansigreen",
    "disabled": "ansibrightblack",
    "detail": "ansibrightblack",
    "help": "ansibrightblack",
    "prompt": "bold",
})


@dataclass
class Choice:
    value: object
    label: str
    columns: tuple[str, ...] = ()   # details, aligned in columns
    selected: bool = False
    disabled: str = ""        # reason why the entry cannot be selected

    def matches(self, words: list[str]) -> bool:
        text = " ".join((self.label, *self.columns)).lower()
        return all(w in text for w in words)


def pick(choices: list[Choice], title: str, max_rows: int = 20, input=None, output=None) -> list | None:  # noqa: A002
    """Let the user check entries; returns the selected values, or None if cancelled."""
    query = Buffer(multiline=False)
    state = {"cursor": 0}
    width = min(max((len(c.label) for c in choices), default=0), 50)
    n_cols = max((len(c.columns) for c in choices), default=0)
    widths = [min(max((len(c.columns[i]) for c in choices if len(c.columns) > i), default=0), 40)
              for i in range(n_cols)]

    def visible() -> list[Choice]:
        words = query.text.lower().split()
        return [c for c in choices if c.matches(words)]

    def clamp() -> None:
        state["cursor"] = max(0, min(state["cursor"], len(visible()) - 1))

    query.on_text_changed += lambda _: clamp()

    def list_text():
        lines = []
        rows = visible()
        for i, c in enumerate(rows):
            mark = "[-]" if c.disabled else "[x]" if c.selected else "[ ]"
            style = "class:disabled" if c.disabled else "class:selected" if c.selected else ""
            if i == state["cursor"]:
                style += " class:cursor"
            cols = "  ".join(f"{col:<{w}}" for col, w in zip(c.columns, widths, strict=False)).rstrip()
            detail = f"  {cols}" + (f"  ({c.disabled})" if c.disabled else "")
            lines.append((style, f" {mark} {c.label:<{width}}"))
            lines.append((style + " class:detail", detail))
            lines.append(("", "\n"))
        if not rows:
            lines.append(("class:disabled", " (aucun paquet ne correspond au filtre)"))
        return lines

    def status_text():
        rows = visible()
        current = rows[state["cursor"]] if rows else None
        if current is not None and current.disabled:
            return [("class:disabled", f" {current.label} : {current.disabled}")]
        n = sum(c.selected for c in choices)
        return [("class:help", f" {n} sélectionné(s) sur {len(choices)} · {HELP}")]

    kb = KeyBindings()

    def move(delta: int) -> None:
        state["cursor"] += delta
        clamp()

    kb.add("up")(lambda e: move(-1))
    kb.add("down")(lambda e: move(1))
    kb.add("pageup")(lambda e: move(-max_rows))
    kb.add("pagedown")(lambda e: move(max_rows))

    @kb.add("space")
    def _toggle(event):
        rows = visible()
        if rows and not rows[state["cursor"]].disabled:
            rows[state["cursor"]].selected = not rows[state["cursor"]].selected

    def set_visible(value: bool) -> None:
        for c in visible():
            if not c.disabled:
                c.selected = value

    kb.add("c-a")(lambda e: set_visible(True))
    kb.add("c-d")(lambda e: set_visible(False))
    kb.add("enter")(lambda e: e.app.exit(result=[c.value for c in choices if c.selected]))
    kb.add("escape", eager=True)(lambda e: e.app.exit(result=None))
    kb.add("c-c")(lambda e: e.app.exit(result=None))

    layout = Layout(HSplit([
        Window(FormattedTextControl([("class:title", title)]), height=1),
        Window(BufferControl(query), height=1, get_line_prefix=lambda *_: [("class:prompt", "Filtre : ")]),
        Window(FormattedTextControl(list_text, get_cursor_position=lambda: Point(0, state["cursor"])),
               height=Dimension(min=1, max=max_rows, preferred=max_rows)),
        Window(FormattedTextControl(status_text), height=1),
    ]))
    app = Application(layout=layout, key_bindings=kb, style=STYLE, full_screen=False, erase_when_done=True,
                      input=input, output=output)
    layout.focus(query)
    return app.run()
