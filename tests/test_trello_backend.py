import httpx
import pytest

from tui_trello.auth import TokenAuth
from tui_trello.backend import BackendError
from tui_trello.backend.trello import TrelloBackend

PAYLOADS = {
    "/1/boards/b1": {"id": "b1", "name": "Roadmap"},
    "/1/boards/b1/lists": [{"id": "l2", "name": "Done", "pos": 2}, {"id": "l1", "name": "To do", "pos": 1}],
    "/1/boards/b1/cards": [{"id": "c1", "name": "Card", "idList": "l1", "idBoard": "b1"},
                           {"id": "c2", "name": "In an archived list", "idList": "l9", "idBoard": "b1"}],
    "/1/boards/b1/members": [{"id": "m1", "fullName": "Ada Lovelace", "username": "ada"}],
    "/1/boards/b1/labels": [{"id": "lb1", "name": "bug", "color": "red"}],
    "/1/cards/c1": {"id": "c1", "name": "Card", "idList": "l2", "idBoard": "b1"},
    "/1/cards/c1/checklists": [{"id": "cl1", "name": "Tasks", "pos": 1, "checkItems": [
        {"id": "i1", "name": "Write it", "state": "incomplete", "pos": 1}]}],
    "/1/cards/c1/checkItem/i1": {"id": "i1", "name": "Write it", "state": "complete", "pos": 1},
    "/1/checklists/cl1/checkItems": {"id": "i2", "name": "Test it", "state": "incomplete", "pos": 2},
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
