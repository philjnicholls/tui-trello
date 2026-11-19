"""`?`: the key reference."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

KEYS = [
    ("Move", [
        ("j k", "down, up"),
        ("h l", "out, in: back to the lists / open a column or card / back from a card"),
        ("gg G", "first, last"),
        ("ctrl+d ctrl+u", "half a page down, up"),
    ]),
    ("Views", [
        ("1 2 3 4", "browser, triage, my work, notifications"),
        ("gt gT", "next, previous view"),
        ("b", "pick a board"),
        (":", "command palette: jump to any board or card"),
        ("/", "filter: words  #label  @member  list:name  !overdue  !due  (esc clears)"),
        ("s", "triage: cycle sort"),
        ("p", "my work: toggle preview"),
        ("r", "reload"),
    ]),
    ("Cards", [
        ("enter / l", "open"),
        ("m", "move to another list"),
        ("c", "comment: enter sends, alt+enter new line, @ mentions someone (tab or enter picks)"),
        ("e", "edit the description: enter new line, ctrl+s saves"),
        ("", "esc closes either and keeps what you wrote as a draft; empty the box to drop it"),
        ("t", "labels: enter puts one on or takes it off; type a new name to create one"),
        ("x", "checklist: enter ticks or unticks an item; type new text to add an item or a checklist"),
        ("R", "react to a comment: pick it, then an emoji; enter on one you gave takes it off"),
        ("y Y", "copy the link to the card, to one of its comments"),
        ("o", "open in the web browser"),
    ]),
    ("Notifications", [
        ("enter / l", "open the card and mark its notifications read"),
        ("d", "mark read"),
        ("D", "mark all read"),
        ("u", "unread only / all"),
    ]),
    ("Pickers", [
        ("type", "filter"),
        ("ctrl+j ctrl+k", "down, up"),
        ("enter esc", "choose, cancel"),
    ]),
    ("", [("?", "close this"), ("q", "quit (back, on a card)")]),
]


class KeysScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    KeysScreen { align: center middle; }
    KeysScreen > VerticalScroll {
        width: 84; max-width: 95%; height: auto; max-height: 90%; border: round $accent; background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column()
        for section, keys in KEYS:
            if section:
                table.add_row("", Text(section.upper(), style="bold"))
            for key, does in keys:
                table.add_row(Text(key, style="bold yellow"), does)
            table.add_row("", "")
        with VerticalScroll():
            yield Static(table)
