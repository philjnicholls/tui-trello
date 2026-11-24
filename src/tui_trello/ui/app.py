"""The application shell: owns the store, the modes (one per layout) and the app-wide vim keys.

To add a layout, write a screen (usually a :class:`~tui_trello.ui.screens.base.ListScreen` subclass), add it to
``MODES`` and to ``config.LAYOUTS``; it gets a number key from its position. To add a palette command, add a provider
to ``COMMANDS``.

Motions apply to whatever has focus, so every list, table and scrolling pane moves the same way:

    j / k       down / up             gg / G      top / bottom
    ctrl+d / u  half a page           h / l       out / in (per layout)
    gt / gT     next / previous layout
    /           search Trello         f           filter the cards on screen
    :           command palette       ?           keys
    X           show or hide done checklist items, in every card pane (remembered)

Every key has an id, and `[keys]` in config.toml changes it (see `tui_trello.ui.keymap`).

``open_url`` (``tui-trello --open URL``) is a Trello link followed at start-up in place of the default board.
"""

from __future__ import annotations

import asyncio
import time

from rich.text import Text
from textual import events, work
from textual.app import App
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.signal import Signal
from textual.widget import Widget
from textual.widgets import Input, TextArea

from tui_trello import links
from tui_trello.backend import Backend, BackendError
from tui_trello.config import Settings
from tui_trello.drafts import Drafts
from tui_trello.emoji import with_emoji
from tui_trello.models import Notification
from tui_trello.prefs import Prefs
from tui_trello.store import Store
from tui_trello.ui import desktop, follow, keymap, keys_compat, markdown, render
from tui_trello.ui.commands import BoardCommands, CardCommands
from tui_trello.ui.screens.browser import BrowserScreen
from tui_trello.ui.screens.card import CardScreen
from tui_trello.ui.screens.keys import KeysScreen
from tui_trello.ui.screens.mywork import MyWorkScreen
from tui_trello.ui.screens.notifications import NotificationsScreen
from tui_trello.ui.screens.picker import Choice, PickerScreen
from tui_trello.ui.screens.preview import LinkPreviewScreen, previewable
from tui_trello.ui.screens.search import SearchScreen
from tui_trello.ui.screens.triage import TriageScreen
from tui_trello.ui.widgets.card_view import CardView

keys_compat.install()

# Motion -> widget actions to try, in order; the first one the focused widget has is run.
MOTIONS = {
    "down": ("cursor_down", "scroll_down"),
    "up": ("cursor_up", "scroll_up"),
    "top": ("first", "scroll_top", "scroll_home"),
    "bottom": ("last", "scroll_bottom", "scroll_end"),
    "half_down": ("page_down",),
    "half_up": ("page_up",),
}

# Actions that change the screens under a link preview, so are off while one is up.
PREVIEW_BLOCKED = {"switch_mode", "cycle_mode", "pick_board", "refresh", "command_palette", "search"}


