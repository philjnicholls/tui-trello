import io

from rich.console import Console

from tui_trello.ui.markdown import inline, render


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
