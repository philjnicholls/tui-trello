"""In-memory backend with made-up data, for `tui-trello --demo`, tests and screenshots."""

from __future__ import annotations

import itertools
import mimetypes
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tui_trello import links
from tui_trello.backend import BackendError
from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardList,
    CardPreview,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
    REACTIONS,
    Reaction,
    WorkSnapshot,
)

NOW = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)  # due dates are relative
END_OF_DAY = NOW.replace(hour=23, minute=59)  # a card due today isn't overdue until the day is over

MEMBERS = {
    "m1": Member("m1", "Ada Lovelace", "ada"),
    "m2": Member("m2", "Grace Hopper", "grace"),
    "m3": Member("m3", "Alan Turing", "alan"),
    "m4": Member("m4", "ليلى حداد", "layla"),
}

ME = "m1"  # the demo's logged-in member

LABELS = {
    "bug": Label("bug", "bug", "red"),
    "feat": Label("feat", "feature", "green"),
    "ux": Label("ux", "ux", "purple"),
    "ops": Label("ops", "ops", "blue"),
    "blocked": Label("blocked", "blocked", "orange"),
}

# (list name, [(card name, labels, members, due in days or None, comments, checklist)])
PRODUCT_BOARD = [
    ("Inbox", [
        ("Crash when a card has no description", ["bug"], [], None, 0, (0, 0)),
        ("Support markdown tables in card view", ["feat", "ux"], ["m1"], None, 1, (0, 0)),
        ("Look into rate limiting on /boards/cards", ["ops"], [], None, 0, (0, 0)),
    ]),
    ("Next up", [
        ("Command palette: jump to any card", ["feat"], ["m2"], 3, 2, (1, 4)),
        ("Keyboard shortcut cheat sheet", ["ux"], ["m1", "m3"], 7, 0, (0, 2)),
        ("Offline cache for boards", ["feat"], [], 14, 0, (0, 0)),
    ]),
    ("Doing", [
        ("Move cards between lists", ["feat"], ["m1"], 1, 3, (3, 5)),
        ("Token stored in plain text in config", ["bug", "blocked"], ["m3", "m1"], -2, 1, (0, 1)),
    ]),
    ("Review", [
        ("Split backend from UI", ["feat"], ["m2", "m1"], 0, 4, (6, 6)),
    ]),
    ("Done", [
        ("Show comments on card detail", ["feat"], ["m1"], -10, 1, (2, 2)),
        ("Vim keys for navigation", ["ux"], ["m3"], -12, 0, (0, 0)),
        ("Render labels in colour", ["ux"], ["m2"], -20, 0, (0, 0)),
    ]),
]

# Right-to-left text, mixed with English and numbers, to exercise ui/bidi.py.
ARABIC_BOARD = [
    ("للمعالجة", [
        ("إصلاح خطأ في نموذج التسجيل (عاجل)", ["bug"], ["m1"], -1, 2, (1, 3)),
        ("تحديث API إلى الإصدار 2.5", ["feat"], ["m4"], 4, 0, (0, 0)),
        ("مراجعة التصميم: الصفحة الرئيسية الجديدة مع دعم كامل للكتابة من اليمين إلى اليسار", ["ux"], ["m1", "m4"], 9, 1, (0, 2)),
    ]),
    ("قيد العمل", [
        ("Migrate بيانات الاستبيان إلى PostgreSQL", ["ops"], ["m4"], 2, 0, (2, 4)),
    ]),
    ("مكتمل", [
        ("خصم 50% للمشتركين", ["feat"], ["m1"], -6, 1, (1, 1)),
    ]),
]

ARABIC_DESCRIPTION = """\
يجب إصلاح الخطأ في نموذج التسجيل قبل الإطلاق.

- الحقل **"الهاتف"** لا يقبل الأرقام التي فيها شرطة (555-0123)
- رسالة الخطأ تظهر بالإنجليزية: `Invalid input`

> تم الاختبار في متصفح *Chrome* فقط
"""

ARABIC_COMMENTS = [
    ("ليلى حداد", "جربت في Chrome و Firefox، والخطأ يظهر في الاثنين."),
    ("Ada Lovelace", "Fixed in **v2.5**, @layla هل يمكنك التحقق مرة أخرى؟"),
]

