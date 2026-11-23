import io

from rich.console import Console

from tui_trello.ui.markdown import Link, inline, links, render


def lines(source: str, width: int = 40) -> list[str]:
    console = Console(width=width, record=True, file=io.StringIO(), color_system=None)
    console.print(render(source))
    return [line.rstrip() for line in console.export_text().splitlines()]


def styles(source: str) -> dict[str, str]:
    """Each piece of text and its style."""
    console = Console(width=80)
    return {segment.text.strip(): str(segment.style) for segment in console.render(render(source))
            if segment.text.strip() and segment.style}


def test_inline_styles() -> None:
    found = styles("**bold** *it* ~~gone~~ `code` [site](https://example.com) hi @ada me@example.com")
    assert "bold" in found["bold"]
    assert "italic" in found["it"]
    assert "strike" in found["gone"]
    assert "magenta" in found["code"]
    assert "underline" in found["site"] and "https://example.com" in found["site"]
    assert "cyan" in found["@ada"]
    assert not any("cyan" in style for text, style in found.items() if "example.com" in text and "@" in text)


def test_inline_only() -> None:
    text = inline("Run `make` on **all** of [it](https://example.com)")
    assert text.plain == "Run make on all of it"
    spans = {text.plain[span.start:span.end]: str(span.style) for span in text.spans}
    assert "magenta" in spans["make"] and "bold" in spans["all"] and "underline" in spans["it"]
    assert inline("# 1 - two").plain == "# 1 - two"  # not a heading or a list


def test_bare_urls_are_links() -> None:
    assert "underline" in styles("see https://trello.com/b/abc for more")["https://trello.com/b/abc"]


def test_paragraphs_and_line_breaks() -> None:
    assert lines("one\ntwo\n\nthree") == ["one", "two", "", "three"]


def test_list_hangs_under_marker() -> None:
    assert lines("- a long item that has to wrap round\n- b\n  1. nested", width=20) == [
        "• a long item that",
        "  has to wrap round",
        "• b",
        "  1. nested",
    ]


def test_rtl_list_marker_on_the_right() -> None:
    [line] = lines("- مرحبا", width=20)
    assert line.endswith("ابحرم •")  # reordered for display, marker on the right with a gap


def test_heading_quote_code_rule() -> None:
    assert lines("# Title\n\n> quoted\n\n```\nx = 1\n```\n\n---", width=10) == [
        "Title", "", "▌ quoted", "", "│ x = 1", "", "─" * 10,
    ]


def test_table() -> None:
    rendered = "\n".join(lines("| a | b |\n|---|---|\n| 1 | 2 |"))
    assert "a" in rendered and "1" in rendered and "2" in rendered


def test_trello_link_with_url_as_text_shows_once() -> None:
    assert lines("[https://x.org](https://x.org)") == ["https://x.org"]


def clicks(renderable) -> dict[str, tuple]:
    """Each piece of text that runs an action when clicked, and the action."""
    console = Console(width=80)
    return {segment.text.strip(): segment.style.meta["@click"] for segment in console.render(renderable)
            if segment.style and segment.style.meta.get("@click")}


def test_links_in_order() -> None:
    source = ("see [the card](https://trello.com/c/abc) and https://example.com/x\n\n"
              "![shot.png](https://trello.com/1/cards/c/attachments/a/download/shot.png)\n\n"
              "- [item](https://example.com/y)")
    assert links(source) == [
        Link("the card", "https://trello.com/c/abc"), Link("https://example.com/x", "https://example.com/x"),
        Link("shot.png", "https://trello.com/1/cards/c/attachments/a/download/shot.png"),
        Link("item", "https://example.com/y")]
    assert links("**[one](https://a.example)** and `code`", one_line=True) == [Link("one", "https://a.example")]
    assert links("no links here") == []


def test_clickable_links_and_images() -> None:
    found = clicks(render("a [site](https://example.com) and ![pic.png](https://example.com/pic.png) https://b.example",
                          clickable=True))
    assert found == {
        "site": ("app.follow_link", ("https://example.com",)),
        "[image: pic.png]": ("app.follow_link", ("https://example.com/pic.png",)),
        "https://b.example": ("app.follow_link", ("https://b.example",)),
    }


def test_links_are_not_clickable_by_default() -> None:
    assert clicks(render("a [site](https://example.com) ![pic](https://example.com/p.png)")) == {}
    assert "link" in styles("[site](https://example.com)")["site"] or "example.com" in styles(
        "[site](https://example.com)")["site"]


def test_clickable_inline_and_in_blocks() -> None:
    text = inline("go to [it](https://example.com)", clickable=True)
    assert [span.style.meta["@click"] for span in text.spans if span.style.meta.get("@click")] == [
        ("app.follow_link", ("https://example.com",))]
    assert not [s for s in inline("go to [it](https://example.com)").spans if s.style.meta.get("@click")]
    assert clicks(render("> - [deep](https://example.com)\n\n| a |\n| - |\n| [cell](https://b.example) |",
                         clickable=True)).keys() == {"deep", "cell"}


def test_rtl_link_keeps_its_click() -> None:
    found = clicks(render("انظر [البطاقة](https://trello.com/c/abc) من فضلك", clickable=True))
    assert found and set(found.values()) == {("app.follow_link", ("https://trello.com/c/abc",))}
