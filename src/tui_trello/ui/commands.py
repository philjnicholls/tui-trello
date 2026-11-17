"""Command palette (ctrl+p) providers: jump to a board or to a card on the open board."""

from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider

from tui_trello.backend import BackendError
from tui_trello.ui.bidi import has_rtl, visual


def display(matcher, text: str):
    """Highlight the match, unless the text is RTL: highlights are in logical order, so show it reordered."""
    return visual(text) if has_rtl(text) else matcher.highlight(text)


class BoardCommands(Provider):
    async def startup(self) -> None:
        try:
            self.boards = await self.app.store.boards()
        except BackendError:
            self.boards = []

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for board in self.boards:
            text = f"Board: {board.name}"
            if (score := matcher.match(text)) > 0:
                yield Hit(score, display(matcher, text), partial(self.app.open_board, board.id), text=text,
                          help="Open board")

    async def discover(self) -> Hits:
        for board in self.boards:
            yield DiscoveryHit(visual(f"Board: {board.name}"), partial(self.app.open_board, board.id),
                               text=f"Board: {board.name}", help="Open board")


class CardCommands(Provider):
    async def search(self, query: str) -> Hits:
        snapshot = self.app.store.snapshot
        if not snapshot:
            return
        matcher = self.matcher(query)
        for card in snapshot.cards:
            text = f"Card: {card.name}"
            if (score := matcher.match(text)) > 0:
                yield Hit(score, display(matcher, text), partial(self.app.open_card, card.id), text=text,
                          help=visual(snapshot.list_named(card.list_id)).plain)
