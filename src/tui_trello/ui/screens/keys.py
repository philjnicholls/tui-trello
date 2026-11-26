"""`?`: the key reference, for the view it was opened from; `a` shows every key."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from tui_trello.ui import keymap

# Where a section or a key applies: the `HELP_PLACE` of the screens it works on; None for everywhere.
LISTS = {"browser", "triage", "mywork"}
CARDS = LISTS | {"card"}
PLACE_NAMES = {"browser": "the browser", "triage": "triage", "mywork": "my work", "notifications": "notifications",
               "card": "a card", "preview": "a link preview"}

# (section, where, keys); a key is (keys, what they do) or (keys, what they do, where). Keys are written as `{id}`
# placeholders, which `KeysScreen.table` fills with the key in use (see ui/keymap.py).
KEYS = [
    ("Move", None, [
        ("{app.down} {app.up}", "down, up"),
        ("{browser.out} {browser.in}", "back to the lists, into the cards; {browser.in} on a card opens it",
         {"browser"}),
        ("{list.open} / enter", "open the card", {"triage", "mywork"}),
        ("{card_screen.back:all}", "back", {"card"}),
        ("{chord.top} {app.bottom}", "first, last"),
        ("{app.half_down} {app.half_up}", "half a page down, up"),
    ]),
    ("Views", CARDS | {"notifications"}, [  # off under a link preview
        ("{app.browser} {app.triage} {app.mywork} {app.notifications}", "browser, triage, my work, notifications"),
        ("{chord.next_view} {chord.previous_view}", "next, previous view"),
        ("{app.boards}", "pick a board"),
        ("{app.commands}", "command palette: jump to any board or card"),
        ("{app.search}", "search every board on Trello, archived cards too; enter opens, {popup.preview} previews"),
        ("{list.filter}", "filter the cards on screen: words  #label  @member  list:name  !overdue  !due  "
                          "({list.clear_filter} clears)", LISTS),
        ("{triage.sort}", "cycle sort: list, due date, last activity", {"triage"}),
        ("{mywork.preview}", "show or hide the preview", {"mywork"}),
        ("{app.refresh}", "reload"),
        ("{app.news}", "news about tui-trello (shown when there is some you haven't seen)"),
    ]),
    ("Cards", CARDS, [
        ("{list.new_card}", "new card: on the highlighted list (in triage and my work, pick the list first); the "
                            "first line is its name, the lines after it its description", LISTS),
        ("{card.move}", "move to another list"),
        ("{card.comment}", "comment: {editor.enter} sends, {editor.newline} new line, @ mentions someone "
                           "({editor.mention} or {editor.enter} picks)"),
        ("", "in a comment or description, {editor.attach} attaches a file and puts its link in"),
        ("{card.description}", "edit the description: {editor.enter} new line, {editor.save} saves"),
        ("", "{editor.cancel} closes either and keeps what you wrote as a draft; empty the box to drop it"),
        ("{card.labels}", "labels: enter puts one on or takes it off; type a new name to create one"),
        ("{card.members}", "members: enter puts a board member on the card or takes them off"),
        ("{card.join} {card.watch}", "join the card or leave it; watch it or stop watching (👀 marks a watched card)"),
        ("{card.checklist}", "checklist: enter ticks or unticks an item; type new text to add an item or a "
                             "checklist"),
        ("{app.done_items}", "show or hide the ticked items of every checklist (hidden at first; remembered)",
         {"browser", "mywork", "card"}),
        ("{card.attachments}", "attachments: enter opens one in the browser, where you can save a file "
                               "({attachments.save} reminds you), {popup.copy_link} copies its link; attach a file, "
                               "or paste a URL to attach a link"),
        ("{card.reply}", "reply to a comment: it starts with a quote of it and @mentions its author; for a long "
                         "one, pick what to quote"),
        ("{card.react}", "react to a comment: pick it, then an emoji; enter on one you gave takes it off"),
        ("{card.edit_comment}", "edit one of your comments: pick it, change the text, save"),
        ("{card.delete_comment}", "delete one of your comments (asks first)"),
        ("{card.archive}", "archive the card (asks first); {app.search} still finds it, and trello.com can "
                           "restore it"),
        ("{card.delete}", "delete the card for good (asks first)"),
        ("{card.copy_link} {card.copy_comment_link}", "copy the link to the card, to one of its comments"),
        ("{card.open}", "open in the web browser"),
        ("{card.follow_link}", ("follow a link on the card: Trello cards, comments, boards and attachments open "
                                "here, the rest in the web browser; {popup.preview} in the list previews a card, "
                                "comment or attachment in a popup (esc comes back), {popup.open_in_browser} opens "
                                "one in the browser, {popup.copy_link} copies it")),
        ("click", "on a link: a card, comment or attachment opens its preview; enter there follows it; a board or "
                  "web link is followed", CARDS),
        ("{card.copy_link} {card.open}", "on the lists column, copy or open the board's link (a list has no link "
                                         "of its own)", {"browser"}),
        ("{board.copy_link}", "copy the link to the board", {"browser", "triage"}),
    ]),
    ("Notifications", {"notifications"}, [
        ("enter / {list.open}", "open the card and mark its notifications read"),
        ("{notifications.mark_read}", "mark read"),
        ("{notifications.mark_all_read}", "mark all read"),
        ("{notifications.toggle_read}", "hide / show the ones you've read (hidden at first; remembered)"),
        ("{card.reply}", "reply to the comment: it starts with a quote of it and @mentions its author"),
    ]),
    ("Link preview", {"preview"}, [
        ("{preview.close:all}", "close it: everything under it is as it was"),
        ("{preview.follow}", "follow the link"),
        ("{popup.open_in_browser} {popup.copy_link}", "open the link in the web browser, copy it"),
        ("{app.done_items}", "show or hide the ticked items of every checklist"),
        ("{app.down} {app.up}", "scroll; a click on a link in it previews that on top"),
    ]),
    ("Pickers", CARDS | {"notifications"}, [  # where pickers open; none do under a link preview
        ("type", "filter"),
        ("{picker.down} {picker.up}", "down, up"),
        ("enter {picker.close}", "choose, cancel"),
    ]),
    ("", None, [
        ("{app.help}", "close this"),
        ("{app.quit}", "quit (back, on a card)", CARDS | {"notifications"}),
        ("", "change any key in config.toml's [keys]: `tui-trello keys` lists them"),
    ]),
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
        Binding("escape,q", "dismiss", "Close", id="help.close"),
        Binding("question_mark", "dismiss", "Close", show=False, id="app.help"),
        Binding("a", "toggle_all", "All keys", id="help.all"),
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
        keys_in_use = keymap.of(self.app)
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column()
        if self.place:
            heading = "Every key" if self.show_all else f"Keys in {PLACE_NAMES.get(self.place, self.place)}"
            other = keys_in_use.fill("{help.all}: just this view's" if self.show_all else "{help.all}: every key")
            table.add_row("", Text.assemble((heading, "bold"), ("   " + other, "dim")))
            table.add_row("", "")
        for section, keys in keys_for(None if self.show_all else self.place):
            if section:
                table.add_row("", Text(section.upper(), style="bold"))
            for key, does in keys:
                table.add_row(Text(keys_in_use.fill(key), style="bold yellow"), Text(keys_in_use.fill(does)))
            table.add_row("", "")
        return table

    def action_toggle_all(self) -> None:
        if self.place:
            self.show_all = not self.show_all
            self.query_one("#keys", Static).update(self.table())
