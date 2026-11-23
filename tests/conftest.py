import pytest

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
    monkeypatch.setattr("webbrowser.open", lambda url, *args, **kwargs: opened.append(url))
    yield
    assert not opened, f"opened {opened} in a browser; a keypress probably reached the app instead of an input"


@pytest.fixture
def backend() -> DemoBackend:
    return DemoBackend()


@pytest.fixture
def app(backend: DemoBackend) -> TrelloApp:
    return TrelloApp(backend, Settings(default_board="b-product"))
