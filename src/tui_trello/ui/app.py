"""The application shell: owns the store, the modes (one per layout) and the app-wide vim keys.

To add a layout, write a screen (usually a :class:`~tui_trello.ui.screens.base.ListScreen` subclass), add it to
``MODES`` and to ``config.LAYOUTS``; it gets a number key from its position. To add a palette command, add a provider
to ``COMMANDS``.

Motions apply to whatever has focus, so every list, table and scrolling pane moves the same way:

    j / k       down / up             gg / G      top / bottom
    ctrl+d / u  half a page           h / l       out / in (per layout)
    gt / gT     next / previous layout
    /           filter                :           command palette           ?   keys
"""

from __future__ import annotations

from textual import events, work
from textual.app import App
from textual.binding import Binding
from textual.widgets import Input, TextArea

from tui_trello.backend import Backend, BackendError
from tui_trello.config import Settings
from tui_trello.store import Store
from tui_trello.models import Notification
from tui_trello.ui import desktop, keys_compat, render
from tui_trello.ui.commands import BoardCommands, CardCommands
from tui_trello.ui.screens.browser import BrowserScreen
from tui_trello.ui.screens.card import CardScreen
from tui_trello.ui.screens.keys import KeysScreen
from tui_trello.ui.screens.mywork import MyWorkScreen
from tui_trello.ui.screens.notifications import NotificationsScreen
from tui_trello.ui.screens.picker import Choice, PickerScreen
from tui_trello.ui.screens.triage import TriageScreen

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

# Two-key sequences, vim style. The first key is swallowed until the second arrives.
CHORDS = {
    "gg": "motion('top')",
    "gt": "cycle_mode(1)",
    "gT": "cycle_mode(-1)",
}
CHORD_PREFIXES = {chord[0] for chord in CHORDS}


class TrelloApp(App):
    TITLE = "Trello"

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
        Binding("1", "switch_mode('browser')", "Browser"),
        Binding("2", "switch_mode('triage')", "Triage"),
        Binding("3", "switch_mode('mywork')", "My work"),
        Binding("4", "switch_mode('notifications')", "Notifications"),
        Binding("b", "pick_board", "Boards"),
        Binding("r", "refresh", "Refresh"),
        Binding("j,down", "motion('down')", "Down", show=False),
        Binding("k,up", "motion('up')", "Up", show=False),
        Binding("G,end", "motion('bottom')", "Bottom", show=False),
        Binding("home", "motion('top')", "Top", show=False),
        Binding("ctrl+d,pagedown", "motion('half_down')", "Half page down", show=False),
        Binding("ctrl+u,pageup", "motion('half_up')", "Half page up", show=False),
        Binding("colon", "command_palette", "Commands", show=False),
        Binding("question_mark", "toggle_help", "Keys"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, backend: Backend, settings: Settings) -> None:
        super().__init__(ansi_color=settings.transparent)
        self.settings = settings
        self.store = Store(self, backend)
        self.pending_chord = ""

    async def on_mount(self) -> None:
        await self.switch_mode(self.settings.layout)
        if self.settings.default_board:
            self.open_board(self.settings.default_board)
        elif self.settings.layout in ("browser", "triage"):
            self.action_pick_board()
        self.check_notifications()
        if self.settings.notify_interval > 0:
            self.set_interval(self.settings.notify_interval, self.check_notifications)

    async def on_unmount(self) -> None:
        await self.store.backend.aclose()

    # -- vim keys -------------------------------------------------------------------------------------------------

    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, events.Key) and not isinstance(self.focused, (Input, TextArea)):
            key = event.character or event.key
            if self.pending_chord:
                chord, self.pending_chord = self.pending_chord + key, ""
                if chord in CHORDS:
                    await self.run_action(CHORDS[chord])
                return  # an unknown sequence is dropped, as in vim
            if key in CHORD_PREFIXES:
                self.pending_chord = key
                return
        await super().on_event(event)

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

    def action_toggle_help(self) -> None:
        if not isinstance(self.screen, KeysScreen):
            self.push_screen(KeysScreen())

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
            self.sub_title = snapshot.board.name

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
            title, body = "Trello", f"{len(new)} new notifications (4 to see them)"
            self.notify(body, title=title)
        else:
            for notification in reversed(new):  # oldest first, so the newest toast is at the bottom
                self.notify(notification.text, title=render.notification_summary(notification), timeout=8,
                            markup=False)  # comments are other people's text
            title, body = render.notification_summary(new[0]), new[0].text
            if len(new) > 1:
                body = f"and {len(new) - 1} more"
        if self.settings.desktop_notifications and not self.is_headless and self._driver is not None:
            desktop.alert(title, body, self._driver.write)  # App.bell() writes to the driver the same way

    def open_card(self, card_id: str) -> None:
        self.push_screen(CardScreen(card_id))

    @work
    async def action_pick_board(self) -> None:
        async def choices() -> list[Choice[str]]:
            return [Choice(board.name, board.id, "★" if board.starred else "") for board in await self.store.boards()]

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
