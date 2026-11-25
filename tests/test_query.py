from datetime import UTC, datetime

import pytest

from tui_trello import query
from tui_trello.backend import demo
from tui_trello.backend.demo import DemoBackend
from tui_trello.query import CardQuery


def freeze_clock(monkeypatch, moment: datetime) -> None:
    """Make the demo data and the query read the same fixed time."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(demo, "datetime", Frozen)
    monkeypatch.setattr(query, "datetime", Frozen)


@pytest.fixture
async def snapshot(monkeypatch):
    freeze_clock(monkeypatch, datetime(2031, 5, 17, 23, 30, tzinfo=UTC))  # late in the UTC day
    return await DemoBackend().board_snapshot("b-product")


@pytest.mark.parametrize(("query", "expected"), [
    ("", 12),
    ("palette", 1),
    ("#bug", 2),
    ("#bug #blocked", 1),
    ("@ada", 6),
    ("@grace #feat", 2),
    ("list:doing", 2),
    ("!overdue", 1),
    ("!due list:inbox", 0),
])
def test_filter(snapshot, query: str, expected: int) -> None:
    assert len(CardQuery.parse(query).filter(snapshot)) == expected
