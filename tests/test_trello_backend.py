import httpx
import pytest

from tui_trello.models import Attachment

from tui_trello.auth import TokenAuth
from tui_trello.backend import BackendError
from tui_trello.backend.trello import CARD_FIELDS, TrelloBackend

PAYLOADS = {
    "/1/boards/b1": {"id": "b1", "name": "Roadmap"},
    "/1/boards/b1/lists": [{"id": "l2", "name": "Done", "pos": 2}, {"id": "l1", "name": "To do", "pos": 1}],
    "/1/boards/b1/cards": [{"id": "c1", "name": "Card", "idList": "l1", "idBoard": "b1"},
                           {"id": "c2", "name": "In an archived list", "idList": "l9", "idBoard": "b1"}],
    "/1/boards/b1/members": [{"id": "m1", "fullName": "Ada Lovelace", "username": "ada"}],
    "/1/boards/b1/labels": [{"id": "lb1", "name": "bug", "color": "red"}],
    "/1/cards/c1": {"id": "c1", "name": "Card", "idList": "l2", "idBoard": "b1"},
    "/1/cards": {"id": "c3", "name": "New one", "desc": "Why", "idList": "l1", "idBoard": "b1",
                 "url": "https://trello.com/c/c3"},
    "/1/cards/c1/checklists": [{"id": "cl1", "name": "Tasks", "pos": 1, "checkItems": [
        {"id": "i1", "name": "Write it", "state": "incomplete", "pos": 1}]}],
    "/1/cards/c1/checkItem/i1": {"id": "i1", "name": "Write it", "state": "complete", "pos": 1},
    "/1/checklists/cl1/checkItems": {"id": "i2", "name": "Test it", "state": "incomplete", "pos": 2},
    "/1/cards/c1/actions": [
        {"id": "a1", "type": "commentCard", "date": "2026-11-18T09:00:00.000Z", "data": {"text": "Ship it?"},
         "memberCreator": {"fullName": "Grace Hopper"}, "reactions": [
             {"id": "r1", "idMember": "m1", "idModel": "a1", "idEmoji": "1F44D", "member": {"fullName": "Ada Lovelace"},
              "emoji": {"unified": "1F44D", "native": "👍", "shortName": "+1", "skinVariation": None}}]},
    ],
    "/1/actions/a1/reactions": {"id": "r2", "idMember": "m1", "idEmoji": "1F389",
                                "emoji": {"unified": "1F389", "native": "🎉", "shortName": "tada"}},
    "/1/cards/c1/attachments": [{"id": "at1", "name": "notes.txt", "isUpload": True, "bytes": 5,
                                 "url": "https://trello.com/1/cards/c1/attachments/at1/download/notes.txt"}],
    "/1/members/me/notifications": [
        {"id": "n1", "type": "mentionedOnCard", "unread": True, "date": "2026-11-18T09:00:00.000Z",
         "memberCreator": {"fullName": "Grace Hopper"},
         "data": {"card": {"id": "c1", "name": "Card"}, "board": {"id": "b1", "name": "Roadmap"}, "text": "@ada hi"}},
        {"id": "n2", "type": "addedToBoard", "unread": False, "date": "2026-11-17T09:00:00.000Z",
         "memberCreator": {"fullName": "Alan Turing"}, "data": {"board": {"id": "b1", "name": "Roadmap"}}},
    ],
}


def make_backend(requests: list[httpx.Request], status: int = 200) -> TrelloBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=PAYLOADS.get(request.url.path, {}))

    return TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(handler))


async def test_board_snapshot() -> None:
    requests: list[httpx.Request] = []
    snapshot = await make_backend(requests).board_snapshot("b1")
    assert [lst.name for lst in snapshot.lists] == ["To do", "Done"]
    assert snapshot.cards_in("l1")[0].name == "Card"
    assert [c.id for c in snapshot.cards] == ["c1"]  # c2's list is archived
    assert snapshot.members["m1"].initials == "AL"
    assert all(r.url.params["key"] == "KEY" and r.url.params["token"] == "TOKEN" for r in requests)


async def test_move_card() -> None:
    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    snapshot = await backend.board_snapshot("b1")
    moved = await backend.move_card(snapshot.cards[0], "l2")
    assert moved.list_id == "l2"
    assert requests[-1].method == "PUT"
    assert requests[-1].url.params["idList"] == "l2"


