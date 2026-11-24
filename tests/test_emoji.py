import io
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.console import Console
from textual.fuzzy import Matcher

from tui_trello import emoji_codes
from tui_trello.emoji import _replace, with_emoji
from tui_trello.models import (
    Attachment,
    Board,
    BoardSnapshot,
    Card,
    CardList,
    Comment,
    Label,
    Member,
    Notification,
    WorkSnapshot,
)
from tui_trello.ui import render
from tui_trello.ui.bidi import cut
from tui_trello.ui.commands import BoardCommands, CardCommands
from tui_trello.ui.markdown import _plain_short, inline, plain
from tui_trello.ui.markdown import render as render_markdown
from tui_trello.ui.screens.base import CardActionsScreen, reply_to
from tui_trello.ui.screens.mywork import MyWorkScreen
from tui_trello.ui.screens.notifications import NotificationsScreen
from tui_trello.ui.screens.picker import (
    AttachmentPickerScreen,
    Choice,
    LabelPickerScreen,
    PickerScreen,
)
from tui_trello.ui.widgets.card_view import CardView

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def lines(source: str, width: int = 40) -> list[str]:
    console = Console(width=width, record=True, file=io.StringIO(), color_system=None)
    console.print(render_markdown(source))
    return [line.rstrip() for line in console.export_text().splitlines()]


def printed(renderable, width: int = 60) -> str:
    console = Console(width=width, record=True, file=io.StringIO(), color_system=None)
    console.print(renderable)
    return console.export_text()


def test_shortcodes() -> None:
    assert with_emoji("hi :smiley: :+1: :tada:") == "hi 😃 👍 🎉"
    assert with_emoji(":+1::skin-tone-3:") == "👍🏼"
    assert with_emoji(":heart:") == "❤️"
    assert with_emoji(":flag-il:") == "🇮🇱"


@pytest.mark.parametrize("text", [":nope:", "10:30:00", "a:b:c", "word:smile:", ":smile:word", "/path/:smile:",
                                  ":Smiley:", ":)"])
def test_left_as_written(text: str) -> None:
    assert with_emoji(text) == text


def test_no_colon_is_same_object() -> None:
    text = "no shortcodes here"
    assert with_emoji(text) is text


def test_table() -> None:
    assert len(emoji_codes.CODES) > 1900
    assert emoji_codes.CODES["+1"] == emoji_codes.CODES["thumbsup"] == "👍"


def test_markdown() -> None:
    assert lines("Done :tada:") == ["Done 🎉"]
    assert lines("`:tada:` x") == [":tada: x"]
    assert lines("```\n:tada:\n```") == ["│ :tada:"]
    assert lines("https://example.com/:tada:") == ["https://example.com/:tada:"]
    assert lines("<https://example.com/:tada:>") == ["https://example.com/:tada:"]
    assert lines("[:tada: notes](https://e.com)") == ["🎉 notes"]
    assert lines("nope :nope:") == ["nope :nope:"]


def test_inline() -> None:
    assert inline(":rocket: launch").plain == "🚀 launch"
    text = inline(":rocket: @ada")
    assert text.plain == "🚀 @ada"
    assert any("cyan" in str(span.style) and text.plain[span.start:span.end] == "@ada" for span in text.spans)


def card(name: str = ":rocket: Launch", **kwargs) -> Card:
    return Card(id="c1", name=name, list_id="l1", board_id="b1", **kwargs)


def test_card_block_and_labels() -> None:
    snapshot = BoardSnapshot(Board("b1", "B"), [], [])
    assert "🚀 Launch" in printed(render.card_block(card(), snapshot))
    chips = render.label_chips([Label("x", ":tada: Done", "green")])
    assert "🎉 Done" in chips.plain


def notification(**kwargs) -> Notification:
    return Notification(id="n1", type="commentCard", unread=True, date=NOW, creator="Ada", card_id="c1",
                        card_name=":rocket: Launch", board_name=":tada: Board", **kwargs)


def test_notification_summary_and_row() -> None:
    n = notification(text="nice :+1:")
    assert "🚀 Launch" in render.notification_summary(n)
    assert "🚀 Launch" in render.notification_summary(
        Notification(id="n", type="cardDueSoon", unread=True, date=NOW, card_name=":rocket: Launch"))
    row = NotificationsScreen.row(n, NOW, 100).plain
    assert "👍" in row and "🚀 Launch" in row and "🎉 Board" in row
    assert n.text == "nice :+1:"


