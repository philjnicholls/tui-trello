import asyncio
import json
import stat
import time
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from conftest import bearer_auth
from tui_trello.auth import (
    LoginError,
    OAuth2Auth,
    OAuth2Tokens,
    load_credentials,
    login_oauth2,
    pkce_pair,
    retired_login,
    save_credentials,
    whoami,
)
from tui_trello.backend import BackendError

FRESH = OAuth2Tokens("ACCESS", "REFRESH", time.time() + 3600)
EXPIRED = OAuth2Tokens("OLD", "REFRESH", time.time() - 10)


def test_credentials_saved_private(tmp_path) -> None:
    path = save_credentials(FRESH, tmp_path / "credentials.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_credentials(path) == FRESH


def test_credentials_resaved_private(tmp_path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{}")
    path.chmod(0o644)
    save_credentials(FRESH, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["credentials.json"]  # no temporary file left behind


@pytest.mark.parametrize("content", ["", "{\"access_tok", '{"access_token": "A"}', "[]"])
def test_corrupt_credentials_mean_logged_out(tmp_path, content) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(content)
    assert load_credentials(path) is None


def test_pkce_pair() -> None:
    import base64
    import hashlib

    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class Unread(httpx.AsyncByteStream):
    """A body that has to be read, as from the network (MockTransport's responses are otherwise read already)."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self):
        yield self.body


def streamed(response: httpx.Response) -> httpx.Response:
    return httpx.Response(response.status_code, headers=response.headers, stream=Unread(response.content))


class FakeTrello:
    """api.trello.com and auth.atlassian.com/oauth/token, enough for OAuth2Auth."""

    def __init__(self) -> None:
        self.valid = {"ACCESS"}
        self.refreshes = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        return streamed(self.respond(request))

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            body = json.loads(request.content)
            if body.get("refresh_token") != "REFRESH":
                return httpx.Response(403, json={"error": "unauthorized_client"})
            self.refreshes += 1
            access = f"ACCESS{self.refreshes}"
            self.valid = {access}
            return httpx.Response(200, json={"access_token": access, "refresh_token": "REFRESH", "expires_in": 3600})
        if request.headers.get("Authorization", "").removeprefix("Bearer ") in self.valid:
            return httpx.Response(200, json={"id": "m1", "fullName": "Ada Lovelace", "username": "ada"})
        return httpx.Response(401, text="invalid token")


async def get_me(auth: httpx.Auth, trello: FakeTrello, n: int = 1) -> list[httpx.Response]:
    async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(trello)) as http:
        return await asyncio.gather(*(http.get("https://api.trello.com/1/members/me") for _ in range(n)))


async def test_oauth2_sends_bearer() -> None:
    trello = FakeTrello()
    [response] = await get_me(OAuth2Auth(FRESH, on_refresh=lambda _: None), trello)
    assert response.status_code == 200 and trello.refreshes == 0


async def test_oauth2_refreshes_once_for_concurrent_requests() -> None:
    saved: list[OAuth2Tokens] = []
    trello = FakeTrello()
    responses = await get_me(OAuth2Auth(EXPIRED, on_refresh=saved.append), trello, n=5)
    assert all(r.status_code == 200 for r in responses)
    assert trello.refreshes == 1
    assert saved[0].access_token == "ACCESS1"


async def test_oauth2_refreshes_on_401() -> None:
    trello = FakeTrello()
    trello.valid = {"SOMETHING ELSE"}  # the access token was revoked early
    [response] = await get_me(OAuth2Auth(FRESH, on_refresh=lambda _: None), trello)
    assert response.status_code == 200 and trello.refreshes == 1


async def test_oauth2_refreshes_once_for_a_persistent_401() -> None:
    # Trello answers 401 for things the user can't see; refreshing again wouldn't help.
    class NoAccess(FakeTrello):
        def respond(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/oauth/token":
                return super().respond(request)
            return httpx.Response(401, text="unauthorized permission requested")

    trello = NoAccess()
    auth = OAuth2Auth(FRESH, on_refresh=lambda _: None)
    for _ in range(3):
        [response] = await get_me(auth, trello)
        assert response.status_code == 401
    assert trello.refreshes == 1


async def test_oauth2_keeps_refresh_token_if_not_rotated() -> None:
    def atlassian(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return streamed(httpx.Response(200, json={"access_token": "NEW", "expires_in": 3600}))
        return streamed(httpx.Response(200, json={}))

    auth = OAuth2Auth(EXPIRED, on_refresh=lambda _: None)
    async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(atlassian)) as http:
        await http.get("https://api.trello.com/1/members/me")
    assert (auth.tokens.access_token, auth.tokens.refresh_token) == ("NEW", "REFRESH")


async def test_oauth2_failed_refresh() -> None:
    auth = OAuth2Auth(OAuth2Tokens("OLD", "REVOKED", time.time() - 10), on_refresh=lambda _: None)
    with pytest.raises(BackendError, match="login again|login` again"):
        await get_me(auth, FakeTrello())


async def test_login_oauth2_round_trip(unused_tcp_port: int) -> None:
    exchanged: list[dict] = []

    def atlassian(request: httpx.Request) -> httpx.Response:
        exchanged.append(json.loads(request.content))
        return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "expires_in": 3600})

    async def browser(url: str) -> None:
        # Stands in for the user clicking Accept: Atlassian redirects to our callback with a code and our state.
        query = dict(parse_qsl(urlsplit(url).query))
        assert query["code_challenge_method"] == "S256" and "offline_access" in query["scope"]
        async with httpx.AsyncClient() as http:
            stale = await http.get(query["redirect_uri"], params={"code": "C", "state": "wrong"})
            assert stale.status_code == 400
            done = await http.get(query["redirect_uri"], params={"code": "C", "state": query["state"]})
            assert "Logged in" in done.text

    tokens = await login_oauth2(port=unused_tcp_port, echo=lambda _: None, transport=httpx.MockTransport(atlassian),
                                open_browser=lambda url: asyncio.ensure_future(browser(url)))
    assert (tokens.access_token, tokens.refresh_token) == ("A", "R")
    assert exchanged[0]["grant_type"] == "authorization_code" and exchanged[0]["code"] == "C"
    assert exchanged[0]["code_verifier"] and "client_secret" not in exchanged[0]


async def test_login_oauth2_ignores_idle_connections(unused_tcp_port: int) -> None:
    # Browsers open spare connections that never send a request; they mustn't stop login finishing.
    async def browser(url: str) -> None:
        query = dict(parse_qsl(urlsplit(url).query))
        await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        async with httpx.AsyncClient() as http:
            await http.get(query["redirect_uri"], params={"code": "C", "state": query["state"]})

    def atlassian(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "expires_in": 3600})

    login = login_oauth2(port=unused_tcp_port, echo=lambda _: None, transport=httpx.MockTransport(atlassian),
                         open_browser=lambda url: asyncio.ensure_future(browser(url)))
    assert (await asyncio.wait_for(login, 5)).access_token == "A"


async def test_login_oauth2_unreachable(unused_tcp_port: int) -> None:
    async def browser(url: str) -> None:
        query = dict(parse_qsl(urlsplit(url).query))
        async with httpx.AsyncClient() as http:
            await http.get(query["redirect_uri"], params={"code": "C", "state": query["state"]})

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    with pytest.raises(LoginError, match="Could not reach"):
        await login_oauth2(port=unused_tcp_port, echo=lambda _: None, transport=httpx.MockTransport(offline),
                           open_browser=lambda url: asyncio.ensure_future(browser(url)))


async def test_login_oauth2_denied(unused_tcp_port: int) -> None:
    async def browser(url: str) -> None:
        query = dict(parse_qsl(urlsplit(url).query))
        async with httpx.AsyncClient() as http:
            await http.get(query["redirect_uri"], params={"error": "access_denied", "state": query["state"]})

    with pytest.raises(LoginError, match="access_denied"):
        await login_oauth2(port=unused_tcp_port, echo=lambda _: None,
                           open_browser=lambda url: asyncio.ensure_future(browser(url)))


async def test_whoami() -> None:
    assert await whoami(OAuth2Auth(FRESH, on_refresh=lambda _: None), httpx.MockTransport(FakeTrello())) \
        == "Ada Lovelace (@ada)"
    unauthorised = httpx.MockTransport(lambda request: httpx.Response(401, text="unauthorized"))
    with pytest.raises(LoginError, match="401"):
        await whoami(bearer_auth(), unauthorised)
    server_error = httpx.MockTransport(lambda request: httpx.Response(503, text="down"))
    with pytest.raises(LoginError, match="503"):
        await whoami(bearer_auth(), server_error)


def test_a_retired_login_is_recognised_not_loaded(tmp_path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"token": "T"}))
    assert load_credentials(path) is None
    assert retired_login(path)
    assert json.loads(path.read_text()) == {"token": "T"}  # left as it was: only a new login replaces it


def test_oauth_credentials_are_not_a_retired_login(tmp_path) -> None:
    path = save_credentials(FRESH, tmp_path / "credentials.json")
    assert not retired_login(path) and load_credentials(path) == FRESH
    for content in ("", "[]", '{"token": ""}', '{"access_token": "A", "token": "T"}', "{}"):
        path.write_text(content)
        assert not retired_login(path), content
    assert not retired_login(tmp_path / "missing.json")