async def test_checklists() -> None:
    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    [checklist] = await backend.checklists("c1")
    assert requests[-1].url.params["checkItem_fields"] == "name,state,pos"
    ticked = await backend.set_check_item("c1", checklist.items[0], True)
    assert ticked.checked
    assert (requests[-1].method, requests[-1].url.params["state"]) == ("PUT", "complete")
    added = await backend.add_check_item("cl1", "Test it")
    assert added.name == "Test it" and not added.checked
    assert (requests[-1].method, requests[-1].url.params["name"]) == ("POST", "Test it")


async def test_comment_reactions() -> None:
    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    [comment] = await backend.comments("c1")
    assert requests[-1].url.params["reactions"] == "true"
    assert comment.reaction_counts("m1") == [("+1", "👍", 1, True)]
    added = await backend.add_reaction("a1", "tada")
    assert (added.short_name, added.native, added.member_id) == ("tada", "🎉", "m1")
    assert (requests[-1].method, requests[-1].read()) == ("POST", b'{"shortName":"tada"}')
    await backend.remove_reaction("a1", "r1")
    assert (requests[-1].method, requests[-1].url.path) == ("DELETE", "/1/actions/a1/reactions/r1")


async def test_attachments(tmp_path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        listed = PAYLOADS["/1/cards/c1/attachments"]
        return httpx.Response(200, json=listed if request.method == "GET" else listed[0])

    backend = TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(handler))
    [attachment] = await backend.attachments("c1")
    assert (attachment.name, attachment.is_upload) == ("notes.txt", True)
    assert "isUpload" in requests[-1].url.params["fields"]
    path = tmp_path / "plan.pdf"
    path.write_bytes(b"%PDF-1.7 plan")
    await backend.attach_file("c1", path)
    upload = requests[-1]
    assert (upload.method, upload.url.path, upload.url.params["name"]) == ("POST", "/1/cards/c1/attachments", "plan.pdf")
    assert upload.headers["content-type"].startswith("multipart/form-data")
    body = upload.read()
    assert b'name="file"; filename="plan.pdf"' in body and b"%PDF-1.7 plan" in body and b"application/pdf" in body
    await backend.attach_link("c1", "https://example.com/pr/42")
    assert requests[-1].url.params["url"] == "https://example.com/pr/42" and "name" not in requests[-1].url.params


