
import httpx
import pytest

from tui_trello import remote
from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.ui.app import TrelloApp


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    """Drafts go to a test's own directory, never the user's ~/.local/state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    """No test opens a real browser tab; one that opens a URL without patching webbrowser.open itself fails."""
    opened: list[str] = []
    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(f"webbrowser.{name}", lambda url, *args, **kwargs: opened.append(url))
    monkeypatch.setenv("BROWSER", "true")  # a call that slips past the patches runs `true`, not Firefox
    yield
    assert not opened, f"opened {opened} in a browser; a keypress probably reached the app instead of an input"


@pytest.fixture(autouse=True)
def no_remote_fetch(monkeypatch):
    """No test fetches from GitHub; one that does, without a transport of its own, fails."""
    requested: list[str] = []

    def transport() -> httpx.MockTransport:
        return httpx.MockTransport(lambda request: requested.append(str(request.url)) or httpx.Response(404))

    monkeypatch.setattr(remote, "default_transport", transport)
    yield
    assert not requested, f"fetched {requested} from GitHub; pass RemoteFiles a transport of its own"


@pytest.fixture
def backend() -> DemoBackend:
    return DemoBackend()


@pytest.fixture
def app(backend: DemoBackend) -> TrelloApp:
    return TrelloApp(backend, Settings(default_board="b-product"))


class BearerAuth(httpx.Auth):
    """A fixed bearer token: never renewed, and a 401 is left for the caller."""

    async def async_auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = "Bearer ACCESS"
        yield request


def bearer_auth() -> httpx.Auth:
    """A fixed bearer token for the Trello backend, with no expiry or renewal: a 401 from the fake server goes back
    to the backend as it is, so tests see the backend's own message. OAuth2Auth itself is tested in test_auth.py."""
    return BearerAuth()
