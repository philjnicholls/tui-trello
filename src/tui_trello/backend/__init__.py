"""Data backends.

A backend is anything that implements :class:`Backend`. Screens never talk to a backend directly; they go through
:class:`tui_trello.store.Store`, which caches board snapshots and broadcasts changes.
"""

from __future__ import annotations

from typing import Protocol

from tui_trello.models import (
    Board,
    BoardSnapshot,
    Card,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    WorkSnapshot,
)


class BackendError(Exception):
    """A backend call failed; the message is fit to show the user."""


class Backend(Protocol):
    async def boards(self) -> list[Board]: ...

    async def board_snapshot(self, board_id: str) -> BoardSnapshot: ...

    async def my_work(self) -> WorkSnapshot: ...

    async def comments(self, card_id: str) -> list[Comment]: ...

    async def move_card(self, card: Card, list_id: str, pos: str = "top") -> Card: ...

    async def add_comment(self, card_id: str, text: str) -> Comment: ...

    async def labels(self, board_id: str) -> list[Label]: ...

    async def members(self, board_id: str) -> list[Member]: ...

    async def add_label(self, card: Card, label: Label) -> Card: ...

    async def remove_label(self, card: Card, label: Label) -> Card: ...

    async def create_label(self, board_id: str, name: str, color: str | None) -> Label: ...

    async def checklists(self, card_id: str) -> list[Checklist]: ...

    async def set_check_item(self, card_id: str, item: CheckItem, checked: bool) -> CheckItem: ...

    async def add_check_item(self, checklist_id: str, name: str) -> CheckItem: ...

    async def create_checklist(self, card_id: str, name: str) -> Checklist: ...

    async def aclose(self) -> None: ...