def test_my_work_row() -> None:
    me = Member("m1", "Ada Lovelace", "ada")
    work = WorkSnapshot(me, [card()], {"b1": Board("b1", ":tada: Board")}, {"l1": CardList("l1", ":+1: Doing", "b1")})
    row = MyWorkScreen.row(card(), work, NOW, 30, 30).plain
    assert "🚀 Launch" in row and "👍 Doing" in row and "🎉 Board" in row


def test_board_commands_show_emoji() -> None:
    commands = BoardCommands.__new__(BoardCommands)
    commands.boards = [Board("b1", ":tada: Board")]
    assert commands.board_text(commands.boards[0]) == "Board: 🎉 Board"


def test_list_and_quote_direction_follow_the_displayed_text() -> None:
    [line] = lines("- :tada: مرحبا", width=20)
    assert line.endswith("ابحرم 🎉 •")
    [line] = lines("> :tada: مرحبا", width=20)
    assert not line.startswith("▌") and line.endswith("▌")


def test_image_alt_shows_emoji() -> None:
    assert lines("![:tada:](https://e.com/a.png)") == ["[image: 🎉]"]


def test_escaped_shortcode_stays_literal() -> None:
    assert lines(r"\:tada:") == [":tada:"]
    assert lines(r"\:tada: and :tada:") == [":tada: and 🎉"]


def test_only_an_escaped_colon_is_kept_literal() -> None:
    assert lines(r"x\_:tada:") == ["x_:tada:"]
    assert lines("&amp;:tada:") == ["&:tada:"]
    assert lines(r"\\:tada:") == ["\\🎉"]
    assert lines(r":white\_check\_mark: done") == ["✅ done"]
    assert lines(r"\:tada:") == [":tada:"]


def test_mention_with_an_escaped_underscore_is_styled_whole() -> None:
    text = inline(r"hi @bob\_smith")
    assert [text.plain[span.start:span.end] for span in text.spans] == ["@bob_smith"]
    text = inline(r"x\_@bar")
    assert text.spans == []


@pytest.mark.parametrize("source, shown", [
    (r"\:tada:", ":tada:"),
    (r":white\_check\_mark:", "✅"),
    ("\\\\:tada:", "\\🎉"),
    ("`:tada:`", ":tada:"),
    (r"@bob\_smith", "@bob_smith"),
    (r"\:tada: and :tada:", ":tada: and 🎉"),
])
def test_plain_matches_the_card_view(source: str, shown: str) -> None:
    assert plain(source) == shown
    assert plain(source) == inline(source).plain


def test_image_alt_text_has_no_placeholder() -> None:
    assert inline(r"![a\:tada: b](x.png)").plain == "[image: a:tada: b]"
    assert "\ue000" not in inline(r"![\:tada:](u)").plain


def test_with_emoji_skips_the_cache_for_long_text() -> None:
    _replace.cache_clear()
    with_emoji(":tada: " * 100)
    assert _replace.cache_info().currsize == 0
    with_emoji(":tada:")
    assert _replace.cache_info().currsize == 1


def test_cut_never_splits_a_cluster() -> None:
    family = "👨\u200d👩\u200d👧\u200d👦"  # one cluster, two cells
    assert cut(family * 3, 4) == family * 2 + "…"
    assert cut("👍🏽" * 5, 6) == "👍🏽" * 3 + "…"
    assert cut("x" * 59 + "👍🏽x", 60) == "x" * 59 + "…"  # the emoji would be cells 60 and 61
    assert cut("x" * 58 + "👍🏽x", 60) == "x" * 58 + "👍🏽…"
    assert cut("abc", 3) == "abc"


def test_cut_counts_terminal_cells() -> None:
    assert cut("你好世界", 4) == "你好…"
    assert cut("你好", 4) == "你好"


def test_cut_never_splits_a_flag() -> None:
    flag = "\U0001f1ee\U0001f1f1"
    assert cut("x" * 58 + flag + "y", 60) == "x" * 58 + flag + "…"
    assert cut("x" * 59 + flag + "y", 60) == "x" * 59 + "…"
    assert cut(flag * 3, 4) == flag * 2 + "…"  # pairs, not a pair and a half


def test_comment_picker_label_is_cut_by_cell_and_plain() -> None:
    text = "x" * 58 + "👍🏽 more"
    assert cut(plain(text), 60) == "x" * 58 + "👍🏽…"


def test_plain_cut_ends_with_an_ellipsis_at_a_space() -> None:
    shown = plain("word " * 500, limit=100)
    assert shown.endswith("word…")
    assert len(shown) <= 101
    assert plain("a" * 500, limit=100) == "a" * 100 + "…"
    assert plain("one\ntwo three four", limit=12) == "one\ntwo…"


