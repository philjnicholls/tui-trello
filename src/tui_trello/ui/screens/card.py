"""Full-screen card detail. `h`, `q` or Esc go back."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static

from tui_trello.emoji import with_emoji
from tui_trello.models import Card
from tui_trello.ui.bidi import visual
from tui_trello.ui.screens.base import CardActionsScreen, TopBar
from tui_trello.ui.widgets.bell import Bell
from tui_trello.ui.widgets.card_view import CardView
from tui_trello.ui.widgets.news_badge import NewsBadge
from tui_trello.ui.widgets.spinner import Spinner


class CardScreen(CardActionsScreen):
    HELP_PLACE = "card"  # which keys `?` shows
    DEFAULT_CSS = """
    CardScreen CardView { padding: 1 4; }
    """

    BINDINGS = [Binding("escape,q,h,left", "app.pop_screen", "Back", id="card_screen.back")]

    FOCUS_WIDGETS = (CardView,)

    def __init__(self, card_id: str, comment_id: str = "") -> None:
        super().__init__()
        self.card_id = card_id
        self.comment_id = comment_id  # a comment to scroll to and mark, from a link to it

    def compose(self) -> ComposeResult:
        with TopBar():
            yield Static(id="location")
            yield Bell()
            yield NewsBadge()
            yield Spinner()
        yield CardView()
        yield Footer()

    def on_mount(self) -> None:
        store = self.app.store
        store.board_changed.subscribe(self, lambda _: self.redraw())
        store.work_changed.subscribe(self, lambda _: self.redraw())
        self.redraw()
        self.query_one(CardView).focus()

    def redraw(self) -> None:
        if context := self.app.store.context_for(self.card_id):
            card = context.card(self.card_id)
            self.query_one("#location", Static).update(visual(Text(with_emoji(context.location(card)), style="bold")))
            self.query_one(CardView).show(card, context, self.comment_id)

    def show_comment(self, comment_id: str) -> None:
        self.comment_id = comment_id
        self.query_one(CardView).show_comment(comment_id)

    def current_card(self) -> Card | None:
        return self.app.store.find_card(self.card_id)

    def card_gone(self, card: Card) -> None:
        """The card was archived or deleted: there is nothing left to show, so go back."""
        if card.id == self.card_id and self.app.screen is self:
            self.app.pop_screen()
