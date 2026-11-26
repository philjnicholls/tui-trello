from datetime import UTC, datetime

from tui_trello.models import Attachment, Card, CheckItem, Checklist, Comment, Notification, checklist_badge


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
        "badges": {"comments": 2, "checkItems": 4, "checkItemsChecked": 1, "attachments": 3},
    })
    assert card.desc == ""
    assert card.labels[0].rich_colour == "red"
    assert card.due == datetime(2026, 11, 20, 17, tzinfo=UTC)
    assert card.comment_count == 2
    assert card.checklist == (1, 4)
    assert card.attachment_count == 3


def test_attachment_from_api() -> None:
    upload = Attachment.from_api({"id": "at1", "name": "photo.jpg", "isUpload": True, "bytes": 115146,
                                  "mimeType": "image/jpeg", "fileName": "photo_1.jpg", "date": "2026-11-16T09:00:00Z",
                                  "url": "https://trello.com/1/cards/c1/attachments/at1/download/photo_1.jpg"})
    assert (upload.is_upload, upload.size, upload.file_name) == (True, 115146, "photo_1.jpg")
    link = Attachment.from_api({"id": "at2", "name": "", "isUpload": False, "bytes": None,
                                "url": "https://example.com/pr/42"})
    assert (link.name, link.size, link.is_upload) == ("https://example.com/pr/42", 0, False)


def test_comment_from_api() -> None:
    comment = Comment.from_api({
        "id": "a1",
        "date": "2026-11-16T09:00:00.000Z",
        "memberCreator": {"fullName": "Ada Lovelace"},
        "data": {"text": "Looks good"},
    })
    assert (comment.author, comment.text) == ("Ada Lovelace", "Looks good")


def test_checklist_from_api() -> None:
    checklist = Checklist.from_api({"id": "cl1", "name": "Tasks", "checkItems": [
        {"id": "i2", "name": "Second", "state": "incomplete", "pos": 2},
        {"id": "i1", "name": "First", "state": "complete", "pos": 1},
    ]})
    assert [item.name for item in checklist.items] == ["First", "Second"]
    assert checklist.done == 1
    ticked = checklist.with_item(CheckItem("i2", "Second", checked=True, pos=2))
    added = ticked.with_item(CheckItem("i3", "Third"))
    assert checklist_badge([added, Checklist("cl2", "Empty")]) == (2, 3)


def test_comment_from_api_keeps_the_username() -> None:
    comment = Comment.from_api({"id": "a1", "data": {"text": "hi"},
                                "memberCreator": {"fullName": "Grace Hopper", "username": "grace"}})
    assert (comment.author, comment.author_username) == ("Grace Hopper", "grace")


def test_reaction_notification_from_api() -> None:
    """The reactions come with every reaction on the comment; the notification is about its creator's."""
    emoji = {"unified": "1F64F", "native": "🙏", "shortName": "pray"}
    n = Notification.from_api({
        "id": "n1", "type": "reactionAdded", "unread": True, "date": "2026-11-19T11:26:59.413Z",
        "idMemberCreator": "m2", "memberCreator": {"id": "m2", "fullName": "Grace Hopper", "username": "grace"},
        "data": {"card": {"id": "c1", "name": "Plan"}, "board": {"id": "b1", "name": "Dev"}, "text": "Ship it?"},
        "reactions": [{"id": "r1", "idMember": "m2", "emoji": emoji},
                      {"id": "r2", "idMember": "m3", "emoji": {**emoji, "native": "👍", "shortName": "+1"}}],
    })
    assert (n.reactions, n.creator_username, n.is_comment) == (("🙏",), "grace", False)


def test_comment_author_id() -> None:
    comment = Comment.from_api({"id": "a1", "data": {"text": "hi"}, "idMemberCreator": "m1",
                                "memberCreator": {"id": "m9", "fullName": "Ada Lovelace"}})
    assert comment.author_id == "m1"
    nested = Comment.from_api({"id": "a2", "data": {"text": "hi"}, "memberCreator": {"id": "m9", "fullName": "Ada"}})
    assert nested.author_id == "m9"
    assert Comment.from_api({"id": "a3", "data": {"text": "hi"}}).author_id == ""


def test_card_from_api_reads_subscribed() -> None:
    base = {"id": "c1", "name": "Fix login", "idList": "l1", "idBoard": "b1"}
    assert Card.from_api({**base, "subscribed": True}).subscribed is True
    assert Card.from_api(base).subscribed is False


def test_work_snapshot_add_card() -> None:
    from tui_trello.models import Member, WorkSnapshot

    work = WorkSnapshot(Member("m1", "Ada Lovelace", "ada"), [], {}, {})
    card = Card(id="c1", name="Fix login", list_id="l1", board_id="b1")
    assert work.card("c1") is None
    work.add_card(card)
    assert work.card("c1") == card
