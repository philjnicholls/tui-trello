from datetime import datetime, timezone

from tui_trello.models import Attachment, Card, CheckItem, Checklist, Comment, checklist_badge


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
    assert card.due == datetime(2026, 11, 20, 17, tzinfo=timezone.utc)
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
