"""Domain models.

The UI only ever sees these types, never raw API payloads, so a backend can be swapped (REST, demo data, a cache)
without touching any screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

# Trello's label colours mapped onto Rich colour names.
LABEL_COLOURS = {
    "green": "green",
    "yellow": "yellow",
    "orange": "dark_orange",
    "red": "red",
    "purple": "medium_purple",
    "blue": "dodger_blue1",
    "sky": "sky_blue1",
    "lime": "chartreuse3",
    "pink": "hot_pink",
    "black": "grey50",
}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class Label:
    id: str
    name: str
    color: str | None

    @property
    def rich_colour(self) -> str:
        base = (self.color or "").split("_")[0]  # Trello has variants such as "green_dark"
        return LABEL_COLOURS.get(base, "grey50")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Label:
        return cls(id=data["id"], name=data.get("name") or "", color=data.get("color"))


@dataclass(frozen=True)
class Member:
    id: str
    full_name: str
    username: str

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.full_name.split()[:2]).upper() or self.username[:2].upper()

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Member:
        return cls(id=data["id"], full_name=data.get("fullName") or "", username=data.get("username") or "")


@dataclass(frozen=True)
class Board:
    id: str
    name: str
    url: str = ""
    starred: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Board:
        return cls(id=data["id"], name=data["name"], url=data.get("url", ""), starred=data.get("starred", False))


@dataclass(frozen=True)
class CardList:
    id: str
    name: str
    board_id: str
    pos: float = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CardList:
        return cls(id=data["id"], name=data["name"], board_id=data.get("idBoard", ""), pos=data.get("pos", 0))


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    list_id: str
    board_id: str
    desc: str = ""
    labels: tuple[Label, ...] = ()
    member_ids: tuple[str, ...] = ()
    due: datetime | None = None
    due_complete: bool = False
    pos: float = 0
    url: str = ""
    last_activity: datetime | None = None
    comment_count: int = 0
    checklist: tuple[int, int] = (0, 0)  # (checked, total)

    def with_list(self, list_id: str, pos: float) -> Card:
        return replace(self, list_id=list_id, pos=pos)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Card:
        badges = data.get("badges") or {}
        return cls(
            id=data["id"],
            name=data["name"],
            list_id=data["idList"],
            board_id=data.get("idBoard", ""),
            desc=data.get("desc") or "",
            labels=tuple(Label.from_api(label) for label in data.get("labels") or ()),
            member_ids=tuple(data.get("idMembers") or ()),
            due=_parse_date(data.get("due")),
            due_complete=data.get("dueComplete", False),
            pos=data.get("pos", 0),
            url=data.get("url", ""),
            last_activity=_parse_date(data.get("dateLastActivity")),
            comment_count=badges.get("comments", 0),
            checklist=(badges.get("checkItemsChecked", 0), badges.get("checkItems", 0)),
        )


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    text: str
    date: datetime | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Comment:
        return cls(
            id=data["id"],
            author=(data.get("memberCreator") or {}).get("fullName", "?"),
            text=data["data"]["text"],
            date=_parse_date(data.get("date")),
        )


@dataclass(frozen=True)
class CheckItem:
    id: str
    name: str
    checked: bool = False
    pos: float = 0

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CheckItem:
        return cls(id=data["id"], name=data.get("name") or "", checked=data.get("state") == "complete",
                   pos=data.get("pos", 0))


@dataclass(frozen=True)
class Checklist:
    id: str
    name: str
    items: tuple[CheckItem, ...] = ()
    pos: float = 0

    @property
    def done(self) -> int:
        return sum(item.checked for item in self.items)

    def with_item(self, item: CheckItem) -> Checklist:
        """The checklist with `item` replaced (by id) or, if it's new, added at the end."""
        if any(i.id == item.id for i in self.items):
            return replace(self, items=tuple(item if i.id == item.id else i for i in self.items))
        return replace(self, items=(*self.items, item))

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Checklist:
        items = sorted((CheckItem.from_api(item) for item in data.get("checkItems") or ()), key=lambda i: i.pos)
        return cls(id=data["id"], name=data.get("name") or "", items=tuple(items), pos=data.get("pos", 0))


def checklist_badge(checklists: list[Checklist]) -> tuple[int, int]:
    """(checked, total) over a card's checklists, as `Card.checklist` holds it."""
    return sum(c.done for c in checklists), sum(len(c.items) for c in checklists)


class CardContext(Protocol):
    """What a view needs around a card to draw it and act on it. Both snapshot types provide it."""

    members: dict[str, Member]

    def card(self, card_id: str) -> Card | None: ...

    def list_named(self, list_id: str) -> str: ...

    def location(self, card: Card) -> str: ...

    def lists_for(self, card: Card) -> list[CardList]: ...

    def replace_card(self, card: Card) -> None: ...


@dataclass
class BoardSnapshot:
    """Everything needed to draw one board, loaded together."""

    board: Board
    lists: list[CardList]
    cards: list[Card]
    members: dict[str, Member] = field(default_factory=dict)
    labels: list[Label] = field(default_factory=list)

    def cards_in(self, list_id: str) -> list[Card]:
        return sorted((c for c in self.cards if c.list_id == list_id), key=lambda c: c.pos)

    def list_named(self, list_id: str) -> str:
        return next((lst.name for lst in self.lists if lst.id == list_id), "?")

    def card(self, card_id: str) -> Card | None:
        return next((c for c in self.cards if c.id == card_id), None)

    def location(self, card: Card) -> str:
        return f"{self.board.name} › {self.list_named(card.list_id)}"

    def lists_for(self, card: Card) -> list[CardList]:
        return self.lists

    def replace_card(self, card: Card) -> None:
        self.cards = [card if c.id == card.id else c for c in self.cards]


@dataclass
class WorkSnapshot:
    """The current member's open cards across every board, with the boards and lists needed to place them."""

    me: Member
    cards: list[Card]
    boards: dict[str, Board]
    lists: dict[str, CardList]

    @property
    def members(self) -> dict[str, Member]:
        return {self.me.id: self.me}

    def card(self, card_id: str) -> Card | None:
        return next((c for c in self.cards if c.id == card_id), None)

    def list_named(self, list_id: str) -> str:
        return self.lists[list_id].name if list_id in self.lists else "?"

    def board_named(self, board_id: str) -> str:
        return self.boards[board_id].name if board_id in self.boards else "?"

    def location(self, card: Card) -> str:
        return f"{self.board_named(card.board_id)} › {self.list_named(card.list_id)}"

    def lists_for(self, card: Card) -> list[CardList]:
        return sorted((lst for lst in self.lists.values() if lst.board_id == card.board_id), key=lambda lst: lst.pos)

    def replace_card(self, card: Card) -> None:
        self.cards = [card if c.id == card.id else c for c in self.cards]
