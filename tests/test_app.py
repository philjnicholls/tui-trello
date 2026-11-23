"""End-to-end flows driven through the keyboard, against the demo backend."""

import asyncio
import json
from dataclasses import replace

import pytest
from textual.widgets import DataTable, TextArea

from tui_trello import store as store_module
from tui_trello.backend import BackendError
from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.drafts import drafts_path
from tui_trello.models import CheckItem, Checklist
from tui_trello.ui import clipboard, render
from tui_trello.ui.app import TrelloApp
from tui_trello.ui.screens.browser import BrowserScreen
from tui_trello.ui.screens.card import CardScreen
from tui_trello.ui.screens.keys import KeysScreen
from tui_trello.ui.screens.mywork import MyWorkScreen
from tui_trello.ui.screens.notifications import NotificationsScreen
from tui_trello.ui.screens.picker import (
    AttachmentPickerScreen,
    ChecklistPickerScreen,
    FilePickerScreen,
    LabelPickerScreen,
    LinkPickerScreen,
    PickerScreen,
    TextPromptScreen,
)
from tui_trello.ui.screens.preview import LinkPreviewScreen
from tui_trello.ui.screens.triage import TriageScreen
from tui_trello.ui.tips import TIPS
from tui_trello.ui.widgets.card_view import CardView
from tui_trello.ui.widgets.spinner import Spinner


def screen_lines(app) -> list[str]:
    return ["".join(segment.text for segment in strip).rstrip()
            for strip in app.screen._compositor.render_update(full=True).strips]


async def test_browse_and_open_card(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, BrowserScreen)
        await pilot.press("j", "l")  # second list, into its cards
        assert app.screen.current_card().name == "Command palette: jump to any card"
        await pilot.press("enter")
        assert isinstance(app.screen, CardScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, BrowserScreen)


