import pytest

from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.ui.app import TrelloApp


@pytest.fixture
def backend() -> DemoBackend:
    return DemoBackend()


@pytest.fixture
def app(backend: DemoBackend) -> TrelloApp:
    return TrelloApp(backend, Settings(default_board="b-product"))
