"""App-wide state: the backend, the open board, the user's cross-board work, and signals fired when they change.

Screens read from the store and subscribe to its signals; mutations go through the store so every screen (including
ones further down the stack, or in another mode) redraws from the same data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path

from textual.dom import DOMNode
from textual.signal import Signal

from tui_trello import links
from tui_trello.backend import Backend, BackendError
from tui_trello.drafts import Draft, Drafts, Kind, new_card_id
from tui_trello.files import download_dir, unique_path
from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardContext,
    CardList,
    CardPreview,
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


@dataclass(frozen=True)
class NewCardDraft:
    """A new card's box's draft: its id, what it holds so far, and how many of the list's drafts were free for the
    box (this one included, if it is one of them)."""

    id: str
    draft: Draft | None
    free: int


class Store:
    def __init__(self, owner: DOMNode, backend: Backend, drafts: Drafts | None = None) -> None:
        self.backend = backend
        self.drafts = drafts or Drafts()
        self.drafts_changed: Signal[str] = Signal(owner, "drafts_changed")  # with the card's (or new card draft's) id
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
        self._card_drafts_in_use: Counter[str] = Counter()  # new-card drafts open in a box or being sent, by id
        # Board fetches under way, and the cards made while one was, by id, each with a tick from `_ticks` for when
        # it started or was made: a fetch can have missed only the cards made after it started.
        self._ticks = count()
        self._board_fetches: set[int] = set()
        self._made: dict[str, tuple[int, Card]] = {}
        self._removed: dict[str, int] = {}  # likewise, the cards archived or deleted while one was, with the tick
        self._failed_card_drafts: dict[str, str] = {}  # the new-card draft that failed last, by list

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
        started = next(self._ticks)
        self._board_fetches.add(started)
        try:
            async with self._busy("board"):
                snapshot = await self.backend.board_snapshot(board_id)
            # A card made after the fetch started may be missing from it: keep showing it.
            for made, card in self._made.values():
                if made > started and card.board_id == board_id and not snapshot.card(card.id):
                    snapshot.add_card(card)
            # ... and one removed after it started may still be in it: don't bring it back.
            for card_id in self._removed_since(started):
                if snapshot.card(card_id):
                    snapshot.remove_card(card_id)
        finally:
            self._fetch_done(started)
        self.snapshot = snapshot
        self._comments.clear()
        self._checklists.clear()
        self._attachments.clear()
        self.board_changed.publish(self.snapshot)
        return self.snapshot

    def _removed_since(self, started: int) -> list[str]:
        return [card_id for card_id, removed in self._removed.items() if removed > started]

    def _fetch_done(self, started: int) -> None:
        self._board_fetches.discard(started)
        # Only a fetch still under way can have missed a card or still hold a removed one.
        oldest = min(self._board_fetches, default=None)
        self._made = {card_id: (made, card) for card_id, (made, card) in self._made.items()
                      if oldest is not None and made > oldest}
        self._removed = {card_id: tick for card_id, tick in self._removed.items()
                         if oldest is not None and tick > oldest}

    async def load_work(self) -> WorkSnapshot:
        started = next(self._ticks)
        self._board_fetches.add(started)
        try:
            async with self._busy("work"):
                work = await self.backend.my_work()
            for card_id in self._removed_since(started):
                if work.card(card_id):
                    work.remove_card(card_id)
        finally:
            self._fetch_done(started)
        self.work = work
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

    @property
    def link_hosts(self) -> frozenset[str]:
        """The hosts whose URLs are Trello links: trello.com, and the backend's own, if it has any."""
        return getattr(self.backend, "link_hosts", links.TRELLO_HOSTS)

    def known_card(self, short_link: str) -> Card | None:
        """A loaded card whose URL has this short link (or whose id this is); no request is made."""
        hosts = self.link_hosts
        return next((card for context in self.contexts() for card in context.cards
                     if short_link in (card.id, links.short_link(card.url, hosts))), None)

    def known_board(self, short_link: str) -> Board | None:
        """The open board, or one of the cached or My work boards, with this short link (or id); no request is made."""
        boards = [self.snapshot.board] if self.snapshot else []
        boards += self._boards or []
        boards += list(self.work.boards.values()) if self.work else []
        hosts = self.link_hosts
        return next((b for b in boards if short_link in (b.id, links.short_link(b.url, hosts))), None)

    async def card_by_link(self, short_link: str) -> Card:
        """The card with this short link: a loaded one, else asked of the backend."""
        if card := self.known_card(short_link):
            return card
        async with self._busy("card"):
            return await self.backend.card(short_link)

    async def card_preview(self, short_link: str) -> CardPreview:
        """A card to show in a link's preview: from a loaded snapshot if one has it, else asked of the backend. What
        comes from the backend is not cached (asking again asks again), and no signal is fired, so no screen redraws.
        A loaded snapshot never holds archived cards, so an archived one always comes from the backend, marked."""
        if (card := self.known_card(short_link)) and (context := self.context_for(card.id)):
            return CardPreview(card, context.location(card), context.members)
        async with self._busy("preview"):
            return await self.backend.card_preview(short_link)

    async def board_by_link(self, short_link: str) -> Board:
        if board := self.known_board(short_link):
            return board
        async with self._busy("board"):
            return await self.backend.board(short_link)

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

    async def create_card(self, card_list: CardList, name: str, desc: str = "", draft: str = "") -> Card:
        """Make a card, with no members, at the bottom of the list, and show it if the list's board is open (unless
        a reload while it was being made has brought it already).

        `draft` is the id of the new-card draft it was written in: in use and marked sent meanwhile, dropped once the
        card is made, and kept if not (still marked sent if the outcome of this attempt, or an earlier one, is
        unknown), to be offered first by the list's next box."""
        if draft:
            self._card_drafts_in_use[draft] += 1
            was_sent = bool((before := self.drafts.get("card", draft)) and before.sent)
            self.drafts.mark_sent("card", draft, True)  # quitting before the answer keeps the mark
        try:
            async with self._busy("save"):
                card = await self.backend.create_card(card_list.id, name, desc)
        except BackendError as exc:
            if draft:
                self.drafts.mark_sent("card", draft, was_sent or exc.unsure)
                self._failed_card_drafts[card_list.id] = draft
            raise
        finally:
            if draft:
                self._release_card_draft(draft)
        if draft:
            self.save_draft("card", draft, "")
        if self._board_fetches:
            self._made[card.id] = (next(self._ticks), card)
        if self.snapshot and self.snapshot.board.id == card.board_id and not self.snapshot.card(card.id):
            self.snapshot.add_card(card)
            self.board_changed.publish(self.snapshot)
        return card

    async def add_comment(self, card_id: str, text: str) -> Comment:
        async with self._busy("save"):
            comment = await self.backend.add_comment(card_id, text)
        self._comments.setdefault(card_id, []).insert(0, comment)
        if card := self.find_card(card_id):
            self._replace(replace(card, comment_count=card.comment_count + 1))
        return comment

    async def archive_card(self, card: Card) -> Card:
        """Archive the card on Trello, and take it out of every loaded snapshot."""
        async with self._busy("save"):
            archived = await self.backend.archive_card(card)
        self._remove(card.id)
        return archived

    async def delete_card(self, card: Card) -> None:
        """Delete the card for good, and forget it: its cached details and its drafts, which could never be sent."""
        async with self._busy("save"):
            await self.backend.delete_card(card.id)
        self._remove(card.id)
        for cached in (self._comments, self._checklists, self._attachments):
            cached.pop(card.id, None)
        for kind in ("comment", "desc"):
            self.save_draft(kind, card.id, "")

    async def edit_comment(self, card_id: str, comment: Comment, text: str) -> Comment:
        """Change the text of one of the member's comments. The new text is what was sent: the reply's shape isn't
        in Trello's API reference."""
        async with self._busy("save"):
            await self.backend.edit_comment(card_id, comment.id, text)
        updated = replace(comment, text=text)
        if card_id in self._comments:
            self._comments[card_id] = [updated if c.id == comment.id else c for c in self._comments[card_id]]
        self.comments_changed.publish(card_id)
        return updated

    async def delete_comment(self, card_id: str, comment: Comment) -> None:
        async with self._busy("save"):
            await self.backend.delete_comment(card_id, comment.id)
        if card_id in self._comments:
            self._comments[card_id] = [c for c in self._comments[card_id] if c.id != comment.id]
        if card := self.find_card(card_id):
            self._replace(replace(card, comment_count=max(card.comment_count - 1, 0)))
        self.comments_changed.publish(card_id)

    async def search_cards(self, query: str) -> list[CardPreview]:
        """Cards on every board, archived ones too, matching what Trello's search makes of the query. Not cached."""
        async with self._busy("search"):
            return await self.backend.search_cards(query)

    async def set_description(self, card: Card, desc: str) -> Card:
        async with self._busy("save"):
            updated = await self.backend.set_description(card, desc)
        self._replace(updated)
        return updated

    def draft(self, kind: Kind, card_id: str) -> Draft | None:
        return self.drafts.get(kind, card_id)

    def save_draft(self, kind: Kind, card_id: str, text: str, base: str = "") -> None:
        """Keep unsent text (blank text drops the draft) and tell the views, which mark cards with a draft. The
        id is the card's, or for a new card its draft's (`<list id>/<token>`)."""
        if self.drafts.set(kind, card_id, text, base):
            self.drafts_changed.publish(card_id)

    # Each new card's box has a draft of its own, `<list id>/<token>`, from the moment it opens until Trello has made
    # the card. A draft is in use while a box has it open or its card is being sent, and is offered to the next box
    # on the list only when it isn't.

    @contextmanager
    def new_card_box(self, list_id: str) -> Iterator[NewCardDraft]:
        """The draft for a new card's box on the list, in use until the box is done: the list's draft that failed
        last, else its oldest, not in use, or a new one."""
        free = self.new_card_drafts(list_id)
        if (failed := self._failed_card_drafts.get(list_id)) in free:
            free.remove(failed)
            free.insert(0, failed)
        card_id = free[0] if free else new_card_id(list_id)
        self._card_drafts_in_use[card_id] += 1
        try:
            yield NewCardDraft(card_id, self.drafts.get("card", card_id), len(free))
        finally:
            self._release_card_draft(card_id)

    def new_card_drafts(self, list_id: str) -> list[str]:
        """The ids of the list's new-card drafts that no box has open and aren't being sent, oldest first."""
        return [card_id for card_id in self.drafts.ids("card", f"{list_id}/") if not self._card_drafts_in_use[card_id]]

    def lists_with_card_drafts(self) -> set[str]:
        return {card_id.partition("/")[0] for card_id in self.drafts.ids("card", "")}

    def _release_card_draft(self, card_id: str) -> None:
        self._card_drafts_in_use[card_id] -= 1
        if not self._card_drafts_in_use[card_id]:
            del self._card_drafts_in_use[card_id]

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

    def _remove(self, card_id: str) -> None:
        """Take the card out of every loaded snapshot that has it, and tell their screens: the counterpart of
        `_replace`."""
        self._made.pop(card_id, None)  # a reload under way mustn't put it back
        if self._board_fetches:
            self._removed[card_id] = next(self._ticks)
        if self.snapshot and self.snapshot.card(card_id):
            self.snapshot.remove_card(card_id)
            self.board_changed.publish(self.snapshot)
        if self.work and self.work.card(card_id):
            self.work.remove_card(card_id)
            self.work_changed.publish(self.work)

    def _replace(self, card: Card) -> None:
        """Patch the card into every loaded snapshot that has it, and tell their screens."""
        if card.id in self._made:  # a reload that missed it shows it as it is now
            self._made[card.id] = (self._made[card.id][0], card)
        if self.snapshot and self.snapshot.card(card.id):
            self.snapshot.replace_card(card)
            self.board_changed.publish(self.snapshot)
        if self.work and self.work.card(card.id):
            self.work.replace_card(card)
            self.work_changed.publish(self.work)
