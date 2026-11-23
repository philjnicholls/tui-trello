"""Command palette (ctrl+p) providers: jump to a board or to a card on the open board."""

from __future__ import annotations

from functools import partial

from textual.command import DiscoveryHit, Hit, Hits, Provider

from tui_trello.backend import BackendError
from tui_trello.emoji import with_emoji
from tui_trello.models import Board
from tui_trello.ui.bidi import has_rtl, visual


def display(matcher, text: str):
    """Highlight the match, unless the text is RTL: highlights are in logical order, so show it reordered."""
    return visual(text) if has_rtl(text) else matcher.highlight(text)


def match_score(matcher, shown: str, stored: str = "") -> float:
    """How well the query matches the text as shown or, if that differs (`:tada:` as 🎉), as stored."""
    result = matcher.match(shown)
    return result if not stored or shown == stored else max(result, matcher.match(stored))


class BoardCommands(Provider):
    async def startup(self) -> None:
        try:
            self.boards = await self.app.store.boards()
        except BackendError:
            self.boards = []

    @staticmethod
    def board_text(board: Board) -> str:
        return f"Board: {with_emoji(board.name)}"

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for board in self.boards:
            text = self.board_text(board)
            if (score := match_score(matcher, text, f"Board: {board.name}")) > 0:
                yield Hit(score, display(matcher, text), partial(self.app.open_board, board.id), text=text,
                          help="Open board")

    async def discover(self) -> Hits:
        for board in self.boards:
            text = self.board_text(board)
            yield DiscoveryHit(visual(text), partial(self.app.open_board, board.id), text=text, help="Open board")


class CardCommands(Provider):
    async def search(self, query: str) -> Hits:
        snapshot = self.app.store.snapshot
        if not snapshot:
            return
        matcher = self.matcher(query)
        for card in snapshot.cards:
            text = f"Card: {with_emoji(card.name)}"
            if (score := match_score(matcher, text, f"Card: {card.name}")) > 0:
                yield Hit(score, display(matcher, text), partial(self.app.open_card, card.id), text=text,
                          help=visual(with_emoji(snapshot.list_named(card.list_id))).plain)