async def test_download_with_a_token_login(tmp_path) -> None:
    """Trello's download links want the key and token in an OAuth header, not the query string."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"hello")

    backend = TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(handler))
    attachment = Attachment("at1", "notes.txt", "https://trello.com/1/cards/c1/attachments/at1/download/notes.txt",
                            is_upload=True)
    await backend.download_attachment(attachment, tmp_path / "notes.txt")
    assert (tmp_path / "notes.txt").read_bytes() == b"hello"
    assert seen[0].headers["authorization"] == 'OAuth oauth_consumer_key="KEY", oauth_token="TOKEN"'


async def test_download_refused_leaves_no_file(tmp_path) -> None:
    backend = TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text="unauthorized permission requested")))
    attachment = Attachment("at1", "notes.txt", "https://trello.com/1/cards/c1/attachments/at1/download/notes.txt",
                            is_upload=True)
    with pytest.raises(BackendError, match="login --token"):
        await backend.download_attachment(attachment, tmp_path / "notes.txt")
    assert not (tmp_path / "notes.txt").exists()


async def test_no_permission() -> None:
    backend = TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(
        lambda request: httpx.Response(401, text="unauthorized permission requested")))
    with pytest.raises(BackendError, match="don't have access"):
        await backend.comments("c1")


async def test_unauthorised() -> None:
    with pytest.raises(BackendError, match="401"):
        await make_backend([], status=401).boards()


async def test_notifications() -> None:
    from tui_trello.ui.render import notification_summary

    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    mention, board = await backend.notifications()
    assert "reactions" in requests[-1].url.params["fields"].split(",")  # not sent unless asked for by name
    assert (mention.card_id, mention.board_name, mention.text, mention.unread) == ("c1", "Roadmap", "@ada hi", True)
    assert notification_summary(mention) == "Grace Hopper mentioned you on Card"
    assert notification_summary(board) == "Alan Turing added you to the board Roadmap"
    await backend.mark_notifications_read(["n1"])
    assert (requests[-1].method, requests[-1].url.path, requests[-1].url.params["unread"]) == (
        "PUT", "/1/notifications/n1", "false")
    await backend.mark_all_notifications_read()
    assert (requests[-1].method, requests[-1].url.path) == ("POST", "/1/notifications/all/read")


async def test_marking_read_without_the_scope() -> None:
    """A login from before write:member:trello was asked for: Trello says 403, the app says log in again."""
    backend = TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(
        lambda request: httpx.Response(403, text="unauthorized notification requested.")))
    with pytest.raises(BackendError, match="tui-trello login"):
        await backend.mark_notifications_read(["n1"])


async def test_set_description_sends_the_text_in_the_body() -> None:
    import json

    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    snapshot = await backend.board_snapshot("b1")
    long = "word " * 3000  # too long for a URL
    await backend.set_description(snapshot.cards[0], long)
    assert requests[-1].method == "PUT" and "desc" not in requests[-1].url.params
    assert json.loads(requests[-1].content) == {"desc": long}


async def test_create_card() -> None:
    import json

    requests: list[httpx.Request] = []
    card = await make_backend(requests).create_card("l1", "New one", "Why")
    assert (requests[-1].method, requests[-1].url.path) == ("POST", "/1/cards")
    assert json.loads(requests[-1].content) == {"idList": "l1", "name": "New one", "desc": "Why", "pos": "bottom"}
    assert (card.id, card.name, card.desc, card.list_id, card.board_id) == ("c3", "New one", "Why", "l1", "b1")


async def test_create_card_without_a_description() -> None:
    import json

    requests: list[httpx.Request] = []
    await make_backend(requests).create_card("l1", "New one")
    assert json.loads(requests[-1].content) == {"idList": "l1", "name": "New one", "pos": "bottom"}


def failing_with(error: Exception) -> TrelloBackend:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return TrelloBackend(TokenAuth("KEY", "TOKEN"), transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(("backend", "unsure"), [
    (failing_with(httpx.ConnectError("refused")), False),  # never sent
    (failing_with(httpx.ConnectTimeout("no answer")), False),
    (failing_with(httpx.PoolTimeout("no free connection")), False),
    (failing_with(httpx.UnsupportedProtocol("no scheme")), False),
    (failing_with(httpx.LocalProtocolError("bad header")), False),
    (failing_with(httpx.ProxyError("proxy refused")), False),
    (failing_with(httpx.InvalidURL("bad URL")), False),
    (failing_with(httpx.ReadTimeout("slow")), True),  # sent: Trello may have made the card
    (failing_with(httpx.RemoteProtocolError("dropped")), True),
    (failing_with(httpx.WriteTimeout("half sent")), True),
    (make_backend([], status=502), True),
    (make_backend([], status=400), False),
])
async def test_create_card_outcome_unknown(backend: TrelloBackend, unsure: bool) -> None:
    with pytest.raises(BackendError) as caught:
        await backend.create_card("l1", "New one")
    assert getattr(caught.value, "unsure", None) is unsure


async def test_card_and_board_by_short_link() -> None:
    requests: list[httpx.Request] = []
    backend = make_backend(requests)
    PAYLOADS["/1/cards/Xy12Zw34"] = {"id": "c9", "name": "Linked", "idList": "l1", "idBoard": "b1"}
    PAYLOADS["/1/boards/AbCd1234"] = {"id": "b1", "name": "Roadmap", "url": "https://trello.com/b/AbCd1234/roadmap"}
    try:
        assert (await backend.card("Xy12Zw34")).id == "c9"
        assert (await backend.board("AbCd1234")).name == "Roadmap"
    finally:
        del PAYLOADS["/1/cards/Xy12Zw34"], PAYLOADS["/1/boards/AbCd1234"]
    card_request, board_request = requests
    assert card_request.url.path == "/1/cards/Xy12Zw34" and card_request.url.params["fields"] == CARD_FIELDS
    assert board_request.url.path == "/1/boards/AbCd1234"


async def test_unknown_short_link_is_an_error() -> None:
    with pytest.raises(BackendError, match="404"):
        await make_backend([], status=404).card("nope")
    with pytest.raises(BackendError, match="404"):
        await make_backend([], status=404).board("nope")
