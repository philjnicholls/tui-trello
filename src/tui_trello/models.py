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
    attachment_count: int = 0
    closed: bool = False  # archived on Trello; loaded boards never hold one
    list_closed: bool = False  # its list is archived; only known for a card fetched alone (backend.card)

    def comment_url(self, comment_id: str) -> str:
        """A link straight to one of the card's comments, as trello.com's "Copy link" on a comment gives."""
        return f"{self.url}#comment-{comment_id}" if self.url else ""

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
            attachment_count=badges.get("attachments", 0),
            closed=data.get("closed", False),
            list_closed=(data.get("list") or {}).get("closed", False),
        )


@dataclass(frozen=True)
class Attachment:
    """A file uploaded to a card, or a link attached to it."""

    id: str
    name: str
    url: str
    is_upload: bool
    size: int = 0  # bytes; 0 for links
    mime_type: str = ""
    date: datetime | None = None
    file_name: str = ""  # an upload's file name, which `name` may have been renamed from

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Attachment:
        return cls(id=data["id"], name=data.get("name") or data.get("fileName") or data.get("url", ""),
                   url=data.get("url", ""), is_upload=data.get("isUpload", False), size=data.get("bytes") or 0,
                   mime_type=data.get("mimeType") or "", date=_parse_date(data.get("date")),
                   file_name=data.get("fileName") or "")


@dataclass(frozen=True)
class Reaction:
    """One member's emoji on a comment."""

    id: str
    member_id: str
    member_name: str
    short_name: str  # Trello's (iamcal emoji-data) name: "+1", "tada", ...; what a reaction is added by
    native: str  # the emoji itself

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Reaction:
        emoji = data.get("emoji") or {}
        unified = emoji.get("unified") or data.get("idEmoji") or ""
        native = emoji.get("native") or "".join(chr(int(part, 16)) for part in unified.split("-") if part)
        return cls(id=data["id"], member_id=data.get("idMember") or "",
                   member_name=(data.get("member") or {}).get("fullName", ""),
                   short_name=emoji.get("shortName") or "", native=native)


# The reactions offered on a comment: (Trello's short name, the emoji, its name in the picker).
REACTIONS = (
    ("+1", "👍", "thumbs up"),
    ("-1", "👎", "thumbs down"),
    ("heart", "❤️", "heart"),
    ("joy", "😂", "laugh"),
    ("tada", "🎉", "hooray"),
    ("open_mouth", "😮", "wow"),
    ("cry", "😢", "sad"),
    ("eyes", "👀", "eyes"),
    ("pray", "🙏", "thanks"),
    ("white_check_mark", "✅", "done"),
    ("rocket", "🚀", "rocket"),
    ("fire", "🔥", "fire"),
)


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    text: str
    date: datetime | None
    reactions: tuple[Reaction, ...] = ()
    author_username: str = ""  # for an @mention in a reply

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Comment:
        creator = data.get("memberCreator") or {}
        return cls(
            id=data["id"],
            author=creator.get("fullName", "?"),
            text=data["data"]["text"],
            date=_parse_date(data.get("date")),
            reactions=tuple(Reaction.from_api(r) for r in data.get("reactions") or ()),
            author_username=creator.get("username") or "",
        )

    def mine(self, short_name: str, member_id: str) -> Reaction | None:
        return next((r for r in self.reactions if r.short_name == short_name and r.member_id == member_id), None)

    def reaction_counts(self, member_id: str = "") -> list[tuple[str, str, int, bool]]:
        """(short name, emoji, how many, whether `member_id` is one of them), in the order they were first given."""
        counts: dict[str, tuple[str, str, int, bool]] = {}
        for r in self.reactions:
            _, native, n, mine = counts.get(r.short_name, (r.short_name, r.native, 0, False))
            counts[r.short_name] = (r.short_name, native, n + 1, mine or r.member_id == member_id)
        return list(counts.values())

    def reactors(self, short_name: str, member_id: str = "") -> list[str]:
        """Who gave the reaction, in order, with "you" for `member_id`."""
        return ["you" if r.member_id == member_id else r.member_name or "?" for r in self.reactions
                if r.short_name == short_name]


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


@dataclass(frozen=True)
class Notification:
    """One of the member's Trello notifications (the bell): someone mentioned them, added them to a card, ..."""

    id: str
    type: str  # Trello's: mentionedOnCard, commentCard, addedToCard, changeCard, cardDueSoon, ...
    unread: bool
    date: datetime | None
    creator: str = ""  # who did it; empty for Trello's own (cardDueSoon)
    card_id: str = ""  # empty for notifications not about a card (addedToBoard, ...)
    card_name: str = ""
    board_id: str = ""
    board_name: str = ""
    list_name: str = ""  # where a card was moved to (changeCard)
    text: str = ""  # the comment, for commentCard and mentionedOnCard; the one reacted to, for reactionAdded
    creator_username: str = ""
    reactions: tuple[str, ...] = ()  # the emoji the creator put on the comment, for reactionAdded

    @property
    def is_comment(self) -> bool:
        """About someone's comment on a card, which can be replied to."""
        return self.type in ("commentCard", "mentionedOnCard") and bool(self.card_id and self.text)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Notification:
        detail = data.get("data") or {}
        card, board = detail.get("card") or {}, detail.get("board") or {}
        creator = data.get("memberCreator") or {}
        creator_id = creator.get("id") or data.get("idMemberCreator")
        # A reactionAdded notification carries the comment's reactions; the creator's are the ones it's about.
        reactions = [Reaction.from_api(r) for r in data.get("reactions") or ()]
        return cls(
            id=data["id"],
            type=data.get("type") or "",
            unread=data.get("unread", False),
            date=_parse_date(data.get("date")),
            creator=creator.get("fullName", ""),
            card_id=card.get("id", ""),
            card_name=card.get("name", ""),
            board_id=board.get("id", ""),
            board_name=board.get("name", ""),
            list_name=(detail.get("listAfter") or {}).get("name", ""),
            text=detail.get("text") or "",
            creator_username=creator.get("username") or "",
            reactions=tuple(r.native for r in reactions if not creator_id or r.member_id == creator_id),
        )


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

    def add_card(self, card: Card) -> None:
        self.cards.append(card)


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
        return self.place(card.board_id, self.list_named(card.list_id))

    def list_location(self, card_list: CardList) -> str:
        return self.place(card_list.board_id, card_list.name)

    def place(self, board_id: str, list_name: str) -> str:
        return f"{self.board_named(board_id)} › {list_name}"

    def lists_for(self, card: Card) -> list[CardList]:
        return sorted((lst for lst in self.lists.values() if lst.board_id == card.board_id), key=lambda lst: lst.pos)

    def replace_card(self, card: Card) -> None:
        self.cards = [card if c.id == card.id else c for c in self.cards]
