"""Miller-column browser: lists │ cards │ preview. `l` goes into a column, `h` backs out."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from tui_trello.models import Card
from tui_trello.ui import render
from tui_trello.ui.bidi import visual
from tui_trello.ui.screens.base import FILTER_HELP, BoardScreen, TopBar
from tui_trello.ui.widgets.card_view import CardView
from tui_trello.ui.widgets.bell import Bell
from tui_trello.ui.widgets.spinner import Spinner


class BrowserScreen(BoardScreen):
    HELP_PLACE = "browser"  # which keys `?` shows
    AUTO_FOCUS = "#lists"

    DEFAULT_CSS = """
    BrowserScreen OptionList, BrowserScreen OptionList:focus {
        height: 1fr; border: none; padding: 0 1; margin-right: 1; background: $surface;
    }
    BrowserScreen OptionList:focus { background: $boost; }
    BrowserScreen OptionList > .option-list--option-highlighted { background: $panel-lighten-1; }
    BrowserScreen OptionList:focus > .option-list--option-highlighted { background: $accent 40%; }
    BrowserScreen #lists { width: 24; }
    BrowserScreen #cards { width: 1fr; }
    BrowserScreen #preview { width: 1fr; background: $surface; scrollbar-size-vertical: 1; }
    """

    BINDINGS = [
        Binding("l,right", "drill", "In", show=False),
        Binding("h,left", "back_out", "Out", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.list_id: str | None = None
        self.cards: list[Card] = []

    def compose(self) -> ComposeResult:
        with TopBar():
            yield Static(id="crumbs")
            yield Bell()
            yield Spinner()
        yield Input(id="filter", placeholder=FILTER_HELP)
        with Horizontal(id="body"):
            yield OptionList(id="lists")
            yield OptionList(id="cards")
            yield CardView(id="preview")
        yield Footer()

    # -- drawing --------------------------------------------------------------------------------------------------

    def redraw(self) -> None:
        if not (snapshot := self.snapshot):
            return
        lists = self.query_one("#lists", OptionList)
        unread = self.app.store.unread_by_card()
        lists.set_options(
            Option(Text.assemble(visual(lst.name), (f"  {self.count(lst.id)}", "dim"), "  ",
                                 render.unread_badge(sum(unread[c.id] for c in self.matching(lst.id)))), id=lst.id)
            for lst in snapshot.lists
        )
        ids = [lst.id for lst in snapshot.lists]
        if ids:
            lists.highlighted = ids.index(self.list_id) if self.list_id in ids else 0
        self.show_list()

    def count(self, list_id: str) -> int:
        return len(self.matching(list_id))

    def matching(self, list_id: str) -> list[Card]:
        """The list's cards that the filter lets through."""
        snapshot, query = self.snapshot, self.card_query
        return [card for card in snapshot.cards_in(list_id) if query.matches(card, snapshot)] if snapshot else []

    def show_list(self) -> None:
        if not (snapshot := self.snapshot):
            return
        option = self.query_one("#lists", OptionList).highlighted_option
        self.list_id = option.id if option else None
        previous = self.current_card()
        self.cards = self.matching(self.list_id) if self.list_id else []
        unread = self.app.store.unread_by_card()
        cards = self.query_one("#cards", OptionList)
        cards.set_options(Option(render.card_block(card, snapshot, unread=unread[card.id]), id=card.id)
                          for card in self.cards)
        if self.cards:
            ids = [c.id for c in self.cards]
            cards.highlighted = ids.index(previous.id) if previous and previous.id in ids else 0
        self.update_crumbs()
        self.query_one(CardView).show(self.current_card(), snapshot)

    def update_crumbs(self) -> None:
        if snapshot := self.snapshot:
            card = self.current_card()
            parts = [snapshot.board.name, snapshot.list_named(self.list_id) if self.list_id else ""]
            if card and self.query_one("#cards", OptionList).has_focus:
                parts.append(card.name)
            crumbs = Text(" › ", style="bold").join(visual(Text(p, style="bold")) for p in parts if p)
            if self.query_text:
                crumbs.append(f"   filter: {self.query_text}", style="yellow")
            self.query_one("#crumbs", Static).update(crumbs)

    # -- events ---------------------------------------------------------------------------------------------------

    @on(OptionList.OptionHighlighted, "#lists")
    def on_list_highlighted(self) -> None:
        self.show_list()

    @on(OptionList.OptionHighlighted, "#cards")
    def on_card_highlighted(self) -> None:
        if self.snapshot:
            self.update_crumbs()
            self.query_one(CardView).show(self.current_card(), self.snapshot)

    @on(OptionList.OptionSelected, "#lists")
    @on(OptionList.OptionSelected, "#cards")
    def on_selected(self) -> None:
        self.action_drill()

    def on_descendant_focus(self) -> None:
        self.update_crumbs()

    # -- actions --------------------------------------------------------------------------------------------------

    def current_card(self) -> Card | None:
        highlighted = self.query_one("#cards", OptionList).highlighted
        return self.cards[highlighted] if highlighted is not None and highlighted < len(self.cards) else None

    def focus_list(self) -> None:
        self.query_one("#cards" if self.cards else "#lists", OptionList).focus()

    def action_drill(self) -> None:
        if self.query_one("#lists", OptionList).has_focus:
            if self.cards:
                self.query_one("#cards", OptionList).focus()
        elif self.query_one("#cards", OptionList).has_focus:
            self.open_card()

    def action_back_out(self) -> None:
        self.query_one("#lists", OptionList).focus()
