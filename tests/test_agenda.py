from datetime import datetime, timedelta, timezone

from tui_trello.agenda import agenda, group_of
from tui_trello.models import Card

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def card(name: str, due_in_hours: float | None, done: bool = False) -> Card:
    due = NOW + timedelta(hours=due_in_hours) if due_in_hours is not None else None
    return Card(id=name, name=name, list_id="l", board_id="b", due=due, due_complete=done)


def test_group_of() -> None:
    assert group_of(card("a", -30), NOW) == "Overdue"
    assert group_of(card("b", -2), NOW) == "Today"  # earlier today is not overdue yet
    assert group_of(card("c", 8), NOW) == "Today"
    assert group_of(card("d", 24 * 6), NOW) == "This week"
    assert group_of(card("e", 24 * 7), NOW) == "Later"
    assert group_of(card("f", None), NOW) == "No due date"
    assert group_of(card("g", -30, done=True), NOW) == "Done"


def test_agenda_order() -> None:
    groups = agenda([card("later", 24 * 30), card("soon", 24 * 2), card("sooner", 24), card("none", None)], NOW)
    assert [(name, [c.name for c in cards]) for name, cards in groups] == [
        ("This week", ["sooner", "soon"]),
        ("Later", ["later"]),
        ("No due date", ["none"]),
    ]
