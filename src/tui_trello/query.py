"""A small card filter language, shared by every view that filters cards.

    login #bug @ada !overdue list:doing

- bare words must all appear in the card name or description (case-insensitive)
- `#label` matches a label name prefix, `@user` a member username or name prefix, `list:name` a list name prefix
- `!overdue`, `!due` (has a due date); add more flags to `FLAGS`
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tui_trello.models import BoardSnapshot, Card

Predicate = Callable[[Card, BoardSnapshot], bool]


def _overdue(card: Card, snapshot: BoardSnapshot) -> bool:
    return card.due is not None and not card.due_complete and card.due < datetime.now(timezone.utc)


FLAGS: dict[str, Predicate] = {
    "overdue": _overdue,
    "due": lambda card, snapshot: card.due is not None,
}


@dataclass
class CardQuery:
    words: list[str] = field(default_factory=list)
    predicates: list[Predicate] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> CardQuery:
        query = cls()
        for token in text.lower().split():
            if token.startswith("#") and len(token) > 1:
                name = token[1:]
                query.predicates.append(lambda c, s, n=name: any(lb.name.lower().startswith(n) for lb in c.labels))
            elif token.startswith("@") and len(token) > 1:
                name = token[1:]
                query.predicates.append(lambda c, s, n=name: any(
                    m in s.members and (s.members[m].username.lower().startswith(n)
                                        or s.members[m].full_name.lower().startswith(n))
                    for m in c.member_ids
                ))
            elif token.startswith("list:") and len(token) > 5:
                name = token[5:]
                query.predicates.append(lambda c, s, n=name: s.list_named(c.list_id).lower().startswith(n))
            elif token.startswith("!") and token[1:] in FLAGS:
                query.predicates.append(FLAGS[token[1:]])
            else:
                query.words.append(token)
        return query

    def matches(self, card: Card, snapshot: BoardSnapshot) -> bool:
        haystack = f"{card.name}\n{card.desc}".lower()
        return all(w in haystack for w in self.words) and all(p(card, snapshot) for p in self.predicates)

    def filter(self, snapshot: BoardSnapshot) -> list[Card]:
        return [card for card in snapshot.cards if self.matches(card, snapshot)]
