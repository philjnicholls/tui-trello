"""Group cards by when they're due, for the My work view."""

from __future__ import annotations

from datetime import datetime, timedelta

from tui_trello.models import Card

GROUPS = ("Overdue", "Today", "This week", "Later", "No due date", "Done")


def group_of(card: Card, now: datetime) -> str:
    if card.due_complete:
        return "Done"
    if card.due is None:
        return "No due date"
    due = card.due.astimezone(now.tzinfo).date()
    today = now.date()
    if card.due < now and due < today:
        return "Overdue"
    if due <= today:
        return "Today"
    if due < today + timedelta(days=7):
        return "This week"
    return "Later"


def agenda(cards: list[Card], now: datetime) -> list[tuple[str, list[Card]]]:
    """Non-empty groups in GROUPS order, each sorted by due date, then name."""
    groups: dict[str, list[Card]] = {name: [] for name in GROUPS}
    for card in cards:
        groups[group_of(card, now)].append(card)
    return [
        (name, sorted(group, key=lambda c: (c.due or now, c.name.lower())))
        for name, group in groups.items() if group
    ]