async def test_move_card_updates_every_view(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("m")
        assert isinstance(app.screen, PickerScreen)
        await pilot.press(*"done", "enter")
        await pilot.pause()
        snapshot = app.store.snapshot
        assert snapshot.list_named(snapshot.card(card.id).list_id) == "Done"
        await pilot.press("2")
        await pilot.pause()
        assert isinstance(app.screen, TriageScreen)
        done = [c.name for c in app.screen.rows if snapshot.list_named(c.list_id) == "Done"]
        assert done[0] == card.name  # moved to the top


async def test_triage_filter_and_sort(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("slash", *"#bug", "enter")
        assert {c.name for c in app.screen.rows} == {
            "Crash when a card has no description", "Token stored in plain text in config"}
        await pilot.press("escape", "s")
        assert app.screen.sort == "due"
        assert len(app.screen.rows) == 12


async def test_add_comment(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l", "enter", "c", *"hello", "ctrl+s")
        await pilot.pause()
        comments = await app.store.comments(app.screen.card_id)
        assert comments[0].text == "hello"


async def test_pick_board(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("b", *"home", "enter")
        await pilot.pause()
        assert app.store.snapshot.board.name == "Home"


async def test_my_work(app) -> None:
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MyWorkScreen)
        names = [c.name for c in screen.cards_by_option.values()]
        assert "Renew passport" in names and "Book boiler service" in names  # cards from both boards
        assert "Vim keys for navigation" not in names  # someone else's
        # Group headers are skipped: the cursor starts on a card, and the last card is reachable with G.
        assert screen.current_card() is not None
        await pilot.press("G")
        assert screen.current_card().name == names[-1]


async def test_move_from_my_work_updates_the_board(app) -> None:
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        while app.screen.current_card().board_id != app.store.snapshot.board.id:
            await pilot.press("j")
        card = app.screen.current_card()
        await pilot.press("m", *"done", "enter")
        await pilot.pause()
        assert app.store.snapshot.list_named(app.store.snapshot.card(card.id).list_id) == "Done"
        assert app.store.work.card(card.id).list_id == app.store.snapshot.card(card.id).list_id


async def test_vim_keys(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        lists = app.screen.query_one("#lists")
        await pilot.press("G")
        assert lists.highlighted == 4
        await pilot.press("g", "g")
        assert lists.highlighted == 0
        await pilot.press("g", "x", "j")  # an unknown chord is dropped, then j works
        assert lists.highlighted == 1
        await pilot.press("g", "t")
        assert app.current_mode == "triage"
        await pilot.press("g", "T", "g", "T")
        assert app.current_mode == "notifications"
        await pilot.press("colon")
        assert app.screen.__class__.__name__ == "CommandPalette"


async def test_browser_filter(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("slash", *"#bug", "enter")
        assert [c.name for c in app.screen.cards] == ["Crash when a card has no description"]
        assert app.focused.id == "cards"
        await pilot.press("escape")
        assert len(app.screen.cards) == 3


class SlowBackend(DemoBackend):
    """Holds board loads until the test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def board_snapshot(self, board_id: str):
        await self.release.wait()
        return await super().board_snapshot(board_id)


async def test_loading_animation() -> None:
    backend = SlowBackend()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        spinner = app.screen.query_one(Spinner)
        assert "loading board" in str(spinner.render())
        assert not app.screen.query_one("#body").loading  # no overlay: the spinner is the only indicator
        backend.release.set()
        await pilot.pause()
        assert str(spinner.render()) == ""


async def test_arabic_board(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app.open_board("b-arabic")
        await pilot.pause()
        screen = app.screen
        assert screen.snapshot.board.name == "مشروع الموقع"
        await pilot.press("l", "enter")
        await pilot.pause()
        assert isinstance(app.screen, CardScreen)
        bullets = [line for line in screen_lines(app) if line.endswith(" •")]
        assert len(bullets) == 2  # the description's Arabic list, markers on the right


async def test_rtl_text_takes_up_space() -> None:
    """An RTL BidiText in a Static once rendered zero lines high (a missing final newline)."""
    from textual.app import App
    from textual.widgets import Static

    from tui_trello.ui.bidi import BidiText

    class OneStatic(App):
        def compose(self):
            yield Static(BidiText("عنوان البطاقة"))

    app = OneStatic()
    async with app.run_test(size=(40, 4)) as pilot:
        await pilot.pause()
        assert app.query_one(Static).size.height == 1


class SlowBoards(DemoBackend):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def boards(self):
        await self.release.wait()
        return await super().boards()


async def test_board_picker_keeps_typing_while_loading() -> None:
    backend = SlowBoards()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("b", *"home")
        assert isinstance(app.screen, PickerScreen)  # open before the boards arrive
        backend.release.set()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.store.snapshot.board.name == "Home"


async def test_toggle_labels(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")  # Inbox, first card: "Crash when a card has no description", labelled bug
        card = app.screen.current_card()
        assert [lb.name for lb in card.labels] == ["bug"]
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, LabelPickerScreen)
        await pilot.press(*"ux", "enter")  # on
        await pilot.pause()
        await pilot.press("ctrl+u")  # clear the input (Input's own binding)
        for _ in "ux":
            await pilot.press("backspace")
        await pilot.press(*"bug", "enter")  # off
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert [lb.name for lb in app.store.find_card(card.id).labels] == ["ux"]
        # Every view sees it: the board snapshot has the new labels.
        assert [lb.name for lb in app.store.snapshot.card(card.id).labels] == ["ux"]


async def test_create_label(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press(*"urgent")
        await pilot.pause()
        picker = app.screen
        assert picker.shown[-1].value == ("create", "urgent")
        await pilot.press("enter")
        await pilot.pause()
        assert "urgent" in [lb.name for lb in app.store.find_card(card.id).labels]
        assert "urgent" in [lb.name for lb in app.store.snapshot.labels]
        assert any(c.label == "urgent" and c.hint == "✓" for c in picker.choices)


async def test_checklist(app) -> None:
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("j", "l")  # "Command palette: jump to any card", 1 of 4 ticked
        card = app.screen.current_card()
        assert card.checklist == (1, 4)
        await pilot.press("enter")
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "☐ Update the README.md" in lines
        assert "Tasks  ☑ 1/4" in lines
        assert "1 done hidden" in lines
        assert "☑ Write the tests" not in lines  # ticked, so hidden
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ChecklistPickerScreen)
        assert app.screen.choices[1].label == "Update the README.md"  # matched as shown, without the backticks
        await pilot.press("down", "enter")  # tick the second item
        await pilot.pause()
        assert app.store.find_card(card.id).checklist == (2, 4)
        await pilot.press(*"Ship it")
        await pilot.pause()
        assert [c.value[0] for c in app.screen.shown] == ["add", "new"]
        await pilot.press("enter")  # add to Tasks
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.store.find_card(card.id).checklist == (2, 5)
        assert app.store.snapshot.card(card.id).checklist == (2, 5)  # every view's badge
        lines = "\n".join(screen_lines(app))
        assert "☐ Ship it" in lines
        assert "2 done hidden" in lines  # "Update the README.md" ticked, and hidden with the first


async def test_new_checklist_on_a_card_without_one(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")  # Inbox, first card: no checklist
        card = app.screen.current_card()
        assert not app.screen.query_one("#card-checklists").display
        await pilot.press("x")
        await pilot.pause()
        await pilot.press(*"Release", "enter")  # the only offer: a new checklist
        await pilot.pause()
        await pilot.press(*"Tag it")
        await pilot.pause()
        assert [c.label for c in app.screen.shown] == ["add “Tag it” to Release", "new checklist “Tag it”"]
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.store.find_card(card.id).checklist == (0, 1)
        assert app.screen.query_one("#card-checklists").display


async def test_comment_enter_sends(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"line one", "ctrl+j", *"line two", "enter")
        await pilot.pause()
        comments = await app.store.comments(card.id)
        assert comments[0].text == "line one\nline two"


async def test_mention_autocomplete(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"thanks @gr")
        await pilot.pause()
        prompt = app.screen
        assert [m.username for m in prompt.suggested] == ["grace"]
        await pilot.press("tab")
        await pilot.press(*"and @", "down", "enter")  # down to the second suggestion; enter picks it, not send
        await pilot.pause()
        assert prompt.query_one("TextArea").text == "thanks @grace and @alan "
        await pilot.press("alt+enter", *"bye", "enter")
        await pilot.pause()
        comments = await app.store.comments(card.id)
        assert comments[0].text == "thanks @grace and @alan \nbye"


async def test_escape_closes_suggestions_first(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", "@")
        await pilot.pause()
        prompt = app.screen
        assert prompt.suggested
        await pilot.press("escape")
        assert app.screen is prompt and not prompt.suggested
        await pilot.press("escape")
        assert app.screen is not prompt


async def test_notifications(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert app.store.unread_count == 3
        assert "🔔 3 unread" in screen_lines(app)[0]  # the bell in the browser's top bar
        await pilot.press("4")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, NotificationsScreen)
        lines = "\n".join(screen_lines(app))
        assert "Grace Hopper mentioned you on Move cards between lists" in lines
        assert "Alan Turing moved" not in lines  # read: hidden at first
        assert len(screen.shown) == 3
        await pilot.press("u")
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "Alan Turing moved Show comments on card detail to Done" in lines
        assert "Alan Turing reacted 🎉 to your comment on Split backend from UI" in lines
        await pilot.press("u")
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert app.store.unread_count == 2
        assert [n.type for n in screen.shown] == ["addedToCard", "cardDueSoon"]
        await pilot.press("D")
        await pilot.pause()
        assert app.store.unread_count == 0
        assert "●" not in "\n".join(screen_lines(app)) and "🔔" not in "\n".join(screen_lines(app))
        assert "Nothing unread" in "\n".join(screen_lines(app))


async def test_unread_counts_on_boards_lists_and_cards(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        snapshot = app.store.snapshot
        card = next(c for c in snapshot.cards if c.name == "Move cards between lists")  # two unread
        lines = screen_lines(app)
        assert any(snapshot.list_named(card.list_id) in line and "🔔" in line for line in lines)  # its list
        await pilot.press("b")
        await pilot.pause()
        assert "🔔3 Product roadmap" in "\n".join(screen_lines(app))  # the board picker
        await pilot.press("escape")
        await pilot.pause()
        assert "🔔2" in render.card_block(card, snapshot, unread=app.store.unread_by_card()[card.id]).text.plain
        await pilot.press("2")
        await pilot.pause()
        assert "●" not in "\n".join(screen_lines(app))
        table = app.screen.query_one(DataTable)
        column = table.columns[render.BELL]  # the triage column's header
        assert column.label.plain == "🔔" and column.width == 3
        row = table.get_row(card.id)
        assert row[5].plain == "2" and row[5].style == f"bold {render.BELL_COLOUR}"  # the unread column
        await pilot.press("1")
        await pilot.pause()
        await app.store.mark_card_read(card.id)
        await pilot.pause()
        assert app.store.unread_by_card()[card.id] == 0
        assert "🔔2" not in "\n".join(screen_lines(app))


def test_unread_badge_is_a_bell() -> None:
    assert render.BELL == "\U0001F514"
    assert render.unread_badge(3).plain == "🔔3"
    assert render.unread_badge(3).cell_len == 3
    assert render.unread_badge(0).plain == ""
    card = next(c for c in DemoBackend()._boards["b-product"].cards if c.comment_count)
    assert render.badges(card, unread=2).plain.startswith("🔔2 ") and "●" not in render.badges(card, unread=2).plain


async def test_open_notification_loads_its_board(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("u", "G", "enter")  # the Arabic board's card, read, and on a board that isn't loaded
        await pilot.pause()
        assert isinstance(app.screen, CardScreen)
        assert app.store.snapshot.board.id == "b-arabic"
        assert app.screen.current_card().name == "إصلاح خطأ في نموذج التسجيل (عاجل)"


async def test_new_notification_is_announced(app, backend) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        backend.push_notification(backend.notification("commentCard", "Alan Turing", "Offline cache for boards",
                                                       extra="Should this use [bold]SQLite[/]?"))
        app.check_notifications()
        await pilot.pause()
        [toast] = app._notifications
        assert toast.title == "Alan Turing commented on Offline cache for boards"
        assert toast.message == "Should this use [bold]SQLite[/]?" and not toast.markup
        assert app.store.unread_count == 4
        app.check_notifications()  # nothing new since: no second toast
        await pilot.pause()
        assert len(app._notifications) == 1


async def test_react_to_a_comment(app) -> None:
    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "j", "l")  # Review: Split backend from UI, four comments
        card = app.screen.current_card()
        await pilot.press("R")
        await pilot.pause()
        assert isinstance(app.screen, PickerScreen)
        await pilot.press(*"looks good", "enter")  # Grace's comment, which has 🎉 from Ada (me) and Alan
        await pilot.pause()
        await pilot.press(*"hooray", "enter")  # mine: takes it off
        await pilot.pause()
        comment = next(c for c in await app.store.comments(card.id) if c.text == "Looks good to me.")
        assert comment.reaction_counts("m1") == [("tada", "🎉", 1, False), ("+1", "👍", 1, False)]
        await pilot.press("R", *"looks good", "enter", *"rocket", "enter")
        await pilot.pause()
        comment = next(c for c in await app.store.comments(card.id) if c.text == "Looks good to me.")
        assert ("rocket", "🚀", 1, True) in comment.reaction_counts("m1")
        assert "🚀 you" in "\n".join(screen_lines(app))  # in the preview, with who gave it


async def test_reply_to_a_comment(app) -> None:
    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "j", "l")  # Review: Split backend from UI, four comments
        card = app.screen.current_card()
        await pilot.press("C", *"looks good", "enter")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "> Looks good to me.\n\n@grace "
        await pilot.press(*"thanks", "enter")
        await pilot.pause()
        assert (await app.store.comments(card.id))[0].text == "> Looks good to me.\n\n@grace thanks"


async def test_reply_to_a_long_comment_picks_what_to_quote(app) -> None:
    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        long = "The picker is slow on big boards. " * 10
        await app.store.add_comment(card.id, f"{long.strip()}\n\nCan we cache the lists?")
        await pilot.press("c", *"draft", "escape")  # an unsent comment stays, with the quote after it
        await pilot.pause()
        await pilot.press("C", "enter")  # the newest comment, mine
        await pilot.pause()
        assert isinstance(app.screen, PickerScreen)
        await pilot.press(*"cache", "enter")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "draft\n\n> Can we cache the lists?\n\n"


async def test_reply_from_notifications(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("C")  # Grace's mention, the newest
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "> @ada can you check the picker remembers the last list?\n\n@grace "
        await pilot.press(*"yes", "enter")
        await pilot.pause()
        card_id = app.store.notifications[0].card_id
        assert (await app.store.comments(card_id))[0].text.endswith("@grace yes")
        await pilot.press("j", "C")  # added to a card: nothing to reply to
        await pilot.pause()
        assert isinstance(app.screen, NotificationsScreen)


async def test_notification_comments_wrap(app, backend) -> None:
    words = " ".join(f"word{n}" for n in range(200))
    backend.push_notification(backend.notification("commentCard", "Alan Turing", "Split backend from UI",
                                                   extra=f"Short start.\n\n{words}"))
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        lines = screen_lines(app)
        top = next(i for i, line in enumerate(lines) if "Alan Turing commented on" in line)
        comment = lines[top + 1:top + 1 + NotificationsScreen.COMMENT_LINES]
        assert "Product roadmap · Short start. word0" in comment[0]
        assert all("word" in line for line in comment) and comment[-1].rstrip().endswith("…")
        assert "Grace Hopper mentioned you" in lines[top + 1 + NotificationsScreen.COMMENT_LINES]  # the next row


async def test_help_shows_the_keys_for_the_view(app) -> None:
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("4", "question_mark")
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "Keys in notifications" in lines and "mark all read" in lines
        assert "move to another list" not in lines and "cycle sort" not in lines
        await pilot.press("a")  # every key
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "move to another list" in lines and "cycle sort" in lines
        await pilot.press("escape", "2", "question_mark")
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "Keys in triage" in lines and "cycle sort" in lines and "move to another list" in lines
        assert "mark all read" not in lines and "show or hide the preview" not in lines


async def test_hiding_read_notifications_is_remembered(backend, state_dir) -> None:
    app = TrelloApp(backend, Settings(default_board="b-product", layout="notifications"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert len(app.screen.shown) == 3
        await pilot.press("u")
        await pilot.pause()
        assert len(app.screen.shown) == 7
    app = TrelloApp(backend, Settings(default_board="b-product", layout="notifications"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert len(app.screen.shown) == 7  # still showing read ones, after a restart
        assert (state_dir / "tui-trello" / "prefs.json").exists()


async def test_tip_when_there_is_no_card(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        view = app.screen.query_one(CardView)
        assert not view.has_class("empty")
        view.show(None, app.store.snapshot)
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "💡 Tip" in lines and "No comments" not in lines and "No description" not in lines
        tip = view.tip
        view.next_tip()
        assert view.tip == (tip + 1) % len(TIPS)


async def test_copy_links(app, monkeypatch) -> None:
    monkeypatch.setattr(clipboard, "command", lambda: None)  # not the real clipboard, the app's OSC 52 copy
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "j", "l")
        card = app.screen.current_card()
        await pilot.press("y")
        assert app.clipboard == card.url
        await pilot.press("Y")
        await pilot.pause()
        await pilot.press(*"looks good", "enter")
        await pilot.pause()
        comment = next(c for c in await app.store.comments(card.id) if c.text == "Looks good to me.")
        assert app.clipboard == f"{card.url}#comment-{comment.id}"


async def test_copy_and_open_board_link(app, monkeypatch) -> None:
    monkeypatch.setattr(clipboard, "command", lambda: None)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        board_url = app.store.snapshot.board.url
        assert board_url
        await pilot.press("y")  # the lists column has focus
        assert app.clipboard == board_url
        await pilot.press("o")
        assert opened == [board_url]
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("y")
        assert app.clipboard == card.url
        await pilot.press("B")
        assert app.clipboard == board_url


async def test_attachments(app, monkeypatch, tmp_path) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr(store_module, "download_dir", lambda: tmp_path / "Downloads")
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "l")  # Doing: Move cards between lists, a file and a link
        card = app.screen.current_card()
        assert card.attachment_count == 2
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "picker-sketch.png" in lines and "example.com" in lines  # in the preview
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, AttachmentPickerScreen)
        await pilot.press("ctrl+s")  # the file
        await pilot.pause()
        assert (tmp_path / "Downloads" / "picker-sketch.png").read_bytes().startswith(b"\x89PNG")
        await pilot.press("ctrl+j", "enter")  # the link
        await pilot.pause()
        assert opened == ["https://example.com/pr/42"] and not isinstance(app.screen, AttachmentPickerScreen)


async def test_attach_a_file_and_a_link(app, monkeypatch, tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("remember")
    (tmp_path / "sub").mkdir()
    monkeypatch.setattr(FilePickerScreen, "last_dir", tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*"attach a file", "enter")
        await pilot.pause()
        assert isinstance(app.screen, FilePickerScreen)
        assert [c.label for c in app.screen.choices] == ["../", "sub/", "notes.txt"]
        await pilot.press(*"notes", "enter")
        await pilot.pause()
        assert isinstance(app.screen, AttachmentPickerScreen)
        await pilot.press(*"https://example.com/spec", "enter")
        await pilot.pause()
        names = [a.name for a in await app.store.attachments(card.id)]
        assert names == ["notes.txt", "https://example.com/spec"]
        assert app.store.find_card(card.id).attachment_count == 2  # the 📎 badge


async def test_attach_a_file_to_a_comment(app, monkeypatch, tmp_path) -> None:
    (tmp_path / "trace.log").write_text("boom")
    monkeypatch.setattr(FilePickerScreen, "last_dir", tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"see ", "ctrl+o")
        await pilot.pause()
        await pilot.press(*"trace", "enter")
        await pilot.pause()
        [attachment] = await app.store.attachments(card.id)
        assert app.screen.query_one(TextArea).text == f"see [trace.log]({attachment.url})"
        await pilot.press("enter")
        await pilot.pause()
        assert (await app.store.comments(card.id))[0].text == f"see [trace.log]({attachment.url})"


async def test_comment_draft(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"half a thought", "escape")
        await pilot.pause()
        assert app.store.draft("comment", card.id).text == "half a thought"
        assert "✐ draft  c: unsent comment" in "\n".join(screen_lines(app))  # in the preview
        await pilot.press("c")
        await pilot.pause()
        assert app.screen.query_one("TextArea").text == "half a thought"
        await pilot.press(*" finished", "enter")
        await pilot.pause()
        assert (await app.store.comments(card.id))[0].text == "half a thought finished"
        assert app.store.draft("comment", card.id) is None
        assert "✐ draft" not in "\n".join(screen_lines(app))


async def test_draft_survives_a_restart(backend) -> None:
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"before the crash")
        await pilot.pause(0.6)  # written a moment after typing stops, without closing the box
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l", "c")
        await pilot.pause()
        assert app.screen.query_one("TextArea").text == "before the crash"
        assert app.store.draft("comment", card.id).text == "before the crash"


class FailingComments(DemoBackend):
    async def add_comment(self, card_id: str, text: str):
        raise BackendError("Could not reach Trello.")


async def test_failed_comment_is_kept() -> None:
    app = TrelloApp(FailingComments(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        await pilot.press("c", *"important", "enter")
        await pilot.pause()
        assert app.store.draft("comment", card.id).text == "important"


async def test_edit_description(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("l")  # Inbox, first card: no description
        card = app.screen.current_card()
        await pilot.press("e", *"First line", "enter", *"second line")  # enter is a new line here
        await pilot.press("escape")
        await pilot.pause()
        assert app.store.draft("desc", card.id).text == "First line\nsecond line"
        assert app.store.find_card(card.id).desc == ""  # not saved yet
        await pilot.press("e", "ctrl+s")
        await pilot.pause()
        assert app.store.find_card(card.id).desc == "First line\nsecond line"
        assert app.store.draft("desc", card.id) is None
        assert "second line" in "\n".join(screen_lines(app))


async def test_description_changed_since_the_draft(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("l")
        card = app.screen.current_card()
        app.store.save_draft("desc", card.id, "my version", base="what it said when I started")
        await pilot.press("e")
        await pilot.pause()
        assert "has changed on Trello" in "\n".join(screen_lines(app))
        assert app.screen.query_one("TextArea").text == "my version"


def backgrounds(app) -> dict[str, int]:
    """Cells per background colour on the screen; "default" is the terminal's own."""
    counts: dict[str, int] = {}
    for line in app.screen._compositor.render_update(full=True).strips:
        for strip in [line] if hasattr(line, "_segments") else line:
            for segment in strip:
                colour = segment.style.bgcolor if segment.style else None
                key = "default" if colour is None or colour.is_default else colour.name
                counts[key] = counts.get(key, 0) + len(segment.text)
    return counts


@pytest.mark.parametrize("keys", [(), ("2",), ("3",), ("c",), ("question_mark",)])
async def test_transparent_background(app, keys) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause(0.2)
        await pilot.press("l", *keys)
        await pilot.pause(0.2)
        counts = backgrounds(app)
        painted = sum(n for colour, n in counts.items() if colour != "default")
        assert painted < 400, counts  # the cursor row, label chips and text cursor; no panels
        assert painted > 0  # the cursor still shows


async def test_text_cursor_shows_on_a_transparent_background(app) -> None:
    """The cursor used to come out reversed theme colours, dark on a dark terminal: it must reverse the terminal's."""
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l", "c", *"hi")
        await pilot.pause()
        cursor = app.screen.query_one("TextArea").get_component_rich_style("text-area--cursor")
        assert cursor.reverse and cursor.color.is_default and cursor.bgcolor.is_default


async def test_opaque_background(backend) -> None:
    app = TrelloApp(backend, Settings(default_board="b-product", transparent=False))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause(0.2)
        assert backgrounds(app).get("default", 0) < 100


def list_id(app, name: str) -> str:
    return next(lst.id for lst in app.store.snapshot.lists if lst.name == name)


def toasts(app) -> list[str]:
    return [toast.message for toast in app._notifications]


async def test_new_card_in_the_browser(app, backend) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("j", "n")  # on the lists column, "Next up"
        await pilot.pause()
        assert app.screen.query_one(".title").content == "New card in “Next up”"
        await pilot.press(*"Write the plan", "ctrl+j", *"First the goal.", "ctrl+j", *"Then the steps.", "enter")
        await pilot.pause()
        next_up = list_id(app, "Next up")
        card = app.store.snapshot.cards_in(next_up)[-1]
        assert (card.name, card.desc) == ("Write the plan", "First the goal.\nThen the steps.")
        assert app.screen.current_card() == card
        assert app.screen.query_one("#cards").has_focus
        assert (await backend.board_snapshot("b-product")).card(card.id) == card
        assert card_drafts(next_up) == []
        assert toasts(app) == ["Added “Write the plan” to Next up"]


async def test_new_card_from_triage(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("j", "j", "j")  # a card on "Next up", under the default sort by list
        row_list = app.screen.current_card().list_id
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, PickerScreen)
        first = app.screen.choices[0]
        assert (first.value.id, first.hint) == (row_list, "this card's list")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press(*"Triage me", "enter")
        await pilot.pause()
        card = app.screen.current_card()
        assert (card.name, card.list_id) == ("Triage me", row_list)
        assert card in app.screen.rows
        await pilot.press("1")
        await pilot.pause()
        assert card in app.store.snapshot.cards_in(row_list)


async def test_new_card_from_my_work(app, backend) -> None:
    async with app.run_test(size=(140, 30)) as pilot:
        await pilot.pause()
        await pilot.press("b", *"home", "enter")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert all("›" in choice.label for choice in app.screen.choices)
        await pilot.press(*"home to do", "enter")
        await pilot.pause()
        await pilot.press(*"Clean the gutters", "enter")
        await pilot.pause()
        to_do = list_id(app, "To do")
        card = app.store.snapshot.cards_in(to_do)[-1]
        assert (card.name, card.member_ids) == ("Clean the gutters", ())  # unassigned
        assert card.id not in app.screen.cards_by_option
        assert (await backend.board_snapshot("b-home")).card(card.id) == card
        assert toasts(app) == ["Added “Clean the gutters” to Home › To do"]
        await pilot.press("1")
        await pilot.pause()
        assert card in app.screen.cards  # the browser shows Home's first list, To do


class FailingCards(DemoBackend):
    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom"):
        raise BackendError("Could not reach Trello.")


async def test_failed_new_card_is_kept() -> None:
    app = TrelloApp(FailingCards(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        before = list(app.store.snapshot.cards)
        await pilot.press("n", *"important", "ctrl+j", *"why", "enter")
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        assert card_drafts(inbox) == ["important\nwhy"]
        assert app.store.snapshot.cards == before
        assert "The card is kept as a draft: n to try again." in toasts(app)[0]
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "important\nwhy"
        assert "Your unsent card" in "\n".join(screen_lines(app))


async def test_new_card_escape_and_blank(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        before = len(app.store.snapshot.cards)
        await pilot.press("n", "escape")
        await pilot.pause()
        await pilot.press("n", "space", "enter")
        await pilot.pause()
        assert len(app.store.snapshot.cards) == before
        assert card_drafts(list_id(app, "Inbox")) == []
        await pilot.press("n", *"x  y ", "ctrl+j", "ctrl+j", *"  indented  ", "ctrl+j", *"end", "ctrl+j", "ctrl+j",
                          "enter")
        await pilot.pause()
        card = app.store.snapshot.cards_in(list_id(app, "Inbox"))[-1]
        assert (card.name, card.desc) == ("x y", "  indented  \nend")


async def test_new_card_needs_a_name(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        before = len(app.store.snapshot.cards)
        await pilot.press("n", "space", "ctrl+j", *"only a description", "enter")
        await pilot.pause()
        assert len(app.store.snapshot.cards) == before
        assert toasts(app) == ["A card needs a name on the first line"]
        assert card_drafts(list_id(app, "Inbox")) == [" \nonly a description"]


class SlowCards(DemoBackend):
    """Holds each create until `release` is set, and fails it if `fail` is."""

    def __init__(self) -> None:
        super().__init__()
        self.release, self.fail = asyncio.Event(), False

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom"):
        await self.release.wait()
        if self.fail:
            raise BackendError("Could not reach Trello.")
        return await super().create_card(list_id, name, desc, pos=pos)


def card_drafts(list_id: str) -> list[str]:
    """The texts of the list's new-card drafts, as saved on disk, oldest first."""
    try:
        saved = json.loads(drafts_path().read_text())
    except OSError:
        return []
    return [draft["text"] for key, draft in saved.items() if key.startswith(f"card:{list_id}")]


def slow_app(fail: bool = False) -> tuple[TrelloApp, SlowCards]:
    backend = SlowCards()
    backend.fail = fail
    return TrelloApp(backend, Settings(default_board="b-product")), backend


def box_notice(app) -> str:
    """The notice in the new-card box: why it starts with text, if it does."""
    return "".join(str(label.content) for label in app.screen.query(".notice"))


async def test_new_card_kept_while_sending() -> None:
    app, _ = slow_app()  # never released
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        await pilot.press("n", *"first", "enter")
        await pilot.pause()
        assert card_drafts(inbox) == ["first"]  # until Trello has it
    # Quit while the card was being made: the next n on the list offers it again, as perhaps made already.
    app = TrelloApp(DemoBackend(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "first"
        assert box_notice(app) == "This card may already have been made on Trello: check before sending"
        await pilot.press("enter")
        await pilot.pause()
        assert app.store.snapshot.cards_in(inbox)[-1].name == "first"
        assert card_drafts(inbox) == []


async def test_new_card_escape_keeps_the_text(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        await pilot.press("n", *"keep me", "escape")
        await pilot.pause()
        assert card_drafts(inbox) == ["keep me"]
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "keep me"
        assert box_notice(app) == "Your unsent card"


async def test_two_new_card_boxes_on_one_list(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        screen = app.screen
        screen.action_new_card()  # two quick n presses: the second before the first box is up
        screen.action_new_card()
        await pilot.pause()
        assert sum(isinstance(screen, TextPromptScreen) for screen in app.screen_stack) == 2
        await pilot.press(*"top", "escape")
        await pilot.pause()
        await pilot.press(*"under", "escape")
        await pilot.pause()
        assert sorted(card_drafts(inbox)) == ["top", "under"]  # neither overwrites the other
        await pilot.press("n")
        await pilot.pause()
        assert box_notice(app) == "Your unsent card (1 of 2)"


async def test_new_card_while_one_is_sent() -> None:
    app, backend = slow_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        await pilot.press("n", *"first", "enter")
        await pilot.pause()
        await pilot.press("n")  # while the first is being made
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == ""
        await pilot.press(*"second")
        backend.release.set()  # made while the second box is open
        await pilot.pause()
        assert app.store.snapshot.cards_in(inbox)[-1].name == "first"
        assert isinstance(app.screen, TextPromptScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert card_drafts(inbox) == ["second"]  # only the sent card's text goes


async def test_failed_new_card_while_another_is_written() -> None:
    app, backend = slow_app(fail=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        inbox = list_id(app, "Inbox")
        await pilot.press("n", *"first", "ctrl+j", *"why", "enter")
        await pilot.pause()
        await pilot.press("n")  # a second box, open when the first fails
        await pilot.pause()
        backend.release.set()
        await pilot.pause()
        assert "The card is kept as a draft: n to try again." in toasts(app)[0]
        await pilot.press(*"other", "escape")
        await pilot.pause()
        assert card_drafts(inbox) == ["first\nwhy", "other"]  # oldest first; neither overwrites the other
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "first\nwhy"
        assert box_notice(app) == "Your unsent card (1 of 2)"
        backend.fail = False
        await pilot.press("enter")
        await pilot.pause()
        assert card_drafts(inbox) == ["other"]


async def test_new_card_with_several_drafts_on_the_list() -> None:
    backend = DemoBackend()
    inbox = (await backend.board_snapshot("b-product")).lists[0]
    drafts_path().parent.mkdir(parents=True, exist_ok=True)
    drafts_path().write_text(json.dumps({f"card:{inbox.id}/{n}": {"text": n} for n in ("one", "two", "three")}))
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        rows = [line for line in screen_lines(app) if "✐" in line]
        assert len(rows) == 1 and inbox.name in rows[0]  # the lists column marks the list
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "one"
        assert box_notice(app) == "Your unsent card (1 of 3)"


def timed_out() -> BackendError:
    exc = BackendError("Could not reach Trello: timed out.")
    exc.unsure = True  # the request may have reached Trello
    return exc


class UnsureCards(DemoBackend):
    """Makes the card, then loses Trello's answer, as a timeout after Trello has acted would."""

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom"):
        await super().create_card(list_id, name, desc, pos=pos)
        raise timed_out()


async def test_new_card_outcome_unknown() -> None:
    app = TrelloApp(UnsureCards(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n", *"Maybe", "enter")
        await pilot.pause()
        assert "The card may have been made on Trello anyway: check before sending it again (n)." in toasts(app)[0]
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "Maybe"
        assert box_notice(app) == "This card may already have been made on Trello: check before sending"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("r")  # the reload brings the card Trello made
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert box_notice(app) == ("This card may already have been made on Trello: “Maybe” is on Inbox already; "
                                   "check before sending")


class UnsureThenRefused(DemoBackend):
    """Makes the card and loses the answer the first time, then can't reach Trello at all."""

    def __init__(self) -> None:
        super().__init__()
        self.tries = 0

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom"):
        self.tries += 1
        if self.tries == 1:
            await super().create_card(list_id, name, desc, pos=pos)
            raise timed_out()
        raise BackendError("Could not reach Trello: connection refused.")


async def test_new_card_failure_keeps_an_unknown_outcome() -> None:
    app = TrelloApp(UnsureThenRefused(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n", *"Maybe", "enter")
        await pilot.pause()
        await pilot.press("n", "enter")  # resent, and never reaches Trello: the first may still have made it
        await pilot.pause()
        assert "The card is kept as a draft: n to try again." in toasts(app)[-1]
        await pilot.press("n")
        await pilot.pause()
        assert box_notice(app) == "This card may already have been made on Trello: check before sending"


async def test_new_card_edit_keeps_an_unknown_outcome() -> None:
    app = TrelloApp(UnsureCards(), Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n", *"Maybe", "enter")
        await pilot.pause()
        await pilot.press("n", *" not", "escape")  # edited, not sent: Trello may still have made it
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "Maybe not"
        assert box_notice(app) == "This card may already have been made on Trello: check before sending"


async def test_failed_new_card_is_offered_first() -> None:
    backend = FailingCards()
    inbox = (await backend.board_snapshot("b-product")).lists[0]
    drafts_path().parent.mkdir(parents=True, exist_ok=True)
    drafts_path().write_text(json.dumps({f"card:{inbox.id}/old": {"text": "old"}}))
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app.screen.action_new_card()  # the old draft's box, under a new one
        app.screen.action_new_card()
        await pilot.pause()
        await pilot.press(*"new", "enter")
        await pilot.pause()
        assert "n to try again" in toasts(app)[-1]
        await pilot.press("escape")  # the old draft's box
        await pilot.pause()
        await pilot.press("n")  # tries the card that failed again, not the oldest
        await pilot.pause()
        assert app.screen.query_one(TextArea).text == "new"
        assert box_notice(app) == "Your unsent card (1 of 2)"


class ReloadingCards(DemoBackend):
    """Has the board reloaded while a card is being made, as `r` or the refresh timer might."""

    store = None

    async def create_card(self, list_id: str, name: str, desc: str = "", *, pos: str = "bottom"):
        card = await super().create_card(list_id, name, desc, pos=pos)
        await self.store.open_board(card.board_id)
        return card


async def test_create_card_already_reloaded() -> None:
    backend = ReloadingCards()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        backend.store = app.store
        card = await app.store.create_card(app.store.snapshot.lists[0], "Once")
        assert [c.id for c in app.store.snapshot.cards].count(card.id) == 1


async def test_new_card_after_moving_away() -> None:
    backend = SlowCards()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n", *"Elsewhere", "enter")
        await pilot.pause()
        await pilot.press("j")  # to "Next up" while the card is being made on "Inbox"
        backend.release.set()
        await pilot.pause()
        assert toasts(app) == ["Added “Elsewhere” to Inbox"]  # nothing about a filter: there is none
        assert app.screen.list_id == list_id(app, "Next up")
        assert app.screen.query_one("#lists").has_focus  # left where the user went


async def test_new_card_while_filtering() -> None:
    app, backend = slow_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("n", *"Quietly", "enter")
        await pilot.pause()
        await pilot.press("slash", *"qui")  # typing a filter when the card is made
        backend.release.set()
        await pilot.pause()
        assert app.screen.query_one("#filter").has_focus
        await pilot.press("e")
        assert app.screen.query_one("#filter").value == "quie"
        assert toasts(app) == ["Added “Quietly” to Inbox"]


async def test_new_card_hidden_by_filter(app) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("slash", *"#bug", "enter")
        await pilot.pause()
        await pilot.press("n", *"Not a bug", "enter")
        await pilot.pause()
        card = app.store.snapshot.cards_in(list_id(app, "Inbox"))[-1]
        assert card.name == "Not a bug" and card not in app.screen.cards
        assert toasts(app) == ["Added “Not a bug” to Inbox (hidden by the filter; esc clears it)"]


async def test_help_lists_new_card(app) -> None:
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert "new card:" in "\n".join(screen_lines(app))
        await pilot.press("escape", "l", "enter", "question_mark")
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "Keys in a card" in lines
        assert "new card:" not in lines
        await pilot.press("escape", "n")  # does nothing on a card
        await pilot.pause()
        assert isinstance(app.screen, CardScreen)


async def test_new_card_after_moving_within_the_list() -> None:
    app, backend = slow_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("l")  # into Inbox's cards
        await pilot.press("n", *"Later", "enter")
        await pilot.pause()
        await pilot.press("j")  # to the next card while the new one is being made
        moved_to = app.screen.current_card()
        backend.release.set()
        await pilot.pause()
        assert app.store.snapshot.cards_in(list_id(app, "Inbox"))[-1].name == "Later"
        assert app.screen.current_card() == moved_to  # left where the user put it


async def test_new_card_filter_note_only_for_the_board_on_screen() -> None:
    app, backend = slow_app()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("slash", *"#bug", "enter")
        await pilot.pause()
        await pilot.press("n", *"Not a bug", "enter")
        await pilot.pause()
        await pilot.press("b", *"home", "enter")  # another board while the card is being made
        await pilot.pause()
        assert app.store.snapshot.board.id == "b-home" and app.screen.query_text == "#bug"
        backend.release.set()
        await pilot.pause()
        assert "Added “Not a bug” to Inbox" in toasts(app)  # the filter on screen isn't hiding it


class HeldReloads(DemoBackend):
    """Once `hold` is set, holds each board fetch, taken when asked, until `release` is set."""

    def __init__(self) -> None:
        super().__init__()
        self.hold, self.release = False, asyncio.Event()

    async def board_snapshot(self, board_id: str):
        snapshot = await super().board_snapshot(board_id)
        if self.hold:
            await self.release.wait()
        return snapshot


async def test_new_card_outlives_an_older_reload() -> None:
    backend = HeldReloads()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        backend.hold = True
        reload = asyncio.create_task(app.store.open_board("b-product"))  # fetched before the card is made
        await pilot.pause()
        card = await app.store.create_card(app.store.snapshot.lists[0], "Made meanwhile")
        backend.release.set()
        await reload
        assert app.store.snapshot.card(card.id) == card
        assert [c.id for c in app.store.snapshot.cards].count(card.id) == 1
        backend.hold = False
        await app.store.open_board("b-product")  # a reload after it was made brings it itself
        assert [c.id for c in app.store.snapshot.cards].count(card.id) == 1


async def test_new_card_moved_outlives_an_older_reload() -> None:
    backend = HeldReloads()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        backend.hold = True
        reload = asyncio.create_task(app.store.open_board("b-product"))
        await pilot.pause()
        lists = app.store.snapshot.lists
        card = await app.store.create_card(lists[0], "Moved meanwhile")
        moved = await app.store.move_card(card, lists[1].id)
        backend.release.set()
        await reload
        assert app.store.snapshot.card(card.id) == moved  # as it is now, not as it was made


class FailingReloads(HeldReloads):
    async def board_snapshot(self, board_id: str):
        snapshot = await super().board_snapshot(board_id)
        if self.hold:
            raise BackendError("Could not reach Trello.")
        return snapshot


async def test_failed_reload_forgets_the_cards_made_meanwhile() -> None:
    backend = FailingReloads()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        backend.hold = True
        reload = asyncio.create_task(app.store.open_board("b-product"))
        await pilot.pause()
        await app.store.create_card(app.store.snapshot.lists[0], "Made meanwhile")
        backend.release.set()
        with pytest.raises(BackendError):
            await reload
        assert not app.store._made  # no fetch under way can have missed it


async def test_done_check_items_hidden_until_shown(app, backend) -> None:
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("j", "l")  # "Command palette: jump to any card": "Write the tests" ticked
        await pilot.pause()
        lines = "\n".join(screen_lines(app))
        assert "☐ Update the README.md" in lines and "1 done hidden" in lines and "X: show done items" in lines
        assert "☑ Write the tests" not in lines
        await pilot.press("enter", "X")
        await pilot.pause()
        assert isinstance(app.screen, CardScreen)
        lines = "\n".join(screen_lines(app))
        assert "☑ Write the tests" in lines and "X: hide done items" in lines
        assert "done hidden" not in lines
        assert app.prefs.show_done_check_items
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, BrowserScreen)
        assert "☑ Write the tests" in "\n".join(screen_lines(app))  # redrawn while under the card screen
        await pilot.press("X")
        await pilot.pause()
        assert "☑ Write the tests" not in "\n".join(screen_lines(app))
        await pilot.press("X")
        await pilot.pause()
        assert "☑ Write the tests" in "\n".join(screen_lines(app))
        await pilot.press("2", "X")  # triage has no card pane
        await pilot.pause()
        assert app.prefs.show_done_check_items
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        await pilot.press("j", "l")
        await pilot.pause()
        assert "☑ Write the tests" in "\n".join(screen_lines(app))  # still shown, after a restart


# -- following links ---------------------------------------------------------------------------------------------


async def settle(pilot, times: int = 4) -> None:
    for _ in range(times):
        await pilot.pause()


async def on_links_card(app, pilot) -> None:
    """The browser with "Offline cache for boards", whose description has the demo's links, as the current card."""
    await pilot.pause()
    await pilot.press("j", "l", "j", "j")
    assert app.screen.current_card().name == "Offline cache for boards"
    await settle(pilot)


def card_named(backend, name: str):
    return next(c for s in backend._boards.values() for c in s.cards if c.name == name)


def card_screens(app) -> list[CardScreen]:
    return [s for s in app.screen_stack if isinstance(s, CardScreen)]


def comment_in_view(app, comment_id: str) -> bool:
    widget = app.screen.query_one(f"#comment-{comment_id}")
    return widget.has_class("target") and app.screen.query_one(CardView).region.contains_region(widget.region)


async def test_follow_card_link(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        assert isinstance(app.screen, LinkPickerScreen)
        assert [c.label for c in app.screen.choices] == [
            "Move cards between lists", "review comment", "picker-sketch.png", "Home", "textual.textualize.io/"]
        assert [c.hint for c in app.screen.choices][:4] == [
            "card · description", "comment · description", "attachment · description", "board · description"]
        await pilot.press(*"move", "enter")
        await settle(pilot)
        assert isinstance(app.screen, CardScreen)
        assert app.screen.current_card().name == "Move cards between lists"
        await pilot.press("escape")
        assert isinstance(app.screen, BrowserScreen)


async def test_follow_comment_link(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"review", "enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen)
        assert app.screen.current_card().name == "Split backend from UI"
        grace = next(c for c in await app.store.comments(app.screen.card_id) if c.author == "Grace Hopper")
        assert comment_in_view(app, grace.id)


async def test_follow_comment_link_on_the_same_card(app, backend) -> None:
    from tui_trello.ui import follow

    split = card_named(backend, "Split backend from UI")
    grace = next(c for c in await backend.comments(split.id) if c.author == "Grace Hopper")
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app.open_card(split.id)
        await settle(pilot, 8)
        assert not app.screen.query(".comment.target")
        await follow.follow(app, split.comment_url(grace.id))
        await settle(pilot, 8)
        assert len(card_screens(app)) == 1 and comment_in_view(app, grace.id)
        app.screen.query_one(CardView).scroll_home(animate=False)
        await follow.follow(app, split.comment_url(grace.id))
        await settle(pilot, 8)
        assert len(card_screens(app)) == 1 and comment_in_view(app, grace.id)
        await follow.follow(app, split.url)
        await pilot.pause()
        assert [t.message for t in app._notifications][-1] == "That's this card"


async def test_follow_link_to_another_board(app, backend) -> None:
    arabic = card_named(backend, "إصلاح خطأ في نموذج التسجيل (عاجل)")
    shortcut = card_named(backend, "Command palette: jump to any card")
    await backend.add_comment(shortcut.id, f"see {arabic.url}")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j", "l")
        assert app.screen.current_card().id == shortcut.id
        await pilot.press("L")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == arabic.id
        assert app.store.snapshot.board.id == "b-arabic"


async def test_follow_attachment_link(app, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(store_module, "download_dir", lambda: tmp_path / "Downloads")
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"picker", "enter")
        await settle(pilot)
        assert isinstance(app.screen, AttachmentPickerScreen)
        assert app.screen.highlighted().name == "picker-sketch.png"
        await pilot.press("ctrl+s")
        await settle(pilot)
        assert (tmp_path / "Downloads" / "picker-sketch.png").read_bytes().startswith(b"\x89PNG")


async def test_follow_attachment_link_highlights_that_attachment(app, backend, tmp_path) -> None:
    from tui_trello.ui import follow

    (tmp_path / "notes.txt").write_text("remember")
    moving = card_named(backend, "Move cards between lists")
    notes = await backend.attach_file(moving.id, tmp_path / "notes.txt")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await follow.follow(app, notes.url)
        await settle(pilot)
        assert isinstance(app.screen, AttachmentPickerScreen) and app.screen.highlighted().id == notes.id
        await pilot.press("escape")
        await follow.follow(app, notes.url.replace(notes.id, "gone"))
        await pilot.pause()
        assert [t.message for t in app._notifications][-1] == "That attachment is no longer on its card"


async def test_follow_board_link(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("enter")  # the card screen
        await settle(pilot)
        assert isinstance(app.screen, CardScreen)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"home", "enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, BrowserScreen) and not card_screens(app)
        assert app.store.snapshot.board.id == "b-home"


async def test_follow_web_link(app, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"textual", "enter")
        await settle(pilot)
        assert opened == ["https://textual.textualize.io/"]


async def test_follow_link_ctrl_o_opens_browser(app, backend, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"move", "ctrl+o")
        await settle(pilot)
        assert opened == [card_named(backend, "Move cards between lists").url]
        assert isinstance(app.screen, BrowserScreen)


async def test_link_picker_copies_the_link(app, monkeypatch) -> None:
    monkeypatch.setattr(clipboard, "command", lambda: None)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"textual", "ctrl+y")
        assert app.clipboard == "https://textual.textualize.io/"


async def test_unsafe_link_is_not_opened(app, monkeypatch) -> None:
    from tui_trello.ui import follow

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        for url in ("javascript:alert(1)", "file:///etc/passwd"):
            await follow.follow(app, url)
        await pilot.pause()
        assert opened == []
        assert [t.message for t in app._notifications] == ["Not opening a javascript: link",
                                                            "Not opening a file: link"]
        assert {t.severity for t in app._notifications} == {"warning"}


async def test_unresolvable_link_is_a_toast(app) -> None:
    from tui_trello.ui import follow

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await follow.follow(app, "https://trello.example/c/nope")
        await pilot.pause()
        [toast] = app._notifications
        assert toast.severity == "error" and "No card nope" in toast.message
        assert isinstance(app.screen, BrowserScreen)


async def test_click_follows_link(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        lines = screen_lines(app)
        y = next(i for i, line in enumerate(lines) if "the Home board" in line)
        await pilot.click(offset=(lines[y].index("Home") + 1, y))
        await settle(pilot, 8)
        assert app.store.snapshot.board.id == "b-home"
        assert isinstance(app.screen, BrowserScreen)


async def test_no_links(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("l")  # Inbox: Crash when a card has no description
        await pilot.press("L")
        await settle(pilot)
        assert isinstance(app.screen, BrowserScreen)
        assert [t.message for t in app._notifications] == ["No links on this card"]


async def test_missing_comment(app, backend) -> None:
    from tui_trello.ui import follow

    split = card_named(backend, "Split backend from UI")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await follow.follow(app, split.comment_url("made-up"))
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == split.id
        assert [t.message for t in app._notifications][-1].startswith("That comment isn't on the card any more")
        assert not app.screen.query(".comment.target")


async def test_help_lists_follow_link(app) -> None:
    async with app.run_test(size=(120, 100)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert any("follow a link" in line and "L" in line.split() for line in screen_lines(app))


async def test_browsing_fast_leaves_the_last_cards_comments(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("j", "j", "l", "j", "k", "j", "k", "j")
        await settle(pilot, 8)
        card = app.screen.current_card()
        ids = [c.id for c in app.screen.query_one("#card-comments").children]
        assert ids == [f"comment-{c.id}" for c in await app.store.comments(card.id)] or not ids


class FailingBoard(DemoBackend):
    async def board_snapshot(self, board_id: str):
        if board_id == "b-arabic":
            raise BackendError("Could not reach Trello.")
        return await super().board_snapshot(board_id)


async def test_notification_stays_unread_when_its_board_fails_to_load(backend) -> None:
    backend.push_notification(backend.notification("commentCard", "Alan Turing", "إصلاح خطأ في نموذج التسجيل (عاجل)"))
    failing = FailingBoard()
    failing._notifications, failing._boards = backend._notifications, backend._boards
    app = TrelloApp(failing, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        unread = app.store.unread_count
        await pilot.press("4")
        await settle(pilot)
        assert app.screen.shown[0].card_name == "إصلاح خطأ في نموذج التسجيل (عاجل)"
        await pilot.press("enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, NotificationsScreen)
        assert app.store.unread_count == unread
        assert [t.title for t in app._notifications] == ["Could not open board"]


async def test_notification_of_a_gone_card_is_marked_read(app, backend) -> None:
    note = backend.notification("commentCard", "Alan Turing", "Split backend from UI")
    backend.push_notification(note := type(note)(**{**note.__dict__, "card_id": "gone"}))
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        unread = app.store.unread_count
        await pilot.press("4")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot, 8)
        assert app.store.unread_count == unread - 1
        assert [t.message for t in app._notifications] == ["That card has been archived or deleted."]


class SlowSections(DemoBackend):
    """Answers a card's attachments and checklists only when released, after its comments."""

    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def attachments(self, card_id: str):
        await self.release.wait()
        return await super().attachments(card_id)

    async def checklists(self, card_id: str):
        await self.release.wait()
        return await super().checklists(card_id)


async def test_scroll_to_linked_comment_survives_late_sections() -> None:
    from tui_trello.ui import follow

    backend = SlowSections()
    split = card_named(backend, "Split backend from UI")
    comments = await backend.comments(split.id)
    first = comments[0]
    backend._attachments[split.id] = [await backend.attach_link(split.id, f"https://example.com/{n}")
                                      for n in range(6)]
    backend._checklists[split.id] = [Checklist("cl1", "Things", tuple(CheckItem(f"ci{n}", f"item {n}", False, n)
                                                                       for n in range(8)))]
    snapshot, card = backend._find(split.id)
    snapshot.replace_card(replace(card, checklist=(0, 8)))
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        await follow.follow(app, split.comment_url(comments[-1].id))
        await settle(pilot, 8)
        backend.release.set()
        await settle(pilot, 12)
        assert comment_in_view(app, comments[-1].id)
        assert first.id != comments[-1].id


async def test_redraw_mid_load_keeps_the_scroll_waiting_for_the_sections() -> None:
    from tui_trello.ui import follow

    backend = SlowSections()
    split = card_named(backend, "Split backend from UI")
    comments = await backend.comments(split.id)
    backend._attachments[split.id] = [await backend.attach_link(split.id, f"https://example.com/{n}")
                                      for n in range(6)]
    backend._checklists[split.id] = [Checklist("cl1", "Things", tuple(CheckItem(f"ci{n}", f"item {n}", False, n)
                                                                       for n in range(8)))]
    snapshot, card = backend._find(split.id)
    snapshot.replace_card(replace(card, checklist=(0, 8)))
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        await follow.follow(app, split.comment_url(comments[-1].id))
        await settle(pilot, 8)
        view = app.screen.query_one(CardView)
        assert view.sections_loading == {"attachments", "checklists"}
        app.store.board_changed.publish(app.store.snapshot)  # the same card is drawn again, its loads restarted
        await settle(pilot, 8)
        assert view.sections_loading == {"attachments", "checklists"}
        assert view.scroll_pending
        assert not comment_in_view(app, comments[-1].id)
        backend.release.set()
        await settle(pilot, 12)
        assert not view.sections_loading
        assert comment_in_view(app, comments[-1].id)


async def test_redraw_of_the_same_card_keeps_comments_and_scroll(app, backend) -> None:
    async with app.run_test(size=(120, 14)) as pilot:
        await pilot.pause()
        split = card_named(backend, "Split backend from UI")
        app.open_card(split.id)
        await settle(pilot, 8)
        view = app.screen.query_one(CardView)
        view.scroll_to(y=view.max_scroll_y, animate=False)
        await settle(pilot)
        before, children = view.scroll_y, list(app.screen.query_one("#card-comments").children)
        assert before > 0 and children
        app.store.board_changed.publish(app.store.snapshot)
        await settle(pilot, 8)
        assert view.scroll_y == before
        assert list(app.screen.query_one("#card-comments").children) == children


async def test_switching_card_shows_only_the_new_cards_comments(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        split = card_named(backend, "Split backend from UI")
        other = card_named(backend, "Move cards between lists")
        app.open_card(split.id)
        await settle(pilot, 8)
        assert app.screen.query_one("#card-comments").children
        await app.store.comments(other.id)  # cached, as after browsing
        view = app.screen.query_one(CardView)
        view.show(app.store.find_card(other.id), app.store.context_for(other.id))
        await settle(pilot, 8)
        shown = {w.id for w in app.screen.query_one("#card-comments").children}
        assert not shown & {f"comment-{c.id}" for c in await backend.comments(split.id)}
        assert shown == {f"comment-{c.id}" for c in await backend.comments(other.id)}


async def test_failing_section_load_releases_the_scroll(app, backend, monkeypatch) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        split = card_named(backend, "Split backend from UI")
        app.store.snapshot.replace_card(replace(app.store.find_card(split.id), attachment_count=1))

        async def boom(card_id):
            raise BackendError("boom")

        monkeypatch.setattr(app.store, "attachments", boom)
        app.open_card(split.id)
        await settle(pilot, 8)
        view = app.screen.query_one(CardView)
        assert "attachments" not in view.sections_loading
        assert app.screen.query_one("#card-attachments").has_class("visible")  # the error is shown


async def test_double_follow_pushes_one_picker(app, backend, tmp_path, monkeypatch) -> None:
    import asyncio

    (tmp_path / "notes.txt").write_text("remember")
    notes = await backend.attach_file(card_named(backend, "Move cards between lists").id, tmp_path / "notes.txt")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        attachments = app.store.attachments

        async def slow(card_id):
            await asyncio.sleep(0.2)  # the first follow is still going when the second comes
            return await attachments(card_id)

        monkeypatch.setattr(app.store, "attachments", slow)
        app.action_follow_link(notes.url)
        app.action_follow_link(notes.url)
        await asyncio.sleep(0.5)
        await settle(pilot, 8)
        assert [s for s in app.screen_stack if isinstance(s, AttachmentPickerScreen)] == [app.screen]


async def test_follow_of_another_link_while_one_is_open_says_so(app, backend, tmp_path, monkeypatch) -> None:
    import asyncio

    (tmp_path / "notes.txt").write_text("remember")
    notes = await backend.attach_file(card_named(backend, "Move cards between lists").id, tmp_path / "notes.txt")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        attachments = app.store.attachments

        async def slow(card_id):
            await asyncio.sleep(0.2)
            return await attachments(card_id)

        monkeypatch.setattr(app.store, "attachments", slow)
        app.action_follow_link(notes.url)
        app.action_follow_link(notes.url)  # the same link: dropped without a word
        await pilot.pause()
        assert not app._notifications
        app.action_follow_link("https://example.com/other")
        await pilot.pause()
        assert [n.message for n in app._notifications] == ["Already opening a link"]
        await asyncio.sleep(0.5)
        await settle(pilot, 8)
        assert not app.following


async def test_reaction_keeps_the_scroll_position(app, backend) -> None:
    async with app.run_test(size=(120, 14)) as pilot:
        await pilot.pause()
        split = card_named(backend, "Split backend from UI")
        app.open_card(split.id)
        await settle(pilot, 8)
        view = app.screen.query_one(CardView)
        view.scroll_to(y=view.max_scroll_y, animate=False)
        await settle(pilot)
        assert view.scroll_y > 0
        before, children = view.scroll_y, list(app.screen.query_one("#card-comments").children)
        comment = next(c for c in await app.store.comments(split.id) if c.text == "Looks good to me.")
        await app.store.toggle_reaction(split.id, comment, "rocket", "🚀")
        await settle(pilot, 8)
        assert view.scroll_y == before
        assert list(app.screen.query_one("#card-comments").children) == children  # updated in place
        assert "🚀 you" in "\n".join(screen_lines(app))


# -- opening a link at start-up (--open) --------------------------------------------------------------------------


class RecordingBackend(DemoBackend):
    def __init__(self) -> None:
        super().__init__()
        self.loaded: list[str] = []

    async def board_snapshot(self, board_id: str):
        self.loaded.append(board_id)
        return await super().board_snapshot(board_id)


def opening(url: str) -> tuple[TrelloApp, RecordingBackend]:
    backend = RecordingBackend()
    return TrelloApp(backend, Settings(default_board="b-product"), open_url=url), backend


async def test_open_card_link_at_start(backend) -> None:
    arabic = card_named(backend, "إصلاح خطأ في نموذج التسجيل (عاجل)")
    app, recording = opening(arabic.url)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == arabic.id
        assert app.store.snapshot.board.id == "b-arabic"
        assert "b-product" not in recording.loaded
        await pilot.press("escape")
        assert isinstance(app.screen, BrowserScreen) and app.current_mode == "browser"


async def test_open_comment_link_at_start(backend) -> None:
    split = card_named(backend, "Split backend from UI")
    grace = next(c for c in await backend.comments(split.id) if c.author == "Grace Hopper")
    app, _ = opening(split.comment_url(grace.id))
    async with app.run_test(size=(120, 24)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == split.id
        assert comment_in_view(app, grace.id)


async def test_open_board_link_at_start() -> None:
    app, recording = opening("https://trello.example/b/b-home/home")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, BrowserScreen) and not card_screens(app)
        assert app.store.snapshot.board.id == "b-home"
        assert "b-product" not in recording.loaded


async def test_open_attachment_link_at_start(backend, tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("remember")
    moving = card_named(backend, "Move cards between lists")
    notes = await backend.attach_file(moving.id, tmp_path / "notes.txt")
    app = TrelloApp(backend, Settings(default_board="b-product"), open_url=notes.url)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, AttachmentPickerScreen) and app.screen.highlighted().id == notes.id
        assert app.store.snapshot.board.id == "b-product"
        assert not app.following


async def test_open_unknown_card_falls_back_to_the_default_board() -> None:
    app, _ = opening("https://trello.example/c/nope")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        [toast] = app._notifications
        assert toast.severity == "error" and "No card nope" in toast.message
        assert isinstance(app.screen, BrowserScreen) and app.store.snapshot.board.id == "b-product"


async def test_open_unknown_board_link_falls_back_to_the_default_board() -> None:
    app, _ = opening("https://trello.example/b/zzzz/x")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        [toast] = app._notifications
        assert toast.severity == "error"
        assert isinstance(app.screen, BrowserScreen) and app.store.snapshot.board.id == "b-product"


async def test_open_unknown_board_link_without_a_default_board_picks_a_board() -> None:
    app = TrelloApp(RecordingBackend(), Settings(default_board=""), open_url="https://trello.example/b/zzzz/x")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert len(app._notifications) == 1
        assert isinstance(app.screen, PickerScreen) and app.store.snapshot is None


async def test_open_board_link_switches_from_my_work_to_the_browser() -> None:
    app = TrelloApp(RecordingBackend(), Settings(default_board="b-product", layout="mywork"),
                    open_url="https://trello.example/b/b-home/home")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert app.current_mode == "browser" and isinstance(app.screen, BrowserScreen)
        assert app.store.snapshot.board.id == "b-home"


async def test_open_attachment_link_without_a_default_board_keeps_its_picker(backend, tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("remember")
    moving = card_named(backend, "Move cards between lists")
    notes = await backend.attach_file(moving.id, tmp_path / "notes.txt")
    app = TrelloApp(backend, Settings(default_board=""), open_url=notes.url)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, AttachmentPickerScreen) and app.screen.highlighted().id == notes.id
        assert [s for s in app.screen_stack if isinstance(s, PickerScreen)] == [app.screen]


async def test_picking_a_board_during_an_open_board_link_load_wins() -> None:
    class SlowHome(RecordingBackend):
        async def board_snapshot(self, board_id: str):
            if board_id == "b-home":
                await asyncio.sleep(0.5)
            return await super().board_snapshot(board_id)

    app = TrelloApp(SlowHome(), Settings(default_board="b-product"), open_url="https://trello.example/b/b-home/home")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 3)
        app.open_board("b-arabic")
        await asyncio.sleep(0.8)
        await settle(pilot, 5)
        assert app.store.snapshot.board.id == "b-arabic"
        assert app._exception is None and not app.following


async def test_help_during_a_failing_open_card_fetch_still_shows_the_board_picker() -> None:
    class SlowFailure(RecordingBackend):
        async def card(self, card_id: str):
            await asyncio.sleep(0.6)
            return await super().card(card_id)

    app = TrelloApp(SlowFailure(), Settings(default_board=""), open_url="https://trello.example/c/nope")
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 3)
        await pilot.press("question_mark")
        await asyncio.sleep(1)
        await settle(pilot, 5)
        assert any(isinstance(s, PickerScreen) for s in app.screen_stack)


async def test_closing_an_open_attachment_picker_without_a_default_board_shows_the_board_picker(
    backend, tmp_path
) -> None:
    (tmp_path / "notes.txt").write_text("remember")
    moving = card_named(backend, "Move cards between lists")
    notes = await backend.attach_file(moving.id, tmp_path / "notes.txt")
    app = TrelloApp(backend, Settings(default_board=""), open_url=notes.url)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot, 8)
        assert isinstance(app.screen, AttachmentPickerScreen)
        await pilot.press("escape")
        await asyncio.sleep(0.4)
        await settle(pilot, 5)
        assert isinstance(app.screen, PickerScreen) and not isinstance(app.screen, AttachmentPickerScreen)


# -- link previews ------------------------------------------------------------------------------------------------


def preview_screens(app) -> list[LinkPreviewScreen]:
    return [s for s in app.screen_stack if isinstance(s, LinkPreviewScreen)]


def preview_text(app) -> str:
    return "\n".join(screen_lines(app))


async def test_preview_card_link_from_picker(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"move", "alt+p")
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen)
        text = preview_text(app)
        assert "Move cards between lists" in text and "Product roadmap › Doing" in text
        assert "card · description" in text  # where the link was found
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(app.screen, LinkPickerScreen)
        assert app.screen.query_one("Input").value == "move"
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(app.screen, BrowserScreen)
        assert app.screen.current_card().name == "Offline cache for boards"


async def test_preview_keeps_the_board(app, backend) -> None:
    arabic = card_named(backend, "إصلاح خطأ في نموذج التسجيل (عاجل)")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(arabic.url)
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen)
        assert "(لجاع)" in preview_text(app)  # drawn right to left
        assert app.store.snapshot.board.id == "b-product"
        await pilot.press("escape")
        await settle(pilot)
        assert app.store.snapshot.board.id == "b-product" and isinstance(app.screen, BrowserScreen)
        assert not app.store.busy


async def test_preview_comment_link(app, backend) -> None:
    split = card_named(backend, "Split backend from UI")
    grace = next(c for c in await backend.comments(split.id) if c.author == "Grace Hopper")
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app.action_open_link(split.comment_url(grace.id))
        await settle(pilot, 10)
        assert isinstance(app.screen, LinkPreviewScreen)
        view = app.screen.query_one(CardView)
        widget = view.query_one(f"#comment-{grace.id}")
        assert widget.has_class("target") and view.region.contains_region(widget.region)
        assert not card_screens(app)


async def test_preview_missing_comment(app, backend) -> None:
    split = card_named(backend, "Split backend from UI")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(split.comment_url("made-up"))
        await settle(pilot, 10)
        assert "Split backend from UI" in preview_text(app)
        assert "ctrl+o opens it on trello.com" in str(app.screen.query_one("#preview-note").content)
        assert not app.screen.query(".comment.target")


async def test_preview_attachment_link(app, backend, tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("remember")
    moving = card_named(backend, "Move cards between lists")
    notes = await backend.attach_file(moving.id, tmp_path / "notes.txt")
    sketch = (await backend.attachments(moving.id))[0]
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(sketch.url)
        await settle(pilot, 8)
        text = preview_text(app)
        assert "picker-sketch.png" in text and "On card" in text and "Move cards between lists" in text
        assert "Product roadmap › Doing" in text and "image/png" in text
        await pilot.press("escape")
        app.action_open_link(notes.url.replace(notes.id, "gone"))
        await settle(pilot, 8)
        assert "That attachment is no longer on its card" in preview_text(app)


async def test_board_and_web_links_have_no_preview(app, backend, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"textual", "alt+p")
        await settle(pilot)
        assert opened == ["https://textual.textualize.io/"] and not preview_screens(app)
        assert isinstance(app.screen, BrowserScreen)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"home", "alt+p")
        await settle(pilot, 8)
        assert app.store.snapshot.board.id == "b-home" and not preview_screens(app)
        app.action_open_link("https://example.com/")
        await settle(pilot)
        assert opened[-1] == "https://example.com/" and not preview_screens(app)


async def test_preview_enter_follows(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"move", "alt+p")
        await settle(pilot, 8)
        await pilot.press("enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and app.screen.card_id == card_named(app.store.backend,
                                                                                    "Move cards between lists").id
        assert not preview_screens(app) and not [s for s in app.screen_stack if isinstance(s, LinkPickerScreen)]


async def test_preview_ctrl_o(app, backend, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"move", "alt+p")
        await settle(pilot, 8)
        await pilot.press("ctrl+o")
        await settle(pilot)
        assert opened == [card_named(backend, "Move cards between lists").url]
        assert isinstance(app.screen, BrowserScreen) and not preview_screens(app)


async def test_preview_copies_the_link(app, backend, monkeypatch) -> None:
    monkeypatch.setattr(clipboard, "command", lambda: None)
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        await pilot.press("ctrl+y")
        assert app.clipboard == moving.url and isinstance(app.screen, LinkPreviewScreen)


async def test_preview_error_in_popup(app, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link("https://trello.example/c/nope")
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen) and "No card nope" in preview_text(app)
        assert not app._notifications
        await pilot.press("ctrl+o")
        await settle(pilot)
        assert opened == ["https://trello.example/c/nope"] and not preview_screens(app)


class ArchivedCards(DemoBackend):
    async def card_preview(self, card_id: str):
        return replace(await super().card_preview(card_id), archived="list")


async def test_preview_says_what_is_archived() -> None:
    backend = ArchivedCards()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    arabic = card_named(backend, "إصلاح خطأ في نموذج التسجيل (عاجل)")  # on a board that isn't loaded
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(arabic.url)
        await settle(pilot, 8)
        assert "In an archived list" in preview_text(app)


async def test_click_on_a_card_link_previews_it(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        lines = screen_lines(app)
        y = next(i for i, line in enumerate(lines) if "the card Move cards" in line)
        await pilot.click(offset=(lines[y].index("Move cards") + 1, y))
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen) and not card_screens(app)
        assert app.store.snapshot.board.id == "b-product"
        await pilot.press("enter")
        await settle(pilot, 8)
        assert isinstance(app.screen, CardScreen) and not preview_screens(app)


async def test_preview_leaves_scroll_and_focus(app, backend) -> None:
    split = card_named(backend, "Split backend from UI")
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 14)) as pilot:
        await pilot.pause()
        app.open_card(split.id)
        await settle(pilot, 8)
        view = app.screen.query_one(CardView)
        view.scroll_to(y=view.max_scroll_y, animate=False)
        await settle(pilot)
        before, focused, stack = view.scroll_y, app.focused, list(app.screen_stack)
        assert before > 0
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen)
        await pilot.press("escape")
        await settle(pilot)
        assert view.scroll_y == before and app.focused is focused and app.screen_stack == stack


async def test_preview_close_cancels_loading(backend) -> None:
    gate = asyncio.Event()

    class Waiting(DemoBackend):
        async def card_preview(self, card_id: str):
            await gate.wait()
            return await super().card_preview(card_id)

    waiting = Waiting()
    app = TrelloApp(waiting, Settings(default_board="b-product"))
    moving = card_named(waiting, "Move cards between lists")
    other = card_named(waiting, "Split backend from UI")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.store.snapshot.cards = [c for c in app.store.snapshot.cards if c.id != moving.id]  # not loaded
        app.action_open_link(moving.url)
        await settle(pilot, 4)
        assert "Loading…" in preview_text(app) and app.store.is_busy("preview")
        await pilot.press("escape")
        await settle(pilot, 4)
        assert not app.store.busy and not app._notifications and isinstance(app.screen, BrowserScreen)
        gate.set()
        await settle(pilot)
        assert other  # the demo is untouched


async def test_mode_keys_disabled_in_preview(app, backend) -> None:
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        await pilot.press("2", "b", "r", "g", "t")
        await settle(pilot)
        assert isinstance(app.screen, LinkPreviewScreen) and app.current_mode == "browser"
        assert len(app.screen_stack) == 2  # the browser and the popup
        await pilot.press("escape")
        assert isinstance(app.screen, BrowserScreen)


async def test_click_inside_preview_previews(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("enter")  # the card screen of the links card
        await settle(pilot, 8)
        app.action_open_link(card_named(backend, "Offline cache for boards").url)
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1
        lines = screen_lines(app)
        y = next(i for i, line in enumerate(lines) if "the card Move cards" in line)
        await pilot.click(offset=(lines[y].index("Move cards") + 1, y))
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 2
        assert "Product roadmap › Doing" in preview_text(app)
        await pilot.press("escape")
        await settle(pilot)
        assert len(preview_screens(app)) == 1 and "Offline cache for boards" in preview_text(app)
        # Following from a second preview closes both.
        app.screen.open_link(card_named(backend, "Move cards between lists").url)
        await settle(pilot, 8)
        await pilot.press("enter")
        await settle(pilot, 8)
        assert not preview_screens(app) and app.screen.card_id == card_named(backend, "Move cards between lists").id


async def test_help_lists_preview(app) -> None:
    async with app.run_test(size=(120, 100)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert "preview" in preview_text(app)


async def test_preview_scrolls_with_vim_keys(app, backend) -> None:
    split = card_named(backend, "Split backend from UI")
    async with app.run_test(size=(120, 14)) as pilot:
        await pilot.pause()
        app.action_open_link(split.url)
        await settle(pilot, 10)
        view = app.screen.query_one(CardView)
        assert view.max_scroll_y > 0 and view.scroll_y == 0
        await pilot.press("j", "j")
        await settle(pilot)
        assert view.scroll_y > 0
        await pilot.press("k", "k")
        await settle(pilot)
        assert view.scroll_y == 0
        await pilot.press("G")
        await settle(pilot, 8)
        assert view.scroll_y == view.max_scroll_y
        await pilot.press("g", "g")
        await settle(pilot, 8)
        assert view.scroll_y == 0
        await pilot.press("ctrl+d")
        await settle(pilot, 8)
        assert view.scroll_y > 0
        await pilot.press("ctrl+u")
        await settle(pilot, 8)
        assert view.scroll_y == 0
        assert isinstance(app.screen, LinkPreviewScreen)


async def test_help_lists_picker_keys_in_views_but_not_in_a_preview(app, backend) -> None:
    async with app.run_test(size=(120, 100)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await settle(pilot)
        assert "ctrl+j ctrl+k" in preview_text(app)
        await pilot.press("escape")
        await settle(pilot)
        app.action_open_link(card_named(backend, "Move cards between lists").url)
        await settle(pilot, 8)
        app.action_toggle_help()
        await settle(pilot)
        assert "Keys in a link preview" in preview_text(app) and "ctrl+j ctrl+k" not in preview_text(app)


async def test_click_preview_returns_focus(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        lines = screen_lines(app)
        before = app.focused
        y = next(i for i, line in enumerate(lines) if "the card Move cards" in line)
        await pilot.click(offset=(lines[y].index("Move cards") + 1, y))
        await settle(pilot, 8)
        assert isinstance(app.screen, LinkPreviewScreen)
        await pilot.press("escape")
        await settle(pilot)
        assert app.focused is before


async def test_help_in_a_preview_shows_the_preview_keys(app, backend) -> None:
    async with app.run_test(size=(120, 100)) as pilot:
        await pilot.pause()
        app.action_open_link(card_named(backend, "Move cards between lists").url)
        await settle(pilot, 8)
        app.action_toggle_help()
        await settle(pilot)
        text = preview_text(app)
        assert "Keys in a link preview" in text and "follow the link" in text
        assert "command palette" not in text and "new card" not in text


async def test_double_click_pushes_one_preview(app, backend) -> None:
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(moving.url)
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1
        app.action_open_link(moving.url)  # the same link inside its own preview is no further preview either
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1
        await pilot.press("escape")
        await settle(pilot)
        assert not preview_screens(app)
        app.action_open_link(moving.url)  # once closed it opens again
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1


async def test_double_click_in_a_preview_pushes_one_more(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(card_named(backend, "Offline cache for boards").url)
        await settle(pilot, 8)
        further = card_named(backend, "Move cards between lists").url
        app.action_open_link(further)
        app.action_open_link(further)
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 2


async def test_picker_preview_key_twice_pushes_one_preview(app) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await on_links_card(app, pilot)
        await pilot.press("L")
        await settle(pilot)
        await pilot.press(*"move")
        picker = app.screen
        picker.action_preview()
        picker.action_preview()
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1


async def test_command_palette_disabled_in_preview(app, backend) -> None:
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        await pilot.press("ctrl+p")
        await app.run_action("command_palette")  # `:`, were the popup not modal to keys
        await settle(pilot)
        assert [type(s).__name__ for s in app.screen_stack] == ["BrowserScreen", "LinkPreviewScreen"]
        # Still blocked under the key reference opened over the preview.
        app.action_toggle_help()
        await settle(pilot)
        assert [type(s).__name__ for s in app.screen_stack][-2:] == ["LinkPreviewScreen", "KeysScreen"]
        await pilot.press("ctrl+p")
        await app.run_action("command_palette")
        await app.run_action("refresh")
        await app.run_action("switch_mode('triage')")
        await settle(pilot)
        assert [type(s).__name__ for s in app.screen_stack][-2:] == ["LinkPreviewScreen", "KeysScreen"]
        assert app.current_mode == "browser"


async def test_preview_shows_only_keys_it_has(app, backend) -> None:
    palette = card_named(backend, "Command palette: jump to any card")  # a ticked checklist item
    moving = card_named(backend, "Move cards between lists")  # attachments
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        for card in (palette, moving):
            app.store.drafts.set("comment", card.id, "half a thought")
            app.store.drafts.set("desc", card.id, "half a description")
        app.action_open_link(palette.url)
        await settle(pilot, 8)
        text = preview_text(app)
        assert "☑" in text and "X: show done items" in text  # X works in the popup
        assert "x: tick" not in text
        assert "✐ draft  unsent comment" in text and "c: unsent" not in text  # the marker stays, the key goes
        await pilot.press("escape")
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        text = preview_text(app)
        assert "picker-sketch.png" in text and "a: open, save or add" not in text


async def test_question_mark_in_a_preview_opens_its_help(app, backend) -> None:
    async with app.run_test(size=(120, 100)) as pilot:
        await pilot.pause()
        app.action_open_link(card_named(backend, "Move cards between lists").url)
        await settle(pilot, 8)
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, KeysScreen)
        text = preview_text(app)
        assert "Keys in a link preview" in text and "follow the link" in text
        assert "ticked" in text  # X
        assert "quit" not in text and "filter" not in text and "command palette" not in text
        await pilot.press("question_mark")
        await settle(pilot)
        assert isinstance(app.screen, LinkPreviewScreen)


async def test_x_in_a_preview_toggles_done_items(app, backend) -> None:
    palette = card_named(backend, "Command palette: jump to any card")
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.action_open_link(palette.url)
        await settle(pilot, 8)
        assert "X: show done items" in preview_text(app)
        await pilot.press("X")
        await settle(pilot)
        assert "X: hide done items" in preview_text(app)


async def test_two_different_links_quickly_give_one_preview(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(card_named(backend, "Move cards between lists").url)
        app.action_open_link(card_named(backend, "Offline cache for boards").url)
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1
        assert "Move cards between lists" in preview_text(app)
        app.action_open_link(card_named(backend, "Offline cache for boards").url)  # inside it: a nested one
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 2


async def test_two_forms_of_one_link_give_one_preview(app, backend) -> None:
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        app.action_open_link(moving.url + "/extra-slug")  # nested, but the same card
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 1


async def test_follow_from_a_nested_preview_closes_the_stack(app, backend) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.action_open_link(card_named(backend, "Offline cache for boards").url)
        await settle(pilot, 8)
        app.action_open_link(card_named(backend, "Move cards between lists").url)
        await settle(pilot, 8)
        assert len(preview_screens(app)) == 2
        await pilot.press("enter")
        await settle(pilot, 12)
        assert not preview_screens(app)
        assert isinstance(app.screen, CardScreen)
        await pilot.press("escape")
        await settle(pilot)
        await pilot.press("2")
        await settle(pilot)
        assert app.current_mode == "triage"
        await pilot.press("4")
        await settle(pilot)
        assert app.current_mode == "notifications"
        await pilot.press("colon")
        await settle(pilot)
        assert type(app.screen).__name__ != "NotificationsScreen"


async def test_preview_shows_the_draft_marker_without_keys(app, backend) -> None:
    moving = card_named(backend, "Move cards between lists")
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        app.store.drafts.set("comment", moving.id, "half a thought")
        app.action_open_link(moving.url)
        await settle(pilot, 8)
        text = preview_text(app)
        assert "draft" in text and "unsent comment" in text and "c: unsent" not in text
