"""App-wide state: the backend, the open board, the user's cross-board work, and signals fired when they change.

Screens read from the store and subscribe to its signals; mutations go through the store so every screen (including
ones further down the stack, or in another mode) redraws from the same data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from textual.dom import DOMNode
from textual.signal import Signal

from tui_trello.backend import Backend
from tui_trello.drafts import Draft, Drafts, Kind
from tui_trello.files import download_dir, unique_path
from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardContext,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
    WorkSnapshot,
    checklist_badge,
)

# Trello's label colours, in the order new labels take them.
LABEL_COLOURS = ("green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "black")


class Store:
    def __init__(self, owner: DOMNode, backend: Backend, drafts: Drafts | None = None) -> None:
        self.backend = backend
        self.drafts = drafts or Drafts()
        self.drafts_changed: Signal[str] = Signal(owner, "drafts_changed")  # with the card's id
        self.comments_changed: Signal[str] = Signal(owner, "comments_changed")  # likewise; for reactions
        self._me: Member | None = None
        self.snapshot: BoardSnapshot | None = None
        self.work: WorkSnapshot | None = None
        self.board_changed: Signal[BoardSnapshot] = Signal(owner, "board_changed")
        self.work_changed: Signal[WorkSnapshot] = Signal(owner, "work_changed")
        self.notifications: list[Notification] | None = None  # newest first
        self.notifications_changed: Signal[list[Notification]] = Signal(owner, "notifications_changed")
        # What is being fetched or saved right now ("board", "work", "boards", "comments", "checklists",
        # "notifications", "save"), for spinners.
        self.busy: dict[str, int] = {}
        self.busy_changed: Signal[Store] = Signal(owner, "busy_changed")
        self._boards: list[Board] | None = None
        self._comments: dict[str, list[Comment]] = {}
        self._checklists: dict[str, list[Checklist]] = {}
        self._attachments: dict[str, list[Attachment]] = {}
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
        self._checklists.clear()
        self._attachments.clear()
        self.board_changed.publish(self.snapshot)
        return self.snapshot

    async def load_work(self) -> WorkSnapshot:
        async with self._busy("work"):
            self.work = await self.backend.my_work()
        self.work_changed.publish(self.work)
        return self.work

    @property
    def unread_count(self) -> int:
        return sum(n.unread for n in self.notifications or ())

    def unread_by_card(self) -> Counter[str]:
        """How many unread notifications each card has, by card id."""
        return Counter(n.card_id for n in self.notifications or () if n.unread and n.card_id)

    def unread_by_board(self) -> Counter[str]:
        return Counter(n.board_id for n in self.notifications or () if n.unread and n.board_id)

    async def load_notifications(self) -> list[Notification]:
        """Fetch the notifications; return the unread ones that arrived since the last fetch (none on the first)."""
        async with self._busy("notifications"):
            fetched = await self.backend.notifications()
        seen = None if self.notifications is None else {n.id for n in self.notifications}
        self.notifications = fetched
        self.notifications_changed.publish(fetched)
        return [n for n in fetched if n.unread and n.id not in seen] if seen is not None else []

    async def mark_read(self, notification: Notification) -> None:
        await self._mark_read([notification.id])

    async def mark_card_read(self, card_id: str) -> None:
        """Mark every unread notification about the card read, as opening the card on trello.com does."""
        await self._mark_read([n.id for n in self.notifications or () if n.unread and n.card_id == card_id])

    async def mark_all_read(self) -> None:
        async with self._busy("save"):
            await self.backend.mark_all_notifications_read()
        self._patch_read(lambda n: True)

    async def _mark_read(self, ids: list[str]) -> None:
        if not ids:
            return
        async with self._busy("save"):
            await self.backend.mark_notifications_read(ids)
        self._patch_read(lambda n: n.id in ids)

    def _patch_read(self, which: Callable[[Notification], bool]) -> None:
        self.notifications = [replace(n, unread=False) if which(n) else n for n in self.notifications or ()]
        self.notifications_changed.publish(self.notifications)

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

    async def me(self) -> Member:
        """The logged-in member, to tell their reactions from other people's."""
        if self._me is None:
            self._me = self.work.me if self.work else await self.backend.me()
        return self._me

    @property
    def me_id(self) -> str:
        return self._me.id if self._me else ""

    async def toggle_reaction(self, card_id: str, comment: Comment, short_name: str, native: str) -> Comment:
        """React to the comment with the emoji, or take the member's reaction off if they've given it."""
        me = await self.me()
        async with self._busy("save"):
            if mine := comment.mine(short_name, me.id):
                await self.backend.remove_reaction(comment.id, mine.id)
                reactions = tuple(r for r in comment.reactions if r.id != mine.id)
            else:
                added = await self.backend.add_reaction(comment.id, short_name)
                # Fill in what the response may leave out, so the reaction counts as the member's.
                added = replace(added, member_id=added.member_id or me.id,
                                member_name=added.member_name or me.full_name,
                                short_name=added.short_name or short_name, native=added.native or native)
                reactions = (*comment.reactions, added)
        updated = replace(comment, reactions=reactions)
        if card_id in self._comments:
            self._comments[card_id] = [updated if c.id == comment.id else c for c in self._comments[card_id]]
        self.comments_changed.publish(card_id)
        return updated

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

    async def set_description(self, card: Card, desc: str) -> Card:
        async with self._busy("save"):
            updated = await self.backend.set_description(card, desc)
        self._replace(updated)
        return updated

    def draft(self, kind: Kind, card_id: str) -> Draft | None:
        return self.drafts.get(kind, card_id)

    def save_draft(self, kind: Kind, card_id: str, text: str, base: str = "") -> None:
        """Keep unsent text (blank text drops the draft) and tell the views, which mark cards with a draft."""
        if self.drafts.set(kind, card_id, text, base):
            self.drafts_changed.publish(card_id)

    def has_checklists(self, card_id: str) -> bool:
        """Whether the card's checklists are loaded and there is at least one (perhaps with no items yet)."""
        return bool(self._checklists.get(card_id))

    async def checklists(self, card_id: str, refresh: bool = False) -> list[Checklist]:
        if card_id not in self._checklists or refresh:
            async with self._busy("checklists"):
                self._checklists[card_id] = await self.backend.checklists(card_id)
        return self._checklists[card_id]

    async def toggle_check_item(self, card_id: str, item: CheckItem) -> CheckItem:
        """Tick the item, or untick it if it's ticked."""
        async with self._busy("save"):
            updated = await self.backend.set_check_item(card_id, item, not item.checked)
        self._patch_checklists(card_id, lambda checklists: [
            c.with_item(updated) if any(i.id == item.id for i in c.items) else c for c in checklists])
        return updated

    async def add_check_item(self, card_id: str, checklist_id: str, name: str) -> CheckItem:
        async with self._busy("save"):
            item = await self.backend.add_check_item(checklist_id, name)
        self._patch_checklists(card_id, lambda checklists: [
            c.with_item(item) if c.id == checklist_id else c for c in checklists])
        return item

    async def create_checklist(self, card_id: str, name: str) -> Checklist:
        async with self._busy("save"):
            checklist = await self.backend.create_checklist(card_id, name)
        self._patch_checklists(card_id, lambda checklists: [*checklists, checklist])
        return checklist

    def _patch_checklists(self, card_id: str, change: Callable[[list[Checklist]], list[Checklist]]) -> None:
        """Apply `change` to the card's cached checklists, if they are loaded, and bring its ☑ badge in line."""
        if card_id not in self._checklists:
            return  # the next look fetches them whole
        self._checklists[card_id] = change(self._checklists[card_id])
        if card := self.find_card(card_id):
            self._replace(replace(card, checklist=checklist_badge(self._checklists[card_id])))

    def has_attachments(self, card_id: str) -> bool:
        return bool(self._attachments.get(card_id))

    async def attachments(self, card_id: str, refresh: bool = False) -> list[Attachment]:
        if card_id not in self._attachments or refresh:
            async with self._busy("attachments"):
                self._attachments[card_id] = await self.backend.attachments(card_id)
        return self._attachments[card_id]

    async def attach_file(self, card_id: str, path: Path) -> Attachment:
        async with self._busy("save"):
            attachment = await self.backend.attach_file(card_id, path)
        self._added_attachment(card_id, attachment)
        return attachment

    async def attach_link(self, card_id: str, url: str, name: str = "") -> Attachment:
        async with self._busy("save"):
            attachment = await self.backend.attach_link(card_id, url, name)
        self._added_attachment(card_id, attachment)
        return attachment

    def _added_attachment(self, card_id: str, attachment: Attachment) -> None:
        """Add it to the cached list, if loaded, and bring the card's 📎 badge in line."""
        if card_id in self._attachments:
            self._attachments[card_id] = [*self._attachments[card_id], attachment]
        if card := self.find_card(card_id):
            count = len(self._attachments[card_id]) if card_id in self._attachments else card.attachment_count + 1
            self._replace(replace(card, attachment_count=count))

    async def download_attachment(self, attachment: Attachment, directory: Path | None = None) -> Path:
        """Save an uploaded file into the downloads directory (under a new name if it's taken); return where."""
        directory = directory or download_dir()
        directory.mkdir(parents=True, exist_ok=True)
        dest = unique_path(directory, attachment.file_name or attachment.name)
        async with self._busy("download"):
            await self.backend.download_attachment(attachment, dest)
        return dest

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