def test_plain_is_cached_for_short_texts() -> None:
    _plain_short.cache_clear()
    plain("a :tada: b")
    plain("a :tada: b")
    assert _plain_short.cache_info().hits == 1
    plain("x" * 400)
    assert _plain_short.cache_info().currsize == 1  # a long text isn't kept


def test_image_alt_text_shows_emoji_with_escaped_underscores() -> None:
    assert inline(r"![:white\_check\_mark:](x.png)").plain == "[image: ✅]"
    assert inline(r"![a *:tada:* b](x.png)").plain == "[image: a 🎉 b]"


def host_for(comments: list[Comment]):
    captured = []

    async def push_screen_wait(screen):
        captured.append(screen)

    async def get_comments(card_id):
        return comments

    async def me():
        return SimpleNamespace(id="m")

    host = SimpleNamespace(app=SimpleNamespace(store=SimpleNamespace(comments=get_comments, me=me),
                                               push_screen_wait=push_screen_wait), notify=print)
    return host, captured


async def test_comment_picker_matches_only_the_label_and_quickly() -> None:
    host, captured = host_for([Comment("c", "Ann", "e " * 300, None)])
    await CardActionsScreen.pick_comment(host, Card(id="c1", name="n", list_id="l1", board_id="b1"), "t")
    [choice] = captured[0].choices
    assert choice.search == choice.label
    assert len(choice.label) <= len("Ann: ") + 61
    started = time.monotonic()
    assert PickerScreen.score(Matcher("eeeee"), choice) > 0
    assert time.monotonic() - started < 1


async def test_comment_picker_label_cuts_rendered_text_not_source() -> None:
    link = "[see](https://example.com/" + "a" * 120 + ") hello"
    host, captured = host_for([Comment("c", "Ann", link, None)])
    await CardActionsScreen.pick_comment(host, Card(id="c1", name="n", list_id="l1", board_id="b1"), "t")
    assert captured[0].choices[0].label == "Ann: see hello"


async def test_quote_picker_matches_only_the_label_and_quickly() -> None:
    captured = []

    async def push_screen_wait(screen):
        captured.append(screen)

    host = SimpleNamespace(app=SimpleNamespace(push_screen_wait=push_screen_wait))
    text = "e " * 200 + "\n\n" + "e " * 100
    await reply_to(host, "c1", "n", "b1", "Ann", "ann", text)
    assert captured
    started = time.monotonic()
    for choice in captured[0].choices:
        assert len(choice.search) <= 61
        PickerScreen.score(Matcher("eeeee"), choice)
    assert time.monotonic() - started < 1


@pytest.mark.parametrize("text", ["https://e.com/?q=:tada:", "a=:tada:", "a?:tada:", "a&:tada:"])
def test_not_after_url_query_characters(text: str) -> None:
    assert with_emoji(text) == text


def test_with_emoji_is_cached() -> None:
    _replace.cache_clear()
    with_emoji(":tada:")
    with_emoji(":tada:")
    assert _replace.cache_info().hits == 1


def test_label_picker_does_not_offer_create_for_a_stored_name() -> None:
    picker = LabelPickerScreen.__new__(LabelPickerScreen)
    picker.choices = [Choice("🎉 Done", Label("x", ":tada: Done", "green"), search=":tada: Done")]
    assert picker.extras(":tada: Done") == []
    assert picker.extras("🎉 Done") == []
    assert len(picker.extras("Other")) == 1


@pytest.mark.parametrize("stored, query", [(":rocket: Launch", "rocket"), (":rocket:", "rocket"), (":rocket:", "🚀")])
def test_picker_finds_a_name_by_its_shortcode(stored: str, query: str) -> None:
    choice = Choice(with_emoji(stored), 1, search=stored)
    assert PickerScreen.score(Matcher(query), choice) > 0


def test_picker_does_not_match_twice_when_nothing_differs() -> None:
    class Counting(Matcher):
        calls = 0

        def match(self, candidate: str) -> float:
            Counting.calls += 1
            return super().match(candidate)

    assert PickerScreen.score(Counting("abc"), Choice("abc", 1, search="abc")) > 0
    assert Counting.calls == 1


def test_picker_highlights_nothing_when_only_the_stored_name_matched() -> None:
    choice = Choice("🚀 Launch", 1, search=":rocket: Launch")
    assert PickerScreen.highlight(Matcher("rocket"), choice).spans == []


class FakeApp:
    def __init__(self, snapshot=None) -> None:
        self.store = SimpleNamespace(snapshot=snapshot)

    def open_board(self, board_id) -> None: ...

    def open_card(self, card_id) -> None: ...


