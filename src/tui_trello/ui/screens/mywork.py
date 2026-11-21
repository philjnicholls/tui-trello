"""My work: the current member's cards across every board, grouped by when they're due, with a preview."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from tui_trello.agenda import agenda
from tui_trello.backend import BackendError
from tui_trello.models import Card, WorkSnapshot
from tui_trello.ui import render
from tui_trello.ui.bidi import fit
from tui_trello.ui.screens.base import FILTER_HELP, ListScreen, TopBar
from tui_trello.ui.widgets.card_view import CardView
from tui_trello.ui.widgets.bell import Bell
from tui_trello.ui.widgets.spinner import Spinner

GROUP_STYLES = {"Overdue": "bold red", "Today": "bold yellow", "Done": "bold green"}
LOCATION_WIDTH = 30
DUE_WIDTH = 9
BADGES_WIDTH = 17
GAPS = 6


class MyWorkScreen(ListScreen):
    AUTO_FOCUS = "#agenda"

    DEFAULT_CSS = """
    MyWorkScreen #agenda, MyWorkScreen #agenda:focus {
        width: 3fr; height: 1fr; border: none; padding: 0 1; margin-right: 1; background: $surface;
    }
    MyWorkScreen #agenda > .option-list--option-disabled { color: $text; }
    MyWorkScreen #agenda:focus > .option-list--option-highlighted { background: $accent 40%; }
    MyWorkScreen #preview { width: 2fr; background: $surface; scrollbar-size-vertical: 1; }
    """

    BINDINGS = [
        Binding("l,right", "open", "Open", show=False),
        Binding("p", "toggle_preview", "Preview"),
    ]

    def __init__(self, now: datetime | None = None) -> None:
        super().__init__()
        self.now = now  # fixed in tests and screenshots; the real clock otherwise
        self.cards_by_option: dict[str, Card] = {}

    def compose(self) -> ComposeResult:
        with TopBar():
            yield Static(id="status")
            yield Bell()
            yield Spinner()
        yield Input(id="filter", placeholder=FILTER_HELP)
        with Horizontal(id="body"):
            yield OptionList(id="agenda")
            yield CardView(id="preview")
        yield Footer()

    def on_mount(self) -> None:
        self.app.store.work_changed.subscribe(self, lambda _: self.redraw())
        self.app.store.notifications_changed.subscribe(self, lambda _: self.redraw())
        if self.snapshot:
            self.redraw()
        else:
            self.load()

    @property
    def snapshot(self) -> WorkSnapshot | None:
        return self.app.store.work

    @work(exclusive=True, group="my-work")
    async def load(self) -> None:
        self.query_one("#status", Static).update(Text("My work", style="bold"))
        try:
            await self.app.store.load_work()
        except BackendError as exc:
            self.query_one("#status", Static).update(Text(str(exc), style="red"))

    # -- drawing --------------------------------------------------------------------------------------------------

    def redraw(self) -> None:
        if not (work := self.snapshot):
            return
        now = self.now or datetime.now(timezone.utc)
        current = self.current_card()
        cards = self.card_query.filter(work)
        groups = agenda(cards, now)
        options = self.query_one("#agenda", OptionList)
        width = options.scrollable_content_region.width
        location_width = min(LOCATION_WIDTH, width // 4)
        name_width = max(12, width - location_width - DUE_WIDTH - BADGES_WIDTH - GAPS)

        self.cards_by_option = {}
        unread = self.app.store.unread_by_card()
        rows: list[Option] = []
        for group, group_cards in groups:
            rows.append(Option(Text.assemble((group.upper(), GROUP_STYLES.get(group, "bold")),
                                             (f"  {len(group_cards)}", "dim")), disabled=True))
            for card in group_cards:
                self.cards_by_option[card.id] = card
                rows.append(Option(self.row(card, work, now, name_width, location_width, unread[card.id]),
                                   id=card.id))
        options.set_options(rows)

        ids = [option.id for option in rows]
        if current and current.id in ids:
            options.highlighted = ids.index(current.id)
        elif self.cards_by_option:
            options.highlighted = ids.index(next(iter(self.cards_by_option)))

        overdue = next((len(c) for g, c in groups if g == "Overdue"), 0)
        status = Text.assemble(
            ("My work", "bold"), f"  {len(cards)} cards on {len({c.board_id for c in cards})} boards",
            (f"  {overdue} overdue", "red") if overdue else "",
            (f"   filter: {self.query_text}", "yellow") if self.query_text else "",
        )
        self.query_one("#status", Static).update(status)
        self.query_one(CardView).show(self.current_card(), work)

    @staticmethod
    def row(card: Card, work: WorkSnapshot, now: datetime, name_width: int, location_width: int,
            unread: int = 0) -> Text:
        dots = Text.assemble(render.label_dots(card.labels), " " if card.labels else "")
        name = Text.assemble(dots, fit(card.name, name_width - dots.cell_len))
        location = fit(Text.assemble(work.list_named(card.list_id), (f" · {work.board_named(card.board_id)}", "dim")),
                       location_width)
        due = render.due_text(card, now)
        due.truncate(DUE_WIDTH, pad=True)
        row = Text.assemble(name, "  ", location, "  ", due, "  ", render.badges(card, now, due=False, unread=unread))
        row.no_wrap, row.overflow = True, "ellipsis"
        return row

    def on_resize(self) -> None:
        self.redraw()

    # -- events and actions ---------------------------------------------------------------------------------------

    @on(OptionList.OptionHighlighted, "#agenda")
    def on_highlighted(self) -> None:
        if self.snapshot:
            self.query_one(CardView).show(self.current_card(), self.snapshot)

    @on(OptionList.OptionSelected, "#agenda")
    def on_selected(self) -> None:
        self.open_card()

    def current_card(self) -> Card | None:
        if not self.is_mounted:
            return None
        option = self.query_one("#agenda", OptionList).highlighted_option
        return self.cards_by_option.get(option.id) if option and option.id else None

    def focus_list(self) -> None:
        self.query_one("#agenda", OptionList).focus()

    def action_open(self) -> None:
        self.open_card()

    def action_toggle_preview(self) -> None:
        preview = self.query_one(CardView)
        preview.display = not preview.display
        self.call_after_refresh(self.redraw)  # the list's width changed
