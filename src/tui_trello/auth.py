"""Trello authorisation: browser login, saved credentials, and httpx auth for API requests.

`tui-trello login` uses OAuth 2.0 with PKCE
(https://developer.atlassian.com/cloud/trello/guides/rest-api/oauth-2-getting-started/): it opens Atlassian's consent
page, which redirects to a one-shot server on 127.0.0.1 with a code; the code is swapped for an access token (1 hour)
and a refresh token (90 days, single use). `OAuth2Auth` sends the access token as a bearer token and refreshes it,
saving each new pair, so users log in once. tui-trello's OAuth client is public: no secret is involved.

The tokens are saved to `credentials.json` (mode 600) next to the config file.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import webbrowser
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from tui_trello.backend import BackendError
from tui_trello.config import config_path

# tui-trello's OAuth 2.0 client, on https://trello.com/power-ups/admin. Its callback URLs must include
# http://127.0.0.1:<oauth_port>/callback and its scopes must include SCOPES.
OAUTH_CLIENT_ID = "gGrXO7ZLRFrZ00UM9irqMjhBGAhIByaI"
OAUTH_AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
OAUTH_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
# write:member:trello is for marking notifications read: Trello refuses that with the board scopes alone, even
# through POST /cards/{id}/markAssociatedNotificationsRead, which its API reference says they cover.
SCOPES = "read:member:trello write:member:trello read:board:trello write:board:trello offline_access"

LOGIN_TIMEOUT = 300  # seconds to wait for the user to approve in the browser
REQUEST_LINE_TIMEOUT = 10  # seconds a connection to the callback server may take to send its request line
REFRESH_MARGIN = 60  # refresh this many seconds before the access token expires
DONE = "Logged in to Trello. You can close this tab and go back to the terminal."
RETIRED_LOGIN = ("Your saved Trello login used a login method tui-trello no longer supports (a pasted token). "
                 "Log in again in the browser: tui-trello login. Starting it now.")


class LoginError(Exception):
    pass


# -- credentials -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuth2Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # unix time

    @property
    def expiring(self) -> bool:
        return time.time() > self.expires_at - REFRESH_MARGIN

    @classmethod
    def from_response(cls, data: dict[str, Any], refresh_token: str = "") -> OAuth2Tokens:
        """`refresh_token` is the one to keep if the response doesn't rotate it."""
        return cls(data["access_token"], data.get("refresh_token") or refresh_token,
                   time.time() + int(data.get("expires_in", 3600)))


def credentials_path() -> Path:
    return config_path().with_name("credentials.json")


