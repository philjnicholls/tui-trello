"""Triage table: every open card on the board as one sortable, filterable row."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Input, Static

from tui_trello.models import Card
from tui_trello.ui import render
from tui_trello.ui.bidi import BidiText, visual
from tui_trello.ui.screens.base import FILTER_HELP, BoardScreen, TopBar
from tui_trello.ui.widgets.bell import Bell
from tui_trello.ui.widgets.spinner import Spinner

FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)
FAR_PAST = datetime.min.replace(tzinfo=timezone.utc)

# name -> sort key; the first is the default
SORTS = {
    "list": lambda card, snapshot: ([lst.id for lst in snapshot.lists].index(card.list_id), card.pos),
    "due": lambda card, snapshot: (card.due_complete, card.due or FAR_FUTURE),
    "activity": lambda card, snapshot: -(card.last_activity or FAR_PAST).timestamp(),
}


class TriageScreen(BoardScreen):
    HELP_PLACE = "triage"  # which keys `?` shows
    AUTO_FOCUS = "DataTable"

    DEFAULT_CSS = """
    TriageScreen DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("s", "cycle_sort", "Sort"),
        Binding("l,right", "open", "Open", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.sort = next(iter(SORTS))
        self.rows: list[Card] = []

    def compose(self) -> ComposeResult:
        with TopBar():
            yield Static(id="status")
            yield Bell()
            yield Spinner()
        yield Input(id="filter", placeholder=FILTER_HELP)
        yield DataTable(id="body", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for label, width in [("List", 12), ("Card", None), ("Labels", 18), ("Due", 9), ("✎", 3), (render.BELL, 3),
                             ("Who", 8)]:
            table.add_column(label, width=width, key=label)

    def redraw(self) -> None:
        if not (snapshot := self.snapshot):
            return
        table = self.query_one(DataTable)
        current = self.current_card()
        self.rows = sorted(self.card_query.filter(snapshot),
                           key=lambda card: SORTS[self.sort](card, snapshot))
        table.clear()
        unread = self.app.store.unread_by_card()
        for card in self.rows:
            table.add_row(
                BidiText(Text(snapshot.list_named(card.list_id), style="bold"), wrap=False, align_rtl=False),
                BidiText(card.name, wrap=False, align_rtl=False),
                render.label_chips(card.labels),
                render.due_text(card),
                Text(str(card.comment_count or ""), style="dim"),
                Text(str(unread[card.id] or ""), style=f"bold {render.BELL_COLOUR}"),
                render.members_text(card, snapshot),
                key=card.id,
            )
        ids = [card.id for card in self.rows]
        if current and current.id in ids:
            table.move_cursor(row=ids.index(current.id))
        self.query_one("#status", Static).update(Text.assemble(
            visual(Text(snapshot.board.name, style="bold")), f"  {len(self.rows)}/{len(snapshot.cards)} cards",
            ("  sort: ", "dim"), self.sort, (f"  filter: {self.query_text}" if self.query_text else "", "yellow"),
        ))

    def current_card(self) -> Card | None:
        if not self.is_mounted:
            return None
        row = self.query_one(DataTable).cursor_row
        return self.rows[row] if 0 <= row < len(self.rows) else None

    # -- actions ------------------------------------------------------------------------------------------------

    def focus_list(self) -> None:
        self.query_one(DataTable).focus()

    def action_cycle_sort(self) -> None:
        names = list(SORTS)
        self.sort = names[(names.index(self.sort) + 1) % len(names)]
        self.redraw()

    def action_open(self) -> None:
        self.open_card()

    @on(DataTable.RowSelected)
    def on_row_selected(self) -> None:
        self.open_card()
