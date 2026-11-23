import pytest

from tui_trello.backend.demo import DemoBackend
from tui_trello.links import parse, short_link


def test_board_with_and_without_a_slug() -> None:
    assert parse("https://trello.com/b/AbCd1234/product-roadmap").short_link == "AbCd1234"
    assert parse("https://trello.com/b/AbCd1234").kind == "board"
    assert parse("https://trello.com/b/AbCd1234/").short_link == "AbCd1234"


def test_card_long_and_short_url() -> None:
    long = parse("https://trello.com/c/Xy12Zw34/42-move-cards")
    assert (long.kind, long.short_link) == ("card", "Xy12Zw34")
    assert parse("https://trello.com/c/Xy12Zw34").kind == "card"


def test_comment_fragment() -> None:
    link = parse("https://trello.com/c/Xy12Zw34/42-move-cards#comment-65f0a1b2c3")
    assert (link.kind, link.short_link, link.comment_id) == ("comment", "Xy12Zw34", "65f0a1b2c3")


def test_other_fragment_is_still_a_card() -> None:
    assert parse("https://trello.com/c/Xy12Zw34/42-move-cards#checklist").kind == "card"


def test_query_before_the_fragment() -> None:
    link = parse("https://trello.com/c/Xy12Zw34/42-move?filter=x#comment-abc")
    assert (link.kind, link.comment_id) == ("comment", "abc")


def test_attachment_download_and_preview_urls() -> None:
    link = parse("https://trello.com/1/cards/5f1c0000aaaa/attachments/5f1c0000bbbb/download/image.png")
    assert (link.kind, link.card_id, link.attachment_id) == ("attachment", "5f1c0000aaaa", "5f1c0000bbbb")
    preview = parse("https://trello.com/1/cards/c1/attachments/a1/previews/p1/download/image.png")
    assert (preview.kind, preview.card_id, preview.attachment_id) == ("attachment", "c1", "a1")


def test_host_case_and_www() -> None:
    assert parse("https://www.Trello.com/c/abc").kind == "card"
    assert parse("HTTPS://TRELLO.COM/b/abc").kind == "board"


@pytest.mark.parametrize("url", [
    "https://trello.com/u/ada", "https://trello.com/w/team", "https://trello.com/c/", "https://trello.com/c",
    "https://trello.com/card/abc", "https://example.com/c/abc", "mailto:ada@example.com", "javascript:alert(1)",
    "https://trello-attachments.s3.amazonaws.com/a/b/c.png", "ftp://trello.com/c/abc", "",
])
def test_everything_else_is_web(url: str) -> None:
    assert parse(url).kind == "web"


def test_short_link() -> None:
    hosts = DemoBackend().link_hosts
    assert short_link("https://trello.com/c/Xy12Zw34/42-move-cards") == "Xy12Zw34"
    assert short_link("https://trello.example/b/b-home/home", hosts) == "b-home"
    assert short_link("https://trello.example/c/id12", hosts) == "id12"
    assert short_link("https://trello.example/c/id12") == ""  # not a host unless the backend says so
    assert short_link("https://example.com/c/abc") == ""