async def hits(provider, query: str) -> list:
    provider.matcher = lambda q: Matcher(q)
    return [hit async for hit in provider.search(query)]


async def test_board_commands_find_a_shortcode_word() -> None:
    class Commands(BoardCommands):
        app = FakeApp()

    commands = Commands.__new__(Commands)
    commands.boards = [Board("b1", ":rocket:")]
    [hit] = await hits(commands, "rocket")
    assert hit.text == "Board: 🚀"


async def test_card_commands_find_a_shortcode_word() -> None:
    snapshot = BoardSnapshot(Board("b1", "B"), [CardList("l1", "Doing", "b1")], [card()])

    class Commands(CardCommands):
        app = FakeApp(snapshot)

    [hit] = await hits(Commands.__new__(Commands), "rocket")
    assert hit.text == "Card: 🚀 Launch"


def test_attachment_names_show_emoji() -> None:
    shown = []
    stub = SimpleNamespace(KEY_HINTS=True, app=None, query=lambda _: SimpleNamespace(set_class=lambda *_: None),
                           query_one=lambda *_: SimpleNamespace(update=shown.append))
    CardView.show_attachments(stub, [Attachment("a1", ":tada: notes.pdf", "https://e.com/n", True)])
    assert "🎉 notes.pdf" in printed(shown[0])


async def test_attachment_picker_shows_emoji() -> None:
    async def attachments(card_id):
        return [Attachment("a1", ":tada: notes.pdf", "https://e.com/n", True)]

    class Picker(AttachmentPickerScreen):
        app = SimpleNamespace(store=SimpleNamespace(find_card=lambda _: None, attachments=attachments))

    picker = Picker.__new__(Picker)
    picker.card_id = "c1"
    [choice] = await picker.attachment_choices()
    assert choice.label == "🎉 notes.pdf" and choice.search == ":tada: notes.pdf"


async def test_quote_choices_with_a_shared_start_are_told_apart(app) -> None:
    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        first = "The picker is slow on big boards and nobody has looked at why it is, though it is easy to see. "
        await app.store.add_comment(card.id, f"{first.strip()}\n\n" + "More detail, in words. " * 12)
        await pilot.press("C", "enter")
        await pilot.pause()
        labels = [c.label for c in app.screen.choices]
        assert len(labels) == len(set(labels)) >= 2
        assert all(cell_len(c.search) <= 61 for c in app.screen.choices)  # only the search is cut


def test_image_alt_text_in_links_shows_emoji() -> None:
    from tui_trello.ui.markdown import links
    assert links(r"![:white\_check\_mark:](x.png)")[0].text == "✅"
    assert links(r"[:rocket: launch plan](https://e.com)")[0].stored == ":rocket: launch plan"


def test_image_alt_text_keeps_code_and_line_breaks() -> None:
    assert inline("![`:tada:`](x.png)").plain == "[image: :tada:]"
    assert inline("![a\nb](x.png)").plain == "[image: a b]"


def test_one_cache_limit() -> None:
    from tui_trello import emoji
    from tui_trello.ui import markdown
    assert not hasattr(markdown, "SHORT")  # emoji.CACHE_LIMIT is the one threshold
    assert emoji.CACHE_LIMIT == 300


async def test_link_picker_searches_a_markdown_links_stored_text() -> None:
    from tui_trello.ui import follow

    async def comments(_id):
        return []

    store = SimpleNamespace(comments=comments, has_checklists=lambda _id: False, link_hosts=(),
                            known_card=lambda _s: None, known_board=lambda _s: None)
    desc = "[:rocket: launch plan](https://example.com/a) and https://example.com/b"
    found = await follow.link_choices(SimpleNamespace(store=store), card(desc=desc, checklist=(0, 0)))
    assert (found[0].label, found[0].search) == ("🚀 launch plan", ":rocket: launch plan")


def test_attachment_preview_shows_emoji_in_names() -> None:
    from tui_trello.ui.screens.preview import LinkPreviewScreen

    attachment = SimpleNamespace(is_upload=True, name=":tada: notes", file_name="notes:tada:.png", size=15,
                                 mime_type="image/png", date=None, url="")
    preview = SimpleNamespace(card=SimpleNamespace(name="Ship :rocket:"), location="Board :fire: / Doing",
                              archived=None)
    out = io.StringIO()
    Console(file=out, width=80, color_system=None).print(LinkPreviewScreen.attachment_lines(attachment, preview))
    text = out.getvalue()
    assert "🎉 notes" in text and "Ship 🚀" in text and "Board 🔥" in text
    assert "notes:tada:.png" in text  # the file name stays as written
