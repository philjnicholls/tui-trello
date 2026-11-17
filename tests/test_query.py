import pytest

from tui_trello.backend.demo import DemoBackend
from tui_trello.query import CardQuery


@pytest.fixture
async def snapshot():
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
