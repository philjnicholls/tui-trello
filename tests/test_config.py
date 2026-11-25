"""`Settings.load`: the retired settings and the sections that aren't tables."""

import pytest

from tui_trello.config import Settings

ENV = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_BOARD")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def load(tmp_path):
    def load(text: str = "") -> Settings:
        path = tmp_path / "config.toml"
        path.write_text(text)
        return Settings.load(path)

    return load


@pytest.mark.parametrize(("setting", "name"), [
    ('[trello]\napi_key = "K"\n', "[trello] api_key"),
    ('[trello]\ntoken = "T"\n', "[trello] token"),
    ({"TRELLO_API_KEY": "K"}, "TRELLO_API_KEY"),
    ({"TRELLO_TOKEN": "T"}, "TRELLO_TOKEN"),
])
def test_retired_settings_warn(load, monkeypatch, setting, name) -> None:
    if isinstance(setting, dict):
        for variable, value in setting.items():
            monkeypatch.setenv(variable, value)
        settings = load()
    else:
        settings = load(setting)
    [warning] = settings.warnings
    assert warning.startswith(f"{name} is ") and "no longer used" in warning and "tui-trello login" in warning
    assert not hasattr(settings, "api_key") and not hasattr(settings, "token")  # ignored, not kept


def test_no_retired_settings_no_warning(load, monkeypatch) -> None:
    monkeypatch.setenv("TRELLO_BOARD", "AbCd1234")
    settings = load('[trello]\ndefault_board = "x"\noauth_port = 9000\n')
    assert settings.warnings == [] and settings.default_board == "AbCd1234" and settings.oauth_port == 9000


@pytest.mark.parametrize("text", ['trello = 1\n', 'ui = "x"\n', 'notifications = []\n'])
def test_a_section_that_is_not_a_table_warns(load, text) -> None:
    name = text.split(" ")[0]
    settings = load(text)
    assert settings.warnings == [f"[{name}] must be a table; ignored"]
    assert settings.layout == "browser" and settings.notify_interval == 60 and settings.oauth_port == 8765


@pytest.mark.parametrize("line", ["remote = false", 'remote = "no"'])
def test_remote_that_is_not_a_table_turns_fetching_off(load, line) -> None:
    settings = load(f"{line}\n")
    assert settings.remote is False and "[remote] must be a table" in settings.warnings[0]


def test_retired_settings_are_listed_apart(load, monkeypatch) -> None:
    monkeypatch.setenv("TRELLO_TOKEN", "T")
    settings = load('[trello]\napi_key = "K"\n\n[keys]\ncard = 1\n')
    assert len(settings.retired) == 2 and all(w in settings.warnings for w in settings.retired)
