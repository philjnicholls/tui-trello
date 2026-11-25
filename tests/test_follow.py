"""Following a link to a card, on the real `TrelloBackend` over a fake transport, so the tests see what Trello sends,
`closed` included."""

import asyncio

import httpx
import pytest

from conftest import bearer_auth
from tui_trello.backend.trello import TrelloBackend
from tui_trello.config import Settings
from tui_trello.ui import follow
from tui_trello.ui.app import TrelloApp
from tui_trello.ui.screens.card import CardScreen

URL = "https://trello.com/c/Xy12Zw34"
DESC = f"original ticket: [{URL}]({URL} \"smartCard-inline\")"
OPEN_CARD = {"id": "c1", "name": "Consolidating", "idList": "l1", "idBoard": "b1", "desc": DESC,
             "url": "https://trello.com/c/Qr56St78/duplicate-report", "badges": {"comments": 2}}
LINKED = {"id": "c2", "name": "original ticket", "idList": "l1", "idBoard": "b1", "closed": True,
          "list": {"id": "l1", "closed": False}, "url": "https://trello.com/c/Xy12Zw34/first-report"}
OPEN_CARD_IN_ARCHIVED_LIST = {"closed": False, "idList": "l9", "list": {"id": "l9", "closed": True}}
LIST = {"id": "l1", "name": "Doing", "idBoard": "b1", "pos": 1}
PAYLOADS = {
    "/1/members/me": {"id": "me", "fullName": "Phil N", "username": "phil"},
    "/1/members/me/boards": [{"id": "b1", "name": "Work", "url": "https://trello.com/b/WWWW1111/work",
                              "lists": [LIST]}],
    "/1/members/me/cards": [],
    "/1/members/me/notifications": [],
    "/1/boards/b1": {"id": "b1", "name": "Work", "url": "https://trello.com/b/WWWW1111/work"},
    "/1/boards/b1/lists": [LIST],
    "/1/boards/b1/cards": [OPEN_CARD],
    "/1/boards/b1/members": [],
    "/1/boards/b1/labels": [],
    "/1/cards/c1/actions": [],
}


def trello_app(extra: dict, requests: list[str], hold: asyncio.Event | None = None,
               arrived: asyncio.Event | None = None) -> TrelloApp:
    """The app on a Trello that answers from PAYLOADS | extra (a (status, body) pair answers with that status; a
    function is called for its body), and records each request path. A request for the linked card sets `arrived`,
    then waits for `hold`, if given. As Trello does, a card carries its "list" only when asked with `list=true`."""
    payloads = PAYLOADS | extra

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/1/cards/Xy12Zw34":
            if arrived:
                arrived.set()
            if hold:
                await hold.wait()
        answer = payloads.get(request.url.path, {})
        status, body = answer if isinstance(answer, tuple) else (200, answer)
        if callable(body):
            body = body()
        if isinstance(body, dict) and "list" in body:
            params = request.url.params
            if params.get("list") != "true":
                body = {k: v for k, v in body.items() if k != "list"}
            else:
                wanted = params.get("list_fields", "id").split(",")
                body = body | {"list": {k: v for k, v in body["list"].items() if k in wanted or k == "id"}}
        return httpx.Response(status, json=body)

    backend = TrelloBackend(bearer_auth(), transport=httpx.MockTransport(handler))
    return TrelloApp(backend, Settings(default_board="b1"))


async def settle(pilot) -> None:
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def on_card(app: TrelloApp, pilot, requests: list[str]) -> None:
    """Open c1 and clear the record, so it holds only what a follow does."""
    await settle(pilot)
    app.open_card("c1")
    await settle(pilot)
    requests.clear()


def toasts(app: TrelloApp) -> list[tuple[str, str, str]]:
    return [(n.message, n.severity, n.title) for n in app._notifications]


async def test_archived_card_on_the_open_board_is_named_without_a_reload() -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": LINKED}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        assert requests == ["/1/cards/Xy12Zw34"]
        [(message, severity, _)] = toasts(app)
        assert severity == "warning" and message.startswith("“original ticket” is archived.")
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == "c1"
        assert app.following == ""


async def test_card_in_an_archived_list_is_named_without_a_reload() -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": LINKED | OPEN_CARD_IN_ARCHIVED_LIST}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        assert requests == ["/1/cards/Xy12Zw34"]
        [(message, severity, _)] = toasts(app)
        assert severity == "warning" and message.startswith("“original ticket” is in an archived list.")


OTHER_BOARD = {"/1/boards/b2": {"id": "b2", "name": "Other"}, "/1/boards/b2/lists": [], "/1/boards/b2/cards": [],
               "/1/boards/b2/members": [], "/1/boards/b2/labels": []}


