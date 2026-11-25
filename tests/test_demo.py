from datetime import UTC, datetime, timedelta

from tui_trello.backend import demo
from tui_trello.backend.demo import DemoBackend


async def test_all_the_dates_come_from_one_base_time(monkeypatch) -> None:
    base = datetime(2020, 3, 4, 9, tzinfo=UTC)
    calls: list[int] = []
    monkeypatch.setattr(demo, "today_at_nine", lambda: calls.append(1) or base)
    backend = DemoBackend()
    assert len(calls) == 1
    snapshot = await backend.board_snapshot("b-product")
    assert snapshot.cards[0].last_activity == base
    assert snapshot.cards[1].last_activity == base - timedelta(days=1)
    commented = next(c for c in snapshot.cards if c.comment_count >= 2)
    comments = await backend.comments(commented.id)
    assert [c.date for c in comments][:2] == [base, base - timedelta(hours=3)]
    assert [c.date for c in comments] == [base - timedelta(hours=3 * i) for i in range(len(comments))]  # going back
    archived = backend._archived["b-product"][0]
    assert archived.last_activity == base - timedelta(days=30)
    due_today = next(c for c in snapshot.cards if c.due and c.due.date() == base.date())
    assert due_today.due == base.replace(hour=23, minute=59)


async def test_attachments_are_dated_and_returned() -> None:
    backend = DemoBackend()
    snapshot = await backend.board_snapshot("b-product")
    attachments = [a for card in snapshot.cards for a in await backend.attachments(card.id)]
    assert attachments and all(a.date is not None and a.url for a in attachments)
    assert any(a.is_upload for a in attachments) and any(not a.is_upload for a in attachments)