HOME_BOARD = [
    ("To do", [
        ("Book boiler service", [], ["m1"], 5, 0, (0, 0)),
        ("Renew passport", ["blocked"], ["m1"], 30, 1, (1, 3)),
    ]),
    ("Done", [("Fix the garden gate", [], ["m1"], -3, 0, (0, 0))]),
]
# Label names on the Arabic board.
ARABIC_LABELS = {"bug": "خطأ", "feat": "ميزة", "ux": "تصميم", "ops": "بنية تحتية"}

DESCRIPTION = """\
Cards should move with `m`, which opens a picker of the board's lists.

## Acceptance

- Works from the browser and the triage table
- The card lands at the **top** of the target list
- The move is reflected everywhere without a refresh

```
PUT /1/cards/{id}?idList=...&pos=top
```
"""

# The links the demo shows off, filled in with real URLs once the ids exist.
LINKS = """\
Where this came from:

- the card [Move cards between lists]({card})
- Grace's [review comment]({comment})
- a sketch: ![picker-sketch.png]({sketch})
- the [Home]({board}) board
- the docs: https://textual.textualize.io/
"""

CHECK_ITEMS = ["Write the tests", "Update the `README.md`", "Try it on a real board", "Ask for a review",
               "Check the Arabic board", "Take **new** screenshots"]
ARABIC_CHECK_ITEMS = ["الاختبار في Chrome", "الاختبار على الجوال", "تحديث التوثيق", "طلب مراجعة الكود"]

# Attachments on sample cards, by card name: (name, link or None for an upload, the upload's content).
ATTACHMENTS = {
    "Move cards between lists": [("picker-sketch.png", None, b"\x89PNG\r\n\x1a\n sketch"),
                                 ("Pull request #42", "https://example.com/pr/42", b"")],
    "Token stored in plain text in config": [("config-dump.txt", None, b"token = 'redacted'\n")],
}

# Who reacted to the sample comments, by the comment's place in COMMENTS / ARABIC_COMMENTS.
COMMENT_REACTIONS = {0: [("m3", "+1")], 3: [("m1", "tada"), ("m3", "tada"), ("m2", "+1")]}

COMMENTS = [
    ("Grace Hopper", "Picker works, but it should remember the last list I moved to."),
    ("Alan Turing", "Agreed. Also: undo with `u` within a few seconds?"),
    ("Ada Lovelace", "Pushed a first version, @grace please have a look:\n\n- picker opens on `m`\n"
                     "- ~~remembers the last list~~ next time\n\nSee [the PR](https://example.com/pr/42)."),
    ("Grace Hopper", "Looks good to me."),
]


# (type, who, card name, hours ago, unread, comment or the list a card moved to), newest first
NOTIFICATIONS = [
    ("mentionedOnCard", "Grace Hopper", "Move cards between lists", 1, True,
     "@ada can you check the picker remembers the last list?"),
    ("addedToCard", "Alan Turing", "Token stored in plain text in config", 3, True, ""),
    ("cardDueSoon", "", "Move cards between lists", 5, True, ""),
    ("commentCard", "Grace Hopper", "Split backend from UI", 26, False, "Looks good to me."),
    ("reactionAdded", "Alan Turing", "Split backend from UI", 30, False, "Pushed the split: screens use the store."),
    ("changeCard", "Alan Turing", "Show comments on card detail", 50, False, "Done"),
    ("mentionedOnCard", "ليلى حداد", "إصلاح خطأ في نموذج التسجيل (عاجل)", 70, False, "@ada جربت في Chrome، والمشكلة ما زالت قائمة."),
]


