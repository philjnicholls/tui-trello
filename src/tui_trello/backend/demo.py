"""In-memory backend with made-up data, for `tui-trello --demo`, tests and screenshots."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tui_trello.backend import BackendError
from tui_trello.models import (
    Board,
    BoardSnapshot,
    Card,
    CardList,
    CheckItem,
    Checklist,
    Comment,
    Label,
    Member,
    Notification,
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

CHECK_ITEMS = ["Write the tests", "Update the `README.md`", "Try it on a real board", "Ask for a review",
               "Check the Arabic board", "Take **new** screenshots"]
ARABIC_CHECK_ITEMS = ["الاختبار في Chrome", "الاختبار على الجوال", "تحديث التوثيق", "طلب مراجعة الكود"]

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
    ("changeCard", "Alan Turing", "Show comments on card detail", 50, False, "Done"),
    ("mentionedOnCard", "ليلى حداد", "إصلاح خطأ في نموذج التسجيل (عاجل)", 70, False, "@ada جربت في Chrome، والمشكلة ما زالت قائمة."),
]


class DemoBackend:
    def __init__(self) -> None:
        self._ids = (f"id{n}" for n in itertools.count(1))
        self._boards: dict[str, BoardSnapshot] = {}
        self._comments: dict[str, list[Comment]] = {}
        self._checklists: dict[str, list[Checklist]] = {}
        for board_id, name, starred, layout in [
            ("b-product", "Product roadmap", True, PRODUCT_BOARD),
            ("b-home", "Home", False, HOME_BOARD),
            ("b-arabic", "مشروع الموقع", False, ARABIC_BOARD),
        ]:
            self._boards[board_id] = self._build(Board(board_id, name, f"https://trello.example/{board_id}", starred),
                                                 layout)
        now = datetime.now(timezone.utc)  # "1h ago" should read so whatever the time of day
        self._notifications = [self.notification(kind, who, card, now - timedelta(hours=hours), unread, extra)
                               for kind, who, card, hours, unread, extra in NOTIFICATIONS]

    def notification(self, kind: str, creator: str, card_name: str, date: datetime | None = None,
                     unread: bool = True, extra: str = "") -> Notification:
        """A notification about the card named `card_name`; `extra` is the comment, or the list it moved to."""
        snapshot, card = next((s, c) for s in self._boards.values() for c in s.cards if c.name == card_name)
        return Notification(next(self._ids), kind, unread, date or datetime.now(timezone.utc), creator, card.id,
                            card.name, snapshot.board.id, snapshot.board.name,
                            list_name=extra if kind == "changeCard" else "",
                            text=extra if kind in ("commentCard", "mentionedOnCard") else "")

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
                    Comment(next(self._ids), author, text, NOW - timedelta(hours=3 * i))
                    for i, (author, text) in enumerate((ARABIC_COMMENTS if rtl else COMMENTS)[:comments])
                ]
                self._checklists[card_id] = self._checklist(checklist, rtl)
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

    async def add_comment(self, card_id: str, text: str) -> Comment:
        comment = Comment(next(self._ids), "You", text, datetime.now(timezone.utc))
        self._comments.setdefault(card_id, []).insert(0, comment)
        return comment

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