async def test_archived_card_on_another_board_loads_nothing() -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": LINKED | {"idBoard": "b2"}} | OTHER_BOARD, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        assert requests == ["/1/cards/Xy12Zw34"]
        assert app.store.snapshot.board.id == "b1"
        [(message, severity, _)] = toasts(app)
        assert severity == "warning" and message.startswith("“original ticket” is archived.")


async def test_card_in_an_archived_list_on_another_board_loads_nothing() -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": LINKED | OPEN_CARD_IN_ARCHIVED_LIST | {"idBoard": "b2"}} | OTHER_BOARD,
                     requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        assert requests == ["/1/cards/Xy12Zw34"]
        assert app.store.snapshot.board.id == "b1"
        [(message, severity, _)] = toasts(app)
        assert severity == "warning" and message.startswith("“original ticket” is in an archived list.")


@pytest.mark.parametrize(("status", "body", "words"), [
    (401, "unauthorized card permission requested", "You don't have access"),
    (404, "The requested resource was not found.", "404"),
])
async def test_card_on_a_board_without_access(status: int, body: str, words: str) -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": (status, body)}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        [(message, severity, title)] = toasts(app)
        assert severity == "error" and title == "Could not follow the link" and words in message
        assert not [path for path in requests if path.startswith("/1/boards")]
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == "c1"
        assert app.following == ""


async def test_clicks_during_a_follow_are_dropped_and_the_next_one_works() -> None:
    requests: list[str] = []
    hold = asyncio.Event()
    arrived = asyncio.Event()
    app = trello_app({"/1/cards/Xy12Zw34": LINKED}, requests, hold, arrived)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        for _ in range(3):
            app.action_follow_link(URL)
            await pilot.pause()
        await asyncio.wait_for(arrived.wait(), 5)
        assert requests == ["/1/cards/Xy12Zw34"] and app.following == URL
        hold.set()
        await settle(pilot)
        assert len(toasts(app)) == 1 and app.following == ""
        app.action_follow_link(URL)
        await settle(pilot)
        assert requests == ["/1/cards/Xy12Zw34"] * 2
        assert len(toasts(app)) == 2 and app.following == ""


async def test_open_card_link_still_opens() -> None:
    """The linked card isn't on the loaded board, so it is fetched, found open, and its board reloaded for it."""
    requests: list[str] = []
    linked = LINKED | {"closed": False}
    loads = []

    def board_cards() -> list[dict]:
        loads.append(1)
        return [OPEN_CARD] if len(loads) == 1 else [OPEN_CARD, linked]

    app = trello_app({"/1/cards/Xy12Zw34": linked, "/1/boards/b1/cards": board_cards}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await follow.follow(app, URL)
        await settle(pilot)
        assert "/1/cards/Xy12Zw34" in requests and len(loads) == 2
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == "c2"
        assert not toasts(app)


async def test_card_in_a_list_newer_than_the_board_opens_after_a_reload() -> None:
    requests: list[str] = []
    new_list = {"id": "l2", "name": "New", "idBoard": "b1", "pos": 2}
    linked = LINKED | {"closed": False, "idList": "l2", "list": {"id": "l2", "closed": False}}
    loads = {"cards": 0, "lists": 0}  # each handler counts its own requests, whatever order a load makes them in

    def board_cards() -> list[dict]:
        loads["cards"] += 1
        return [OPEN_CARD] if loads["cards"] == 1 else [OPEN_CARD, linked]

    def board_lists() -> list[dict]:
        loads["lists"] += 1
        return [LIST] if loads["lists"] == 1 else [LIST, new_list]

    app = trello_app({"/1/cards/Xy12Zw34": linked, "/1/boards/b1/cards": board_cards,
                      "/1/boards/b1/lists": board_lists}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        assert loads == {"cards": 2, "lists": 2}
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == "c2"
        assert not toasts(app)


async def test_archived_toast_is_plain_text_and_stays_8_seconds() -> None:
    requests: list[str] = []
    app = trello_app({"/1/cards/Xy12Zw34": LINKED | {"name": "a [b]b[/b]"}}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        [note] = app._notifications
        assert "a [b]b[/b]" in note.message and note.markup is False and note.timeout == 8


@pytest.mark.parametrize(
    ("extra", "words"), [({}, "is archived."), (OPEN_CARD_IN_ARCHIVED_LIST, "is in an archived list.")])
async def test_archived_toast_shows_the_cards_emoji_and_keeps_markup_off(extra: dict, words: str) -> None:
    requests: list[str] = []
    named = LINKED | extra | {"name": ":rocket: [bold]ticket[/bold]"}
    app = trello_app({"/1/cards/Xy12Zw34": named}, requests)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_card(app, pilot, requests)
        await follow.follow(app, URL)
        await settle(pilot)
        [(message, _, _)] = toasts(app)
        assert message.startswith(f"“🚀 [bold]ticket[/bold]” {words}")
        assert [n.markup for n in app._notifications] == [False]
