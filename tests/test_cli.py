"""`cli.main` start-up: argument checks, without starting the interface or touching the network."""

import json
import time

import pytest

from tui_trello import __version__, auth, cli
from tui_trello.backend.demo import DemoBackend
from tui_trello.remote import RemoteFiles
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
    for name in ("TRELLO_BOARD", "TUI_TRELLO_LAYOUT", "TRELLO_TOKEN", "TRELLO_API_KEY"):
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
    "url", ["", "https://example.com/x", "trello.com/c/abc", "Qr56St78", "https://trello.com/u/ada"]
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


@pytest.mark.parametrize("command", ["login", "logout", "keys"])
def test_open_with_login_is_an_error(command, started, capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--open", CARD_URL, command])
    assert exit_.value.code == 2
    assert "--open can't be used with login, logout or keys" in capsys.readouterr().err


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
    cli.main(["--open", "https://trello.com/c/Qr56St78/5741-x"])
    assert len(logins) == 1 and started[0].open_url.endswith("5741-x")


def write_config(tmp_path, text: str) -> None:
    path = tmp_path / "config" / "tui-trello" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(text)


def test_keys_lists_every_id(capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["keys"])
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("[keys]\n") and "# card:" in out and "# app:" in out
    assert 'card.archive = "A"' in out and 'app.search = "/"' in out and 'chord.next_view = "g t"' in out
    assert "(default:" not in out


def test_keys_reports_problems(tmp_path, capsys) -> None:
    write_config(tmp_path, '[keys]\ncard.archive = "m"\ncard.delete = "ctrl+x"\n')
    with pytest.raises(SystemExit) as exit_:
        cli.main(["keys"])
    assert exit_.value.code == 1
    captured = capsys.readouterr()
    assert "card.archive = \"m\": m already does" in captured.err and "(card.move)" in captured.err
    assert 'card.archive = "A"' in captured.out  # dropped: the default stays
    assert 'card.delete = "ctrl+x"' in captured.out and "(default: D)" in captured.out


def test_keys_ignores_retired_settings(tmp_path, monkeypatch, capsys) -> None:
    """CR42: only [keys] problems make `keys` complain."""
    monkeypatch.setenv("TRELLO_TOKEN", "T")
    write_config(tmp_path, '[trello]\ntoken = "T"\n')
    with pytest.raises(SystemExit) as exit_:
        cli.main(["keys"])
    assert exit_.value.code == 0 and capsys.readouterr().err == ""


def test_keys_marks_an_override_and_exits_clean(tmp_path, capsys) -> None:
    write_config(tmp_path, '[keys]\ncard.archive = "ctrl+a"\n')
    with pytest.raises(SystemExit) as exit_:
        cli.main(["keys"])
    assert exit_.value.code == 0
    captured = capsys.readouterr()
    assert 'card.archive = "ctrl+a"' in captured.out and "(default: A)" in captured.out and captured.err == ""


def test_keys_output_is_a_valid_config(tmp_path, capsys) -> None:
    """What the command prints can be pasted back as `[keys]` without a single warning."""
    with pytest.raises(SystemExit):
        cli.main(["keys"])
    write_config(tmp_path, capsys.readouterr().out)
    with pytest.raises(SystemExit) as exit_:
        cli.main(["keys"])
    assert exit_.value.code == 0 and capsys.readouterr().err == ""


def test_version_prints_the_version_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--version"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out == f"tui-trello {__version__}\n" and __version__ == "0.1.0"


# -- login ----------------------------------------------------------------------------------------------------------


def test_login_token_is_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["login", "--token"])
    assert exit_.value.code == 2 and "unrecognized arguments" in capsys.readouterr().err


def test_a_retired_login_says_so_and_starts_the_browser_login(monkeypatch, capsys) -> None:
    logins: list[int] = []
    tokens = auth.OAuth2Tokens("A", "R", time.time() + 3600)

    async def login_oauth2(**kwargs):
        logins.append(kwargs["port"])
        return tokens

    async def whoami(auth_, transport=None):
        return "Ada Lovelace (@ada)"

    monkeypatch.setattr(auth, "login_oauth2", login_oauth2)
    monkeypatch.setattr(auth, "whoami", whoami)
    monkeypatch.setattr("tui_trello.backend.trello.TrelloBackend", lambda auth_: auth_)
    path = auth.credentials_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"token": "T"}))
    backend = cli.trello_backend(cli.Settings())
    out = capsys.readouterr().out
    assert out.count(auth.RETIRED_LOGIN) == 1 and "Not logged in" not in out
    assert logins == [8765] and isinstance(backend, auth.OAuth2Auth) and backend.tokens == tokens
    assert auth.load_credentials() == tokens and not auth.retired_login()  # replaced: the message won't come back


def test_retired_settings_are_named_before_a_login_starts(monkeypatch, capsys) -> None:
    """CR41: a user with an old token is told why they are asked to log in."""
    monkeypatch.setenv("TRELLO_TOKEN", "T")
    monkeypatch.setattr(cli, "cmd_login", lambda settings: 1)
    with pytest.raises(SystemExit):
        cli.trello_backend(cli.Settings.load())
    err = capsys.readouterr().err
    assert "TRELLO_TOKEN is set but no longer used" in err


def test_no_remote_makes_no_request(started, monkeypatch) -> None:
    monkeypatch.setattr(RemoteFiles, "refresh", lambda *a, **k: pytest.fail("fetched with --no-remote"))
    cli.main(["--no-remote", "--demo"])
    assert started[0].remote is None and started[0].unseen_news == []


def test_remote_disabled_in_config_makes_no_request(tmp_path, started, monkeypatch) -> None:
    write_config(tmp_path, "[remote]\nenabled = false\n")
    monkeypatch.setattr(RemoteFiles, "refresh", lambda *a, **k: pytest.fail("fetched with [remote] disabled"))
    cli.main(["--demo"])
    assert started[0].remote is None


def test_remote_is_on_by_default(started) -> None:
    cli.main(["--demo"])
    assert isinstance(started[0].remote, RemoteFiles)