class DemoBackend:
    def __init__(self) -> None:
        self.link_hosts = links.TRELLO_HOSTS | {"trello.example"}  # where the demo's links point; never a real host
        self._ids = (f"id{n}" for n in itertools.count(1))
        self._boards: dict[str, BoardSnapshot] = {}
        self._comments: dict[str, list[Comment]] = {}
        self._checklists: dict[str, list[Checklist]] = {}
        self._attachments: dict[str, list[Attachment]] = {}
        self._files: dict[str, bytes] = {}  # uploads' content, by attachment id
        self._archived: dict[str, list[Card]] = {}  # archived cards, by board id
        for board_id, name, slug, starred, layout in [
            ("b-product", "Product roadmap", "product-roadmap", True, PRODUCT_BOARD),
            ("b-home", "Home", "home", False, HOME_BOARD),
            ("b-arabic", "مشروع الموقع", "arabic-site", False, ARABIC_BOARD),
        ]:
            self._boards[board_id] = self._build(Board(board_id, name, f"https://trello.example/b/{board_id}/{slug}",
                                                       starred), layout)
        self._add_links_description()
        now = datetime.now(timezone.utc)  # "1h ago" should read so whatever the time of day
        self._notifications = [self.notification(kind, who, card, now - timedelta(hours=hours), unread, extra)
                               for kind, who, card, hours, unread, extra in NOTIFICATIONS]
        self._seed_archived()

    def _seed_archived(self) -> None:
        """One archived card, so that search has one to find."""
        snapshot = self._boards["b-product"]
        done = next(lst for lst in snapshot.lists if lst.name == "Done")
        card_id = next(self._ids)
        self._comments[card_id], self._checklists[card_id], self._attachments[card_id] = [], [], []
        self._archived[snapshot.board.id] = [Card(
            card_id, "Drag and drop cards with the mouse", done.id, snapshot.board.id,
            "Dropped: the app is keyboard first.", pos=99, url=f"https://trello.example/c/{card_id}",
            last_activity=NOW - timedelta(days=30), closed=True)]

    def _add_links_description(self) -> None:
        """Give "Offline cache for boards" a description with a card, comment, attachment, board and web link, which
        can only be written once the ids exist."""
        snapshot, card = next((s, c) for s in self._boards.values() for c in s.cards
                              if c.name == "Offline cache for boards")
        moving = next(c for s in self._boards.values() for c in s.cards if c.name == "Move cards between lists")
        split = next(c for s in self._boards.values() for c in s.cards if c.name == "Split backend from UI")
        grace = next(c for c in self._comments[split.id] if c.author == "Grace Hopper")
        sketch = self._attachments[moving.id][0]
        home = self._boards["b-home"].board
        desc = LINKS.format(card=moving.url, comment=split.comment_url(grace.id), sketch=sketch.url, board=home.url)
        snapshot.replace_card(replace(card, desc=desc))

    def notification(self, kind: str, creator: str, card_name: str, date: datetime | None = None,
                     unread: bool = True, extra: str = "") -> Notification:
        """A notification about the card named `card_name`; `extra` is the comment, or the list it moved to."""
        snapshot, card = next((s, c) for s in self._boards.values() for c in s.cards if c.name == card_name)
        return Notification(next(self._ids), kind, unread, date or datetime.now(timezone.utc), creator, card.id,
                            card.name, snapshot.board.id, snapshot.board.name,
                            list_name=extra if kind == "changeCard" else "",
                            text=extra if kind in ("commentCard", "mentionedOnCard", "reactionAdded") else "",
                            creator_username=next((m.username for m in MEMBERS.values() if m.full_name == creator),
                                                  ""),
                            reactions=("🎉",) if kind == "reactionAdded" else ())

    def push_notification(self, notification: Notification) -> None:
        """Something happened on Trello: the next `notifications()` call returns it first (tests)."""
        self._notifications.insert(0, notification)

    def _build(self, board: Board, layout: list) -> BoardSnapshot:
        rtl = board.id == "b-arabic"
        labels_by_key = {
            key: Label(f"{label.id}-ar", ARABIC_LABELS[key], label.color) if rtl and key in ARABIC_LABELS else label
            for key, label in LABELS.items()
        }
        lists, cards = [], []
        for list_pos, (list_name, card_specs) in enumerate(layout):
            card_list = CardList(next(self._ids), list_name, board.id, list_pos)
            lists.append(card_list)
            for card_pos, (name, labels, members, due, comments, checklist) in enumerate(card_specs):
                card_id = next(self._ids)
                self._comments[card_id] = [
                    Comment(next(self._ids), author, text, NOW - timedelta(hours=3 * i),
                            tuple(self._reaction(member, emoji) for member, emoji in COMMENT_REACTIONS.get(i, ())),
                            next((m.username for m in MEMBERS.values() if m.full_name == author), ""),
                            next((m.id for m in MEMBERS.values() if m.full_name == author), ""))
                    for i, (author, text) in enumerate((ARABIC_COMMENTS if rtl else COMMENTS)[:comments])
                ]
                self._checklists[card_id] = self._checklist(checklist, rtl)
                self._attachments[card_id] = [self._attachment(card_id, *spec) for spec in ATTACHMENTS.get(name, ())]
                cards.append(Card(
                    id=card_id,
                    name=name,
                    list_id=card_list.id,
                    board_id=board.id,
                    desc=(ARABIC_DESCRIPTION if rtl else DESCRIPTION) if comments else "",
                    labels=tuple(labels_by_key[label] for label in labels),
                    member_ids=tuple(members),
                    due=END_OF_DAY + timedelta(days=due) if due is not None else None,
                    due_complete=due is not None and list_name == "Done",
                    pos=card_pos,
                    url=f"https://trello.example/c/{card_id}",
                    last_activity=NOW - timedelta(days=card_pos),
                    comment_count=comments,
                    checklist=checklist,
                    attachment_count=len(self._attachments[card_id]),
                ))
        return BoardSnapshot(board, lists, cards, dict(MEMBERS), list(labels_by_key.values()))

    def _checklist(self, badge: tuple[int, int], rtl: bool) -> list[Checklist]:
        """A checklist with `badge`'s (checked, total) items."""
        checked, total = badge
        if not total:
            return []
        names = ARABIC_CHECK_ITEMS if rtl else CHECK_ITEMS
        items = tuple(CheckItem(next(self._ids), names[n % len(names)], n < checked, n) for n in range(total))
        return [Checklist(next(self._ids), "المهام" if rtl else "Tasks", items)]

    def _attachment(self, card_id: str, name: str, link: str | None, content: bytes) -> Attachment:
        attachment_id = next(self._ids)
        if link:
            return Attachment(attachment_id, name, link, is_upload=False, date=NOW)
        self._files[attachment_id] = content
        return Attachment(attachment_id, name, f"https://trello.example/1/cards/{card_id}/attachments/{attachment_id}"
                          f"/download/{name}", is_upload=True, size=len(content), date=NOW, file_name=name,
                          mime_type=mimetypes.guess_type(name)[0] or "")

    def _reaction(self, member_id: str, short_name: str) -> Reaction:
        native = next(native for name, native, _ in REACTIONS if name == short_name)
        return Reaction(next(self._ids), member_id, MEMBERS[member_id].full_name, short_name, native)

    def _patch_comment(self, comment_id: str, change: Callable[[Comment], Comment]) -> None:
        for comments in self._comments.values():
            for i, comment in enumerate(comments):
                if comment.id == comment_id:
                    comments[i] = change(comment)
                    return
        raise BackendError(f"No comment {comment_id}")

    def _find(self, card_id: str) -> tuple[BoardSnapshot, Card]:
        for snapshot in self._boards.values():
            if card := snapshot.card(card_id):
                return snapshot, card
        raise BackendError(f"No card {card_id}")

    async def boards(self) -> list[Board]:
        return [s.board for s in self._boards.values()]

    async def board_snapshot(self, board_id: str) -> BoardSnapshot:
        try:
            snapshot = self._boards[board_id]
        except KeyError:
            raise BackendError(f"No board {board_id}") from None
        # Hand out a copy, as a real backend would.
        return BoardSnapshot(snapshot.board, list(snapshot.lists), list(snapshot.cards), dict(snapshot.members),
                             list(snapshot.labels))

    def _cards(self) -> list[tuple[BoardSnapshot, Card]]:
        """Every card with its board's snapshot: the open ones, then the archived ones."""
        return [(s, c) for s in self._boards.values() for c in s.cards] + [
            (self._boards[board_id], c) for board_id, cards in self._archived.items() for c in cards]

    async def card(self, card_id: str) -> Card:
        for _, card in self._cards():
            if card_id in (card.id, links.short_link(card.url, self.link_hosts)):
                return card
        raise BackendError(f"No card {card_id}")

    async def card_preview(self, card_id: str) -> CardPreview:
        for snapshot, card in self._cards():
            if card_id in (card.id, links.short_link(card.url, self.link_hosts)):
                return CardPreview(card, snapshot.location(card), dict(snapshot.members),
                                   "card" if card.closed else "")
        raise BackendError(f"No card {card_id}")

    async def board(self, board_id: str) -> Board:
        for snapshot in self._boards.values():
            if board_id in (snapshot.board.id, links.short_link(snapshot.board.url, self.link_hosts)):
                return snapshot.board
        raise BackendError(f"No board {board_id}")

    async def my_work(self) -> WorkSnapshot:
        me = MEMBERS[ME]
        return WorkSnapshot(
            me=me,
            cards=[c for s in self._boards.values() for c in s.cards if me.id in c.member_ids],
            boards={board_id: s.board for board_id, s in self._boards.items()},
            lists={lst.id: lst for s in self._boards.values() for lst in s.lists},
        )

    async def comments(self, card_id: str) -> list[Comment]:
        return list(self._comments.get(card_id, []))

    async def move_card(self, card: Card, list_id: str, pos: str = "top") -> Card:
        snapshot, current = self._find(card.id)
        siblings = [c.pos for c in snapshot.cards if c.list_id == list_id and c.id != card.id]
        new_pos = (min(siblings, default=0) - 1) if pos == "top" else (max(siblings, default=0) + 1)
        moved = current.with_list(list_id, new_pos)
        snapshot.replace_card(moved)
        return moved

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom") -> Card:
        snapshot = next((s for s in self._boards.values() if any(lst.id == list_id for lst in s.lists)), None)
        if not snapshot:
            raise BackendError(f"No list {list_id}")
        siblings = [c.pos for c in snapshot.cards if c.list_id == list_id]
        card_id = next(self._ids)
        card = Card(card_id, name, list_id, snapshot.board.id, desc,
                    pos=(min(siblings, default=0) - 1) if pos == "top" else (max(siblings, default=0) + 1),
                    url=f"https://trello.example/c/{card_id}", last_activity=datetime.now(timezone.utc))
        snapshot.cards.append(card)
        self._comments[card_id], self._checklists[card_id], self._attachments[card_id] = [], [], []
        return card

    async def archive_card(self, card: Card) -> Card:
        snapshot, current = self._find(card.id)
        archived = replace(current, closed=True)
        snapshot.remove_card(card.id)
        self._archived.setdefault(snapshot.board.id, []).append(archived)
        return archived

    async def delete_card(self, card_id: str) -> None:
        for cards in self._archived.values():
            if any(c.id == card_id for c in cards):
                cards[:] = [c for c in cards if c.id != card_id]
                break
        else:
            self._find(card_id)[0].remove_card(card_id)
        for things in (self._comments, self._checklists, self._attachments):
            things.pop(card_id, None)

    async def add_comment(self, card_id: str, text: str) -> Comment:
        comment = Comment(next(self._ids), "You", text, datetime.now(timezone.utc), author_id=ME)
        self._comments.setdefault(card_id, []).insert(0, comment)
        for snapshot in self._boards.values():
            if card := snapshot.card(card_id):
                snapshot.replace_card(replace(card, comment_count=card.comment_count + 1))
        return comment

    async def edit_comment(self, card_id: str, comment_id: str, text: str) -> None:
        self._patch_comment(comment_id, lambda c: replace(c, text=text))

    async def delete_comment(self, card_id: str, comment_id: str) -> None:
        if not any(c.id == comment_id for c in self._comments.get(card_id, [])):
            raise BackendError(f"No comment {comment_id}")
        self._comments[card_id] = [c for c in self._comments[card_id] if c.id != comment_id]
        for snapshot in self._boards.values():  # an archived card isn't on its board
            if card := snapshot.card(card_id):
                snapshot.replace_card(replace(card, comment_count=max(card.comment_count - 1, 0)))

    async def search_cards(self, query: str) -> list[CardPreview]:
        """Cards whose name or description has every word of the query, open ones first. Trello's search terms
        (`board:`, `is:open`, ...) aren't interpreted here."""
        words = query.lower().split()
        hits = []
        for snapshot, card in self._cards():
            text = f"{card.name} {card.desc}".lower()
            if words and all(word in text for word in words):
                hits.append(CardPreview(card, snapshot.location(card), dict(snapshot.members),
                                        "card" if card.closed else ""))
        return sorted(hits, key=lambda hit: bool(hit.archived))

    async def me(self) -> Member:
        return MEMBERS[ME]

    async def attachments(self, card_id: str) -> list[Attachment]:
        return list(self._attachments.get(card_id, []))

    async def attach_file(self, card_id: str, path: Path) -> Attachment:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise BackendError(f"Could not read {path}: {exc.strerror}") from exc
        return self._attach(card_id, self._attachment(card_id, path.name, None, content))

    async def attach_link(self, card_id: str, url: str, name: str = "") -> Attachment:
        return self._attach(card_id, self._attachment(card_id, name or url, url, b""))

    def _attach(self, card_id: str, attachment: Attachment) -> Attachment:
        self._attachments.setdefault(card_id, []).append(attachment)
        snapshot, card = self._find(card_id)
        snapshot.replace_card(replace(card, attachment_count=len(self._attachments[card_id])))
        return attachment

    async def download_attachment(self, attachment: Attachment, dest: Path) -> None:
        dest.write_bytes(self._files[attachment.id])

    async def add_reaction(self, comment_id: str, short_name: str) -> Reaction:
        reaction = self._reaction(ME, short_name)
        self._patch_comment(comment_id, lambda c: replace(c, reactions=(*c.reactions, reaction)))
        return reaction

    async def remove_reaction(self, comment_id: str, reaction_id: str) -> None:
        self._patch_comment(comment_id, lambda c: replace(
            c, reactions=tuple(r for r in c.reactions if r.id != reaction_id)))

    async def set_description(self, card: Card, desc: str) -> Card:
        snapshot, current = self._find(card.id)
        updated = replace(current, desc=desc)
        snapshot.replace_card(updated)
        return updated

    async def labels(self, board_id: str) -> list[Label]:
        return list((await self.board_snapshot(board_id)).labels)

    async def members(self, board_id: str) -> list[Member]:
        return list((await self.board_snapshot(board_id)).members.values())

    async def add_label(self, card: Card, label: Label) -> Card:
        snapshot, current = self._find(card.id)
        updated = replace(current, labels=(*current.labels, label))
        snapshot.replace_card(updated)
        return updated

    async def remove_label(self, card: Card, label: Label) -> Card:
        snapshot, current = self._find(card.id)
        updated = replace(current, labels=tuple(lb for lb in current.labels if lb.id != label.id))
        snapshot.replace_card(updated)
        return updated

    async def create_label(self, board_id: str, name: str, color: str | None) -> Label:
        label = Label(next(self._ids), name, color)
        self._boards[board_id].labels.append(label)
        return label

    async def checklists(self, card_id: str) -> list[Checklist]:
        return list(self._checklists.get(card_id, []))

    async def set_check_item(self, card_id: str, item: CheckItem, checked: bool) -> CheckItem:
        updated = replace(item, checked=checked)
        self._checklists[card_id] = [c.with_item(updated) if any(i.id == item.id for i in c.items) else c
                                     for c in self._checklists.get(card_id, [])]
        return updated

    async def add_check_item(self, checklist_id: str, name: str) -> CheckItem:
        for checklists in self._checklists.values():
            for n, checklist in enumerate(checklists):
                if checklist.id == checklist_id:
                    item = CheckItem(next(self._ids), name, pos=len(checklist.items))
                    checklists[n] = checklist.with_item(item)
                    return item
        raise BackendError(f"No checklist {checklist_id}")

    async def create_checklist(self, card_id: str, name: str) -> Checklist:
        checklist = Checklist(next(self._ids), name, pos=len(self._checklists.get(card_id, [])))
        self._checklists.setdefault(card_id, []).append(checklist)
        return checklist

    async def notifications(self) -> list[Notification]:
        return list(self._notifications)

    async def mark_notifications_read(self, ids: list[str]) -> None:
        self._notifications = [replace(n, unread=False) if n.id in ids else n for n in self._notifications]

    async def mark_all_notifications_read(self) -> None:
        self._notifications = [replace(n, unread=False) for n in self._notifications]

    async def aclose(self) -> None:
        pass
