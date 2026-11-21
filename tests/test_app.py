"""End-to-end flows driven through the keyboard, against the demo backend."""

import asyncio

import pytest
from textual.widgets import TextArea

from tui_trello import store as store_module
from tui_trello.backend import BackendError
from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.ui import clipboard, render
from tui_trello.ui.app import TrelloApp
from tui_trello.ui.screens.browser import BrowserScreen
from tui_trello.ui.screens.card import CardScreen
from tui_trello.ui.screens.mywork import MyWorkScreen
from tui_trello.ui.screens.notifications import NotificationsScreen
from tui_trello.ui.screens.picker import (
    AttachmentPickerScreen,
    ChecklistPickerScreen,
    FilePickerScreen,
    LabelPickerScreen,
    PickerScreen,
)
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
        assert "☐ Update the README.md" in "\n".join(screen_lines(app))
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
        assert "☐ Ship it" in "\n".join(screen_lines(app))


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
        assert any(snapshot.list_named(card.list_id) in line and "●" in line for line in lines)  # its list
        await pilot.press("b")
        await pilot.pause()
        assert "●3 Product roadmap" in "\n".join(screen_lines(app))  # the board picker
        await pilot.press("escape")
        await pilot.pause()
        assert "●2" in render.card_block(card, snapshot, unread=app.store.unread_by_card()[card.id]).text.plain
        await app.store.mark_card_read(card.id)
        await pilot.pause()
        assert app.store.unread_by_card()[card.id] == 0
        assert "●2" not in "\n".join(screen_lines(app))


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
