"""Notifications: Trello's bell, newest first. Enter opens the card and marks its notifications read; d marks one,
D marks them all."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from tui_trello.backend import BackendError
from tui_trello.models import Notification
from tui_trello.ui import render
from tui_trello.ui.bidi import fit
from tui_trello.ui.screens.base import TopBar
from tui_trello.ui.widgets.spinner import Spinner

AGO_WIDTH = 4
MARK = 2  # the unread dot and a space


class NotificationsScreen(Screen):
    AUTO_FOCUS = "#notifications"

    DEFAULT_CSS = """
    NotificationsScreen #notifications, NotificationsScreen #notifications:focus {
        height: 1fr; border: none; padding: 0 1; background: $surface;
    }
    NotificationsScreen #notifications:focus > .option-list--option-highlighted { background: $accent 40%; }
    """

    BINDINGS = [
        Binding("l,right", "open", "Open", show=False),
        Binding("d", "mark_read", "Mark read"),
        Binding("D", "mark_all_read", "Mark all read"),
        Binding("u", "toggle_unread", "Unread only"),
    ]

    def __init__(self, now: datetime | None = None) -> None:
        super().__init__()
        self.now = now  # fixed in tests and screenshots; the real clock otherwise
        self.unread_only = False
        self.shown: list[Notification] = []

    def compose(self) -> ComposeResult:
        with TopBar():
            yield Static(id="status")
            yield Spinner()
        yield OptionList(id="notifications")
        yield Footer()

    def on_mount(self) -> None:
        self.app.store.notifications_changed.subscribe(self, lambda _: self.redraw())
        if self.app.store.notifications is None:
            self.query_one("#status", Static).update(Text("Notifications", style="bold"))
            self.app.check_notifications(quiet=False)  # the start-up check failed: say why
        else:
            self.redraw()

    # -- drawing --------------------------------------------------------------------------------------------------

    def redraw(self) -> None:
        store = self.app.store
        if store.notifications is None:
            return
        now = self.now or datetime.now(timezone.utc)
        current = self.current()
        self.shown = [n for n in store.notifications if n.unread or not self.unread_only]
        options = self.query_one("#notifications", OptionList)
        width = options.scrollable_content_region.width
        options.set_options([Option(self.row(n, now, width), id=n.id) for n in self.shown] or [
            Option(Text("Nothing unread" if self.unread_only else "No notifications", style="dim"), disabled=True)])
        ids = [n.id for n in self.shown]
        if current and current.id in ids:
            options.highlighted = ids.index(current.id)
        elif ids:
            options.highlighted = 0

        status = Text.assemble(
            ("Notifications", "bold"), f"  {store.unread_count} unread",
            ("   unread only", "yellow") if self.unread_only else "",
        )
        self.query_one("#status", Static).update(status)

    @staticmethod
    def row(n: Notification, now: datetime, width: int) -> Text:
        """Two lines: what happened and when; then the board and the comment, if there is one. The first is an
        English sentence with names in it, so it reads left to right even when it starts with an Arabic name."""
        summary_width = max(12, width - MARK - AGO_WIDTH - 1)
        first = Text.assemble(("● " if n.unread else "  ", "bold yellow"),
                              fit(Text(render.notification_summary(n), style="bold" if n.unread else ""),
                                  summary_width, rtl=False),
                              " ", (render.ago(n.date, now).rjust(AGO_WIDTH), "dim"))
        detail = Text(n.board_name, style="dim")
        if n.text:
            detail.append(" · ", style="dim")
            detail.append(" ".join(n.text.split()), style="italic")
        second = Text.assemble("  ", fit(detail, width - MARK))
        row = Text("\n").join([first, second])
        row.no_wrap, row.overflow = True, "ellipsis"
        return row

    def on_resize(self) -> None:
        self.redraw()

    # -- events and actions ---------------------------------------------------------------------------------------

    def current(self) -> Notification | None:
        if not self.is_mounted:
            return None
        option = self.query_one("#notifications", OptionList).highlighted_option
        return next((n for n in self.shown if option and n.id == option.id), None)

    @on(OptionList.OptionSelected, "#notifications")
    def on_selected(self) -> None:
        self.action_open()

    @work
    async def action_open(self) -> None:
        """Open the card (loading its board if no loaded snapshot has it), then mark its notifications read."""
        store = self.app.store
        if not (n := self.current()):
            return
        if not n.card_id:
            if n.board_id:
                await self.app.switch_mode("browser")
                self.app.open_board(n.board_id)
            await self.mark_read(n)
            return
        if not store.find_card(n.card_id):
            try:
                snapshot = await store.open_board(n.board_id)
            except BackendError as exc:
                self.notify(str(exc), title="Could not open board", severity="error")
                return
            self.app.sub_title = snapshot.board.name
        if not store.find_card(n.card_id):
            self.notify("That card has been archived or deleted.", severity="warning")
        else:
            self.app.open_card(n.card_id)
        try:
            await store.mark_card_read(n.card_id)
        except BackendError as exc:
            self.notify(str(exc), severity="error")

    async def mark_read(self, n: Notification) -> None:
        if not n.unread:
            return
        try:
            await self.app.store.mark_read(n)
        except BackendError as exc:
            self.notify(str(exc), severity="error")

    @work
    async def action_mark_read(self) -> None:
        if n := self.current():
            await self.mark_read(n)
            options = self.query_one("#notifications", OptionList)
            # Step on to the next one, as after archiving an e-mail; with unread only, the row went and the next
            # one is already there.
            if (not self.unread_only and options.highlighted is not None
                    and options.highlighted < options.option_count - 1):
                options.highlighted += 1

    @work
    async def action_mark_all_read(self) -> None:
        try:
            await self.app.store.mark_all_read()
        except BackendError as exc:
            self.notify(str(exc), severity="error")

    def action_toggle_unread(self) -> None:
        self.unread_only = not self.unread_only
        self.redraw()