def load_credentials(path: Path | None = None) -> OAuth2Tokens | None:
    """The saved login, or None if there is none or the file is unreadable (the user logs in again)."""
    path = path or credentials_path()
    try:
        data = json.loads(path.read_text())
        return OAuth2Tokens(data["access_token"], data["refresh_token"], float(data["expires_at"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):  # missing, corrupt, or not an OAuth login
        return None


def retired_login(path: Path | None = None) -> bool:
    """True if the saved file is a pasted-token login from before tui-trello logged in with OAuth only."""
    path = path or credentials_path()
    try:
        data = json.loads(path.read_text())
        return bool(data.get("token")) and "access_token" not in data
    except (OSError, ValueError, AttributeError):
        return False


def save_credentials(credentials: OAuth2Tokens, path: Path | None = None) -> Path:
    """Write the credentials readable only by the user, atomically: a refresh token is single use, so a half-written
    file would mean logging in again."""
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".credentials-")  # mkstemp makes it mode 600
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(credentials), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise
    return path


def delete_credentials(path: Path | None = None) -> bool:
    path = path or credentials_path()
    if path.exists():
        path.unlink()
        return True
    return False


# -- request authentication --------------------------------------------------------------------------------------


class OAuth2Auth(httpx.Auth):
    """Bearer token auth that refreshes the access token when it is about to expire, or is rejected.

    Refresh tokens are single use and the backend sends requests concurrently, so refreshing happens under a lock,
    and a request that waited for the lock re-checks whether another one has already refreshed.

    Trello also answers 401 for things the user may not see (a board they were removed from), so a 401 refreshes at
    most once per access token: if the fresh token is refused too, the 401 goes back to the caller.

    Overriding `async_auth_flow` skips httpx's own reading of the flow's responses (`requires_response_body`), so the
    token responses are read here.
    """

    def __init__(self, tokens: OAuth2Tokens, *, client_id: str = OAUTH_CLIENT_ID,
                 on_refresh: Callable[[OAuth2Tokens], object] = save_credentials) -> None:
        self.tokens = tokens
        self.client_id = client_id
        self.on_refresh = on_refresh
        self._lock = asyncio.Lock()
        self._refreshed_for_401: OAuth2Tokens | None = None  # the tokens a 401 last refreshed to

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        raise RuntimeError("OAuth2Auth only supports httpx.AsyncClient")

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if self.tokens.expiring:
            async with self._lock:
                if self.tokens.expiring:
                    await self._refreshed((yield self._refresh_request()))
        used = self.tokens
        request.headers["Authorization"] = f"Bearer {used.access_token}"
        response = yield request
        if response.status_code == 401 and used is not self._refreshed_for_401:
            async with self._lock:
                if self.tokens is used:  # nobody refreshed while we waited for the lock
                    await self._refreshed((yield self._refresh_request()))
                    self._refreshed_for_401 = self.tokens
            request.headers["Authorization"] = f"Bearer {self.tokens.access_token}"
            yield request

    def _refresh_request(self) -> httpx.Request:
        return httpx.Request("POST", OAUTH_TOKEN_URL, json={
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.tokens.refresh_token,
        })

    async def _refreshed(self, response: httpx.Response) -> None:
        await response.aread()
        if response.is_error:
            raise BackendError("Your Trello login has expired or was revoked. Run `tui-trello login` again.")
        try:
            self.tokens = OAuth2Tokens.from_response(response.json(), self.tokens.refresh_token)
        except (ValueError, KeyError) as exc:
            raise BackendError(f"Unexpected reply when renewing the Trello login: {response.text[:200]}") from exc
        self.on_refresh(self.tokens)


async def whoami(auth: httpx.Auth, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Check credentials work; returns the member's name."""
    from tui_trello.backend.trello import TrelloBackend

    backend = TrelloBackend(auth, transport=transport)
    try:
        member = await backend.me()
    except BackendError as exc:
        raise LoginError(str(exc)) from exc
    finally:
        await backend.aclose()
    return f"{member.full_name} (@{member.username})"


# -- OAuth 2.0 login ---------------------------------------------------------------------------------------------


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def _await_callback(port: int, state: str, open_url: Callable[[], object]) -> str:
    """Serve http://127.0.0.1:port/callback until it is hit with our state; return the authorisation code."""
    received: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    def respond(path: str, query: dict[str, str]) -> tuple[str, str]:
        if path != "/callback":
            return "404 Not Found", "Not found."
        if received.done():
            return "200 OK", DONE
        if query.get("state") != state:
            return "400 Bad Request", "This login link is stale; go back to the terminal and try again."
        if "error" in query:
            message = query.get("error_description") or query["error"]
            received.set_exception(LoginError(f"Trello said: {message}"))
            return "200 OK", f"Login failed: {message}. Go back to the terminal."
        if "code" not in query:
            return "400 Bad Request", "No authorisation code in the callback."
        received.set_result(query["code"])
        return "200 OK", DONE

    connections: set[asyncio.StreamWriter] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Browsers open spare connections that may never send a request; don't wait on those for ever.
        connections.add(writer)
        try:
            request_line = (await asyncio.wait_for(reader.readline(), REQUEST_LINE_TIMEOUT)).decode(errors="replace")
            target = urlsplit(request_line.split(" ")[1] if request_line.count(" ") >= 2 else "/")
            status, body = respond(target.path, dict(parse_qsl(target.query)))
            payload = body.encode()
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                         f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode() + payload)
            await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            connections.discard(writer)

    try:
        server = await asyncio.start_server(handle, "127.0.0.1", port)
    except OSError as exc:
        raise LoginError(f"Could not listen on port {port} for the login callback: {exc}") from exc
    try:
        open_url()
        return await asyncio.wait_for(received, LOGIN_TIMEOUT)
    except TimeoutError:
        raise LoginError("Timed out waiting for you to approve in the browser. If Atlassian showed an error about the "
                         f"redirect URL, add http://127.0.0.1:{port}/callback to the app's callback URLs.") from None
    finally:
        server.close()
        for writer in list(connections):  # wait_closed() waits for open connections too
            writer.close()
        await server.wait_closed()


async def login_oauth2(
    *,
    port: int,
    client_id: str = OAUTH_CLIENT_ID,
    open_browser: Callable[[str], object] | None = None,
    echo: Callable[[str], object] = print,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuth2Tokens:
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = f"{OAUTH_AUTHORIZE_URL}?" + urlencode({
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    def open_url() -> None:
        echo(f"Opening Trello in your browser. Click Accept.\nIf the browser doesn't open, visit:\n  {url}\n")
        (open_browser or webbrowser.open)(url)  # looked up now, so tests can patch it

    code = await _await_callback(port, state, open_url)
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as http:
            response = await http.post(OAUTH_TOKEN_URL, json={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            })
    except httpx.HTTPError as exc:
        raise LoginError(f"Could not reach Atlassian to finish logging in: {exc}") from exc
    if response.is_error:
        raise LoginError(f"Could not exchange the code for a token ({response.status_code}): {response.text[:200]}")
    try:
        return OAuth2Tokens.from_response(response.json())
    except (ValueError, KeyError) as exc:
        raise LoginError(f"Unexpected reply from Atlassian: {response.text[:200]}") from exc