class TrelloApp(App):
    TITLE = "Trello"
    CLICK_SECONDS = 0.5  # the longest between a mouse press, which moves the focus, and its click

    # With `[ui] transparent` (the default) the app runs in Textual's ANSI mode, where the screen is drawn on the
    # terminal's own background, transparency included. Panels, table stripes and scrollbar tracks would still paint
    # over it with theme colours, so in that mode only the cursors and selections have a background.
    CSS = """
    App:ansi {
        Widget {
            background: transparent;
            scrollbar-background: ansi_default;
            scrollbar-background-hover: ansi_default;
            scrollbar-background-active: ansi_default;
            scrollbar-corner-color: ansi_default;
        }
        DataTable > .datatable--header, DataTable > .datatable--even-row, DataTable > .datatable--odd-row,
        TextArea > .text-area--cursor-line {
            background: transparent;
        }
        /* Textual's :ansi rule reverses the cursor and its :dark rule then gives it the theme's light-on-dark
           colours, so the reversed cursor came out dark on a dark terminal: invisible. Reverse the terminal's own
           colours instead: a block in its text colour, whatever its theme. */
        TextArea > .text-area--cursor, Input > .input--cursor {
            color: ansi_default;
            background: ansi_default;
            text-style: reverse;
        }
    }
    """

    MODES = {"browser": BrowserScreen, "triage": TriageScreen, "mywork": MyWorkScreen,
             "notifications": NotificationsScreen}
    COMMANDS = App.COMMANDS | {BoardCommands, CardCommands}

    BINDINGS = [
        Binding("1", "switch_mode('browser')", "Browser", id="app.browser"),
        Binding("2", "switch_mode('triage')", "Triage", id="app.triage"),
        Binding("3", "switch_mode('mywork')", "My work", id="app.mywork"),
        Binding("4", "switch_mode('notifications')", "Notifications", id="app.notifications"),
        Binding("b", "pick_board", "Boards", id="app.boards"),
        Binding("r", "refresh", "Refresh", id="app.refresh"),
        Binding("X", "toggle_done_check_items", "Done items", show=False, id="app.done_items"),
        Binding("j,down", "motion('down')", "Down", show=False, id="app.down"),
        Binding("k,up", "motion('up')", "Up", show=False, id="app.up"),
        Binding("G,end", "motion('bottom')", "Bottom", show=False, id="app.bottom"),
        Binding("home", "motion('top')", "Top", show=False, id="app.top"),
        Binding("ctrl+d,pagedown", "motion('half_down')", "Half page down", show=False, id="app.half_down"),
        Binding("ctrl+u,pageup", "motion('half_up')", "Half page up", show=False, id="app.half_up"),
        Binding("colon", "command_palette", "Commands", show=False, id="app.commands"),
        Binding("question_mark", "toggle_help", "Keys", id="app.help"),
        Binding("slash", "search", "Search", id="app.search"),
        Binding("q", "quit", "Quit", id="app.quit"),
    ]

    def __init__(self, backend: Backend, settings: Settings, drafts: Drafts | None = None,
                 prefs: Prefs | None = None, open_url: str = "") -> None:
        super().__init__(ansi_color=settings.transparent)
        self.settings = settings
        self.keymap = keymap.KeyMap.build(settings.keys)  # `[keys]`, checked; problems are in `keymap.warnings`
        self.set_keymap(self.keymap.textual)
        self.prefs = prefs or Prefs()
        # Carries the new "shown" value of `prefs.show_done_check_items`, for every CardView on every screen.
        self.done_check_items_toggled: Signal[bool] = Signal(self, "done_check_items_toggled")
        self.store = Store(self, backend, drafts)
        self.pending_chord = ""
        self.blurred: tuple[Widget, float] | None = None  # the widget that last lost the focus, and when
        self.following = ""  # the link being followed, if any
        self.open_url = open_url  # `--open`: a Trello link to follow at start-up, in place of the default board
        # The links whose preview is being pushed or is open, as (kind, short link, comment, card, attachment)
        self.previewing: set[tuple] = set()
        self.root_preview = False  # a preview not opened from inside another is being pushed or is open

    async def on_mount(self) -> None:
        await self.switch_mode(self.settings.layout)
        if problems := self.settings.warnings + self.keymap.warnings:
            more = [f"and {len(problems) - 5} more: run `tui-trello keys`"] if len(problems) > 5 else []
            shown = problems[:5] + more
            self.notify("\n".join(shown), title="Problems in config.toml", severity="warning", timeout=20,
                        markup=False)
        if self.open_url:
            self.open_link_at_start(self.open_url)
        else:
            self.open_start_board()
        self.check_notifications()
        if self.settings.notify_interval > 0:
            self.set_interval(self.settings.notify_interval, self.check_notifications)

    def open_start_board(self) -> None:
        if self.settings.default_board:
            self.open_board(self.settings.default_board)
        elif self.settings.layout in ("browser", "triage"):
            self.action_pick_board()

    @work
    async def open_link_at_start(self, url: str) -> None:
        """`--open`: follow the link as a click would; if that opened no board and no screen, start as usual."""
        outcome = await self.follow_one_at_a_time(url)
        if outcome == "nothing" and self.store.snapshot is None:
            self.open_start_board()
        elif outcome == "screen" and self.store.snapshot is None:  # an attachments picker, over no board
            if self.settings.default_board:
                self.open_board(self.settings.default_board)
            elif self.settings.layout in ("browser", "triage"):
                screen = self.screen
                while screen in self.screen_stack:
                    await asyncio.sleep(0.1)
                if self.store.snapshot is None:
                    self.action_pick_board()

    async def on_unmount(self) -> None:
        await self.store.backend.aclose()

    # -- vim keys -------------------------------------------------------------------------------------------------

    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, events.Key) and not isinstance(self.focused, (Input, TextArea)):
            key = event.character or event.key
            if self.pending_chord:
                chord, self.pending_chord = self.pending_chord + key, ""
                if action := self.keymap.chords.get(chord):
                    await self.run_action(action)
                return  # an unknown sequence is dropped, as in vim
            if key in self.keymap.chord_prefixes:
                self.pending_chord = key
                return
        await super().on_event(event)

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        self.blurred = (event.widget, time.monotonic())

    def clicked_from(self) -> Widget | None:
        """The widget the click that is being handled took the focus from: the one that lost it a moment ago."""
        if self.blurred and time.monotonic() - self.blurred[1] < self.CLICK_SECONDS:
            return self.blurred[0]
        return None

    def action_motion(self, motion: str) -> None:
        if (target := self.focused) is None:
            return
        for name in MOTIONS[motion]:
            if action := getattr(target, f"action_{name}", None):
                action()
                return

    async def action_cycle_mode(self, step: int) -> None:
        modes = list(self.MODES)
        await self.switch_mode(modes[(modes.index(self.current_mode) + step) % len(modes)])

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in PREVIEW_BLOCKED and any(isinstance(screen, LinkPreviewScreen) for screen in self.screen_stack):
            return False  # they'd change what is under the popup, which closing it must leave as it was
        if action == "search" and isinstance(self.screen, ModalScreen):
            return False  # not over a popup: a picker, the key help, a confirmation
        if action == "toggle_done_check_items":
            return bool(self.screen.query(CardView))  # only where a card pane is
        return True

    @work
    async def action_search(self) -> None:
        """`/`: search every board on Trello, archived cards too; go to the card chosen."""
        if url := await self.push_screen_wait(SearchScreen()):
            self.action_follow_link(url)

    def action_toggle_done_check_items(self) -> None:
        """`X`: show or hide the ticked items of every checklist, in every card pane; remembered."""
        self.prefs.show_done_check_items = not self.prefs.show_done_check_items
        self.done_check_items_toggled.publish(self.prefs.show_done_check_items)

    def action_toggle_help(self) -> None:
        if not isinstance(self.screen, KeysScreen):
            self.push_screen(KeysScreen(getattr(self.screen, "HELP_PLACE", None)))

    # -- boards ---------------------------------------------------------------------------------------------------

    @work(exclusive=True, group="board")
    async def open_board(self, board_id: str) -> None:
        self.sub_title = "loading…"
        try:
            snapshot = await self.store.open_board(board_id)
        except BackendError as exc:
            self.sub_title = ""
            self.notify(str(exc), title="Could not open board", severity="error", timeout=10)
        else:
            self.sub_title = with_emoji(snapshot.board.name)

    # -- notifications --------------------------------------------------------------------------------------------

    @work(exclusive=True, group="notifications")
    async def check_notifications(self, quiet: bool = True) -> None:
        """Fetch the notifications and announce new unread ones. A failed background check is retried at the next
        interval without a word (the network may be down); `quiet=False` reports it."""
        try:
            new = await self.store.load_notifications()
        except BackendError as exc:
            if not quiet:
                self.notify(str(exc), title="Could not check notifications", severity="error")
            return
        self.announce(new)

    def announce(self, new: list[Notification]) -> None:
        """A toast for each new notification (one for the lot if there are many), and a desktop notification."""
        if not new:
            return
        if len(new) > 3:
            title = "Trello"
            body = f"{len(new)} new notifications " + self.keymap.fill("({app.notifications} to see them)")
            self.notify(body, title=title)
        else:
            for notification in reversed(new):  # oldest first, so the newest toast is at the bottom
                self.notify(markdown.plain(notification.text),
                            title=render.notification_summary(notification), timeout=8,
                            markup=False)  # comments are other people's text
            title, body = render.notification_summary(new[0]), markdown.plain(new[0].text)
            if len(new) > 1:
                body = f"and {len(new) - 1} more"
        if self.settings.desktop_notifications and not self.is_headless and self._driver is not None:
            desktop.alert(title, body, self._driver.write)  # App.bell() writes to the driver the same way

    def open_card(self, card_id: str, comment_id: str = "") -> None:
        self.push_screen(CardScreen(card_id, comment_id))

    def action_open_link(self, url: str) -> None:
        """A click on a link or image in a card's text: a card, comment or attachment link opens its preview; a
        board or web link is followed. Inside a preview, the preview deals with it."""
        if isinstance(self.screen, LinkPreviewScreen):
            self.screen.open_link(url)
        else:
            self.open_link(url, self.clicked_from())

    async def preview_link(self, url: str, where: str = "", nested: bool = False) -> str | None:
        """Push the popup for `url` and wait for it: the URL to follow, "" if it went to the web browser, None if it
        was closed. Dropped (None): the same link again while its preview is being pushed or is open, such as a double
        click (whatever the form of its URL), and a second preview from outside a preview while one is being pushed or
        is open. A preview from inside a preview (`nested`) is allowed."""
        link = links.parse(url, self.store.link_hosts)
        key = (link.kind, link.short_link, link.comment_id, link.card_id, link.attachment_id)
        if key in self.previewing or (self.root_preview and not nested):
            return None
        self.previewing.add(key)
        self.root_preview = self.root_preview or not nested
        try:
            return await self.push_screen_wait(LinkPreviewScreen(url, where))
        finally:
            self.previewing.discard(key)
            if not nested:
                self.root_preview = False

    @work
    async def open_link(self, url: str, refocus: Widget | None = None) -> None:
        """`refocus` had the focus before the click that opened the link, which moved it: it gets it back when the
        preview is closed."""
        if previewable(url, self.store.link_hosts):
            if (result := await self.preview_link(url)):
                self.action_follow_link(result)
            elif refocus is not None and refocus.is_attached and refocus.screen is self.screen:
                self.screen.set_focus(refocus)
        else:
            self.action_follow_link(url)

    @work
    async def action_follow_link(self, url: str) -> None:
        """A click on a link or image in a card's text. One at a time: the same link again, such as a double click, is
        dropped; another is refused with a toast. Neither cancels the first half way through its navigation."""
        await self.follow_one_at_a_time(url)

    async def follow_one_at_a_time(self, url: str) -> str | None:
        """Follow the link, and say what came of it (`follow.follow`'s answer); None if another one is under way."""
        if self.following:
            if url != self.following:
                self.notify("Already opening a link", severity="warning")
            return None
        self.following = url
        try:
            return await follow.follow(self, url)
        finally:
            self.following = ""

    @work
    async def action_pick_board(self) -> None:
        async def choices() -> list[Choice[str]]:
            unread = self.store.unread_by_board()
            return [Choice(with_emoji(board.name), board.id, "★" if board.starred else "",
                           Text.assemble(render.unread_badge(unread[board.id]), " ") if unread[board.id] else None,
                           search=board.name)
                    for board in await self.store.boards()]

        # Opens straight away; typing while the boards load is kept.
        if board_id := await self.push_screen_wait(PickerScreen("Open board", choices)):
            if self.current_mode == "mywork":
                await self.switch_mode("browser")
            self.open_board(board_id)

    @work(exclusive=True, group="refresh")
    async def action_refresh(self) -> None:
        try:
            if self.store.snapshot:
                await self.store.open_board(self.store.snapshot.board.id)
            if self.store.work:
                await self.store.load_work()
        except BackendError as exc:
            self.notify(str(exc), title="Could not refresh", severity="error")
        self.check_notifications(quiet=False)
