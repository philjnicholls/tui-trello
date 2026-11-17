"""App-wide state: the backend, the open board, the user's cross-board work, and signals fired when they change.

Screens read from the store and subscribe to its signals; mutations go through the store so every screen (including
ones further down the stack, or in another mode) redraws from the same data.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

from textual.dom import DOMNode
from textual.signal import Signal

from tui_trello.backend import Backend
from tui_trello.models import (
    Board,
    BoardSnapshot,
    Card,
    CardContext,
    Comment,
    Label,
    Member,
    WorkSnapshot,
)

# Trello's label colours, in the order new labels take them.
LABEL_COLOURS = ("green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "black")


class Store:
    def __init__(self, owner: DOMNode, backend: Backend) -> None:
        self.backend = backend
        self.snapshot: BoardSnapshot | None = None
        self.work: WorkSnapshot | None = None
        self.board_changed: Signal[BoardSnapshot] = Signal(owner, "board_changed")
        self.work_changed: Signal[WorkSnapshot] = Signal(owner, "work_changed")
        # What is being fetched or saved right now ("board", "work", "boards", "comments", "save"), for spinners.
        self.busy: dict[str, int] = {}
        self.busy_changed: Signal[Store] = Signal(owner, "busy_changed")
        self._boards: list[Board] | None = None
        self._comments: dict[str, list[Comment]] = {}
        self._labels: dict[str, list[Label]] = {}  # by board, for boards other than the open one
        self._members: dict[str, list[Member]] = {}  # likewise

    def is_busy(self, *what: str) -> bool:
        return any(self.busy.get(name) for name in what) if what else bool(self.busy)

    @asynccontextmanager
    async def _busy(self, what: str) -> AsyncIterator[None]:
        self.busy[what] = self.busy.get(what, 0) + 1
        self.busy_changed.publish(self)
        try:
            yield
        finally:
            self.busy[what] -= 1
            if not self.busy[what]:
                del self.busy[what]
            self.busy_changed.publish(self)

    async def boards(self, refresh: bool = False) -> list[Board]:
        if self._boards is None or refresh:
            async with self._busy("boards"):
                self._boards = await self.backend.boards()
        return self._boards

    async def open_board(self, board_id: str) -> BoardSnapshot:
        async with self._busy("board"):
            self.snapshot = await self.backend.board_snapshot(board_id)
        self._comments.clear()
        self.board_changed.publish(self.snapshot)
        return self.snapshot

    async def load_work(self) -> WorkSnapshot:
        async with self._busy("work"):
            self.work = await self.backend.my_work()
        self.work_changed.publish(self.work)
        return self.work

    def contexts(self) -> list[CardContext]:
        return [context for context in (self.snapshot, self.work) if context is not None]

    def context_for(self, card_id: str) -> CardContext | None:
        """The loaded snapshot that has this card, preferring the open board (it knows every member)."""
        return next((context for context in self.contexts() if context.card(card_id)), None)

    def find_card(self, card_id: str) -> Card | None:
        context = self.context_for(card_id)
        return context.card(card_id) if context else None

    async def comments(self, card_id: str, refresh: bool = False) -> list[Comment]:
        if card_id not in self._comments or refresh:
            async with self._busy("comments"):
                self._comments[card_id] = await self.backend.comments(card_id)
        return self._comments[card_id]

    async def move_card(self, card: Card, list_id: str) -> Card:
        async with self._busy("save"):
            moved = await self.backend.move_card(card, list_id)
        self._replace(moved)
        return moved

    async def add_comment(self, card_id: str, text: str) -> Comment:
        async with self._busy("save"):
            comment = await self.backend.add_comment(card_id, text)
        self._comments.setdefault(card_id, []).insert(0, comment)
        if card := self.find_card(card_id):
            self._replace(replace(card, comment_count=card.comment_count + 1))
        return comment

    async def labels(self, board_id: str) -> list[Label]:
        """A board's labels, sorted by name."""
        if self.snapshot and self.snapshot.board.id == board_id:
            labels = self.snapshot.labels
        else:
            if board_id not in self._labels:
                async with self._busy("labels"):
                    self._labels[board_id] = await self.backend.labels(board_id)
            labels = self._labels[board_id]
        return sorted(labels, key=lambda label: (label.name or label.color or "").lower())

    async def members(self, board_id: str) -> list[Member]:
        """A board's members, for @mentions."""
        if self.snapshot and self.snapshot.board.id == board_id:
            return list(self.snapshot.members.values())
        if board_id not in self._members:
            async with self._busy("members"):
                self._members[board_id] = await self.backend.members(board_id)
        return self._members[board_id]

    async def toggle_label(self, card: Card, label: Label) -> Card:
        """Add the label to the card, or take it off if it's there."""
        async with self._busy("save"):
            if any(lb.id == label.id for lb in card.labels):
                updated = await self.backend.remove_label(card, label)
            else:
                updated = await self.backend.add_label(card, label)
        self._replace(updated)
        return updated

    async def create_label(self, card: Card, name: str) -> Card:
        """Make a new label on the card's board and put it on the card."""
        existing = await self.labels(card.board_id)
        used = {label.color for label in existing}
        color = next((c for c in LABEL_COLOURS if c not in used), LABEL_COLOURS[len(existing) % len(LABEL_COLOURS)])
        async with self._busy("save"):
            label = await self.backend.create_label(card.board_id, name, color)
        if self.snapshot and self.snapshot.board.id == card.board_id:
            if label not in self.snapshot.labels:
                self.snapshot.labels.append(label)
        elif card.board_id in self._labels:
            self._labels[card.board_id].append(label)
        return await self.toggle_label(card, label)

    def _replace(self, card: Card) -> None:
        """Patch the card into every loaded snapshot that has it, and tell their screens."""
        if self.snapshot and self.snapshot.card(card.id):
            self.snapshot.replace_card(card)
            self.board_changed.publish(self.snapshot)
        if self.work and self.work.card(card.id):
            self.work.replace_card(card)
            self.work_changed.publish(self.work)
