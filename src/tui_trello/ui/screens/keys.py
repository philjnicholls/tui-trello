"""`?`: the key reference, for the view it was opened from; `a` shows every key."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

# Where a section or a key applies: the `HELP_PLACE` of the screens it works on; None for everywhere.
LISTS = {"browser", "triage", "mywork"}
CARDS = LISTS | {"card"}
PLACE_NAMES = {"browser": "the browser", "triage": "triage", "mywork": "my work", "notifications": "notifications",
               "card": "a card"}

# (section, where, keys); a key is (keys, what they do) or (keys, what they do, where).
KEYS = [
    ("Move", None, [
        ("j k", "down, up"),
        ("h l", "back to the lists, into the cards; l on a card opens it", {"browser"}),
        ("l / enter", "open the card", {"triage", "mywork"}),
        ("h / esc / q", "back", {"card"}),
        ("gg G", "first, last"),
        ("ctrl+d ctrl+u", "half a page down, up"),
    ]),
    ("Views", None, [
        ("1 2 3 4", "browser, triage, my work, notifications"),
        ("gt gT", "next, previous view"),
        ("b", "pick a board"),
        (":", "command palette: jump to any board or card"),
        ("/", "filter: words  #label  @member  list:name  !overdue  !due  (esc clears)", LISTS),
        ("s", "cycle sort: list, due date, last activity", {"triage"}),
        ("p", "show or hide the preview", {"mywork"}),
        ("r", "reload"),
    ]),
    ("Cards", CARDS, [
        ("m", "move to another list"),
        ("c", "comment: enter sends, alt+enter new line, @ mentions someone (tab or enter picks)"),
        ("", "in a comment or description, ctrl+o attaches a file and puts its link in"),
        ("e", "edit the description: enter new line, ctrl+s saves"),
        ("", "esc closes either and keeps what you wrote as a draft; empty the box to drop it"),
        ("t", "labels: enter puts one on or takes it off; type a new name to create one"),
        ("x", "checklist: enter ticks or unticks an item; type new text to add an item or a checklist"),
        ("a", "attachments: enter opens one in the browser, ctrl+s saves it to Downloads, ctrl+y copies its link; "
              "attach a file, or paste a URL to attach a link"),
        ("C", "reply to a comment: it starts with a quote of it and @mentions its author; for a long one, pick what "
              "to quote"),
        ("R", "react to a comment: pick it, then an emoji; enter on one you gave takes it off"),
        ("y Y", "copy the link to the card, to one of its comments"),
        ("o", "open in the web browser"),
    ]),
    ("Notifications", {"notifications"}, [
        ("enter / l", "open the card and mark its notifications read"),
        ("d", "mark read"),
        ("D", "mark all read"),
        ("u", "hide / show the ones you've read (hidden at first; remembered)"),
        ("C", "reply to the comment: it starts with a quote of it and @mentions its author"),
    ]),
    ("Pickers", None, [
        ("type", "filter"),
        ("ctrl+j ctrl+k", "down, up"),
        ("enter esc", "choose, cancel"),
    ]),
    ("", None, [("?", "close this"), ("q", "quit (back, on a card)")]),
]


def keys_for(place: str | None) -> list[tuple[str, list[tuple[str, str]]]]:
    """The sections and keys that work in `place`, or every one for None."""
    sections = []
    for section, where, keys in KEYS:
        if place and where and place not in where:
            continue
        shown = [(key, does) for key, does, *only in keys if not (place and only and place not in only[0])]
        if shown:
            sections.append((section, shown))
    return sections


class KeysScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    KeysScreen { align: center middle; }
    KeysScreen > VerticalScroll {
        width: 84; max-width: 95%; height: auto; max-height: 90%; border: round $accent; background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape,question_mark,q", "dismiss", "Close"),
        Binding("a", "toggle_all", "All keys"),
    ]

    def __init__(self, place: str | None = None) -> None:
        """`place` is the screen's `HELP_PLACE`: only the keys that work there are shown, until `a`."""
        super().__init__()
        self.place = place
        self.show_all = place is None

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self.table(), id="keys")

    def table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column()
        if self.place:
            heading = "Every key" if self.show_all else f"Keys in {PLACE_NAMES.get(self.place, self.place)}"
            other = "a: just this view's" if self.show_all else "a: every key"
            table.add_row("", Text.assemble((heading, "bold"), ("   " + other, "dim")))
            table.add_row("", "")
        for section, keys in keys_for(None if self.show_all else self.place):
            if section:
                table.add_row("", Text(section.upper(), style="bold"))
            for key, does in keys:
                table.add_row(Text(key, style="bold yellow"), does)
            table.add_row("", "")
        return table

    def action_toggle_all(self) -> None:
        if self.place:
            self.show_all = not self.show_all
            self.query_one("#keys", Static).update(self.table())
