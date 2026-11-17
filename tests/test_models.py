from datetime import datetime, timezone

from tui_trello.models import Card, Comment


def test_card_from_api() -> None:
    card = Card.from_api({
        "id": "c1",
        "name": "Fix login",
        "idList": "l1",
        "idBoard": "b1",
        "desc": None,
        "labels": [{"id": "lb1", "name": "bug", "color": "red_dark"}],
        "idMembers": ["m1"],
        "due": "2026-11-20T17:00:00.000Z",
        "badges": {"comments": 2, "checkItems": 4, "checkItemsChecked": 1},
    })
    assert card.desc == ""
    assert card.labels[0].rich_colour == "red"
    assert card.due == datetime(2026, 11, 20, 17, tzinfo=timezone.utc)
    assert card.comment_count == 2
    assert card.checklist == (1, 4)


def test_comment_from_api() -> None:
    comment = Comment.from_api({
        "id": "a1",
        "date": "2026-11-16T09:00:00.000Z",
        "memberCreator": {"fullName": "Ada Lovelace"},
        "data": {"text": "Looks good"},
    })
    assert (comment.author, comment.text) == ("Ada Lovelace", "Looks good")
