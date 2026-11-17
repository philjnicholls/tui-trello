import pytest

from tui_trello.mentions import candidates, typing_mention
from tui_trello.models import Member

MEMBERS = [
    Member("1", "Ada Lovelace", "ada"),
    Member("2", "Grace Hopper", "grace"),
    Member("3", "Alan Turing", "alan"),
    Member("4", "ليلى حداد", "layla"),
]


@pytest.mark.parametrize(("before", "query"), [
    ("@", ""),
    ("hi @gr", "gr"),
    ("line one\n@ad", "ad"),
    ("@لي", "لي"),
    ("mail me at me@example", None),  # an @ inside a word isn't a mention
    ("@grace done", None),  # the cursor has moved past it
    ("no mention", None),
])
def test_typing_mention(before: str, query: str | None) -> None:
    assert typing_mention(before) == query


def test_candidates() -> None:
    assert [m.username for m in candidates(MEMBERS, "")] == ["ada", "alan", "grace", "layla"]
    assert [m.username for m in candidates(MEMBERS, "a")] == ["ada", "alan"]
    assert [m.username for m in candidates(MEMBERS, "hop")] == ["grace"]  # by surname
    assert [m.username for m in candidates(MEMBERS, "حد")] == ["layla"]
    assert candidates(MEMBERS, "zz") == []


def test_alt_enter_is_decoded() -> None:
    from textual import events
    from textual._xterm_parser import XTermParser

    from tui_trello.ui import keys_compat

    keys_compat.install()

    def keys(data: str) -> list[str]:
        parser = XTermParser()
        return [e.key for e in [*parser.feed(data), *parser.feed("")] if isinstance(e, events.Key)]

    assert keys("\x1b\r") == ["alt+enter"]
    assert keys("\r") == ["enter"]
    assert keys("\x1ba") == ["alt+a"]
