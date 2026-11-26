"""Data backends.

A backend is anything that implements :class:`Backend`. Screens never talk to a backend directly; they go through
:class:`tui_trello.store.Store`, which caches board snapshots and broadcasts changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardPreview,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
    Reaction,
    WorkSnapshot,
)


class BackendError(Exception):
    """A backend call failed; the message is fit to show the user. `unsure` if the request may have reached the
    service and done its work all the same (a timeout or dropped connection after sending, a gateway error)."""

    def __init__(self, message: str, *, unsure: bool = False) -> None:
        super().__init__(message)
        self.unsure = unsure


class Backend(Protocol):
    async def me(self) -> Member: ...

    async def boards(self) -> list[Board]: ...

    async def board_snapshot(self, board_id: str) -> BoardSnapshot: ...

    async def card(self, card_id: str) -> Card: ...  # an id or a short link

    async def board(self, board_id: str) -> Board: ...  # likewise

    async def card_preview(self, card_id: str) -> CardPreview: ...  # likewise; archived cards too

    async def my_work(self) -> WorkSnapshot: ...

    async def comments(self, card_id: str) -> list[Comment]: ...

    async def move_card(self, card: Card, list_id: str, pos: str = "top") -> Card: ...

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom") -> Card: ...

    async def archive_card(self, card: Card) -> Card: ...  # the card as Trello now has it, `closed`

    async def delete_card(self, card_id: str) -> None: ...  # for good

    async def add_comment(self, card_id: str, text: str) -> Comment: ...

    async def edit_comment(self, card_id: str, comment_id: str, text: str) -> None: ...

    async def delete_comment(self, card_id: str, comment_id: str) -> None: ...

    async def search_cards(self, query: str) -> list[CardPreview]: ...  # open and archived cards, every board

    async def set_description(self, card: Card, desc: str) -> Card: ...

    async def add_reaction(self, comment_id: str, short_name: str) -> Reaction: ...

    async def remove_reaction(self, comment_id: str, reaction_id: str) -> None: ...

    async def labels(self, board_id: str) -> list[Label]: ...

    async def members(self, board_id: str) -> list[Member]: ...

    async def add_label(self, card: Card, label: Label) -> Card: ...

    async def remove_label(self, card: Card, label: Label) -> Card: ...

    async def create_label(self, board_id: str, name: str, color: str | None) -> Label: ...

    async def add_member(self, card: Card, member_id: str) -> Card: ...  # the card as Trello now has it

    async def remove_member(self, card: Card, member_id: str) -> Card: ...  # likewise

    async def set_watching(self, card: Card, watching: bool) -> Card: ...  # the logged-in member's watch

    async def checklists(self, card_id: str) -> list[Checklist]: ...

    async def set_check_item(self, card_id: str, item: CheckItem, checked: bool) -> CheckItem: ...

    async def add_check_item(self, checklist_id: str, name: str) -> CheckItem: ...

    async def create_checklist(self, card_id: str, name: str) -> Checklist: ...

    async def attachments(self, card_id: str) -> list[Attachment]: ...

    async def attach_file(self, card_id: str, path: Path) -> Attachment: ...

    async def attach_link(self, card_id: str, url: str, name: str = "") -> Attachment: ...

    async def notifications(self) -> list[Notification]: ...

    async def mark_notifications_read(self, ids: list[str]) -> None: ...

    async def mark_all_notifications_read(self) -> None: ...

    async def aclose(self) -> None: ...
