"""`cli.main` start-up: argument checks, without starting the interface or touching the network."""

import pytest

from tui_trello import cli
from tui_trello.backend.demo import DemoBackend
from tui_trello.ui.app import TrelloApp

CARD_URL = "https://trello.example/c/id12"
KINDS = {
    "board": "https://trello.example/b/b-home/home",
    "card": CARD_URL,
    "comment": f"{CARD_URL}#comment-abc",
    "attachment": "https://trello.com/1/cards/id12/attachments/att1/download/x.png",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No user config.toml, and no real login."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    for name in ("TRELLO_BOARD", "TRELLO_TOKEN", "TUI_TRELLO_LAYOUT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def started(monkeypatch) -> list[TrelloApp]:
    apps: list[TrelloApp] = []
    monkeypatch.setattr(TrelloApp, "run", lambda self, *a, **k: apps.append(self))
    return apps


@pytest.fixture
def logins(monkeypatch) -> list[object]:
    calls: list[object] = []

    def trello_backend(settings):
        calls.append(settings)
        return DemoBackend()

    monkeypatch.setattr(cli, "trello_backend", trello_backend)
    return calls


def test_open_rejects_a_web_url(started, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--demo", "--open", "https://example.com/x"])
    assert exit_.value.code == 2
    assert "not a Trello board, card, comment or attachment link" in capsys.readouterr().err
    assert started == []


@pytest.mark.parametrize(
    "url", ["", "https://example.com/x", "trello.com/c/abc", "nVTbsQMq", "https://trello.com/u/phil"]
)
def test_open_rejects_a_bad_url_before_logging_in(url, started, logins) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--open", url])
    assert exit_.value.code == 2
    assert logins == [] and started == []


def test_open_and_board_together_is_an_error(started, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--demo", "--board", "b-home", "--open", CARD_URL])
    assert exit_.value.code == 2
    assert "not allowed with argument --board" in capsys.readouterr().err
    assert started == []


@pytest.mark.parametrize("command", ["login", "logout"])
def test_open_with_login_is_an_error(command, started, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--open", CARD_URL, command])
    assert exit_.value.code == 2
    assert "--open can't be used with login or logout" in capsys.readouterr().err


def test_open_passes_the_url_to_the_app(started) -> None:
    cli.main(["--demo", "--open", CARD_URL])
    [app] = started
    assert app.open_url == CARD_URL and app.settings.layout == "browser"
    cli.main(["--demo", "--open", CARD_URL, "--layout", "triage"])
    assert started[-1].settings.layout == "triage"


def test_no_open_leaves_the_app_as_before(started) -> None:
    cli.main(["--demo"])
    assert started[0].open_url == ""


@pytest.mark.parametrize("kind", KINDS)
def test_open_accepts_each_kind(kind, started) -> None:
    cli.main(["--demo", "--open", KINDS[kind]])
    assert started[0].open_url == KINDS[kind]


def test_open_with_real_trello_uses_trello_hosts(started, logins) -> None:
    cli.main(["--open", "https://trello.com/c/nVTbsQMq/5741-x"])
    assert len(logins) == 1 and started[0].open_url.endswith("5741-x")
