"""Reusable modals: a fuzzy picker (boards, lists, labels, ...) and a text prompt (comments, ...)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.content import Content
from textual.fuzzy import Matcher
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, TextArea
from textual.widgets.option_list import Option

from tui_trello.backend import BackendError
from tui_trello.mentions import candidates, typing_mention
from tui_trello.models import Member
from tui_trello.ui.bidi import BidiText, has_rtl

T = TypeVar("T")


@dataclass(frozen=True)
class Choice(Generic[T]):
    label: str  # what typing matches against
    value: T
    hint: str = ""  # dim text after the label
    marker: Text | None = None  # shown before the label, e.g. a label's colour


class PickerScreen(ModalScreen[T | None]):
    """Type to filter, Enter to choose, Esc to cancel. Dismisses with the chosen value or None.

    `choices` may be a coroutine function: the picker opens at once and fills in when it returns, keeping whatever
    was typed meanwhile. Subclasses can override `choose()` to stay open (see `LabelPickerScreen`) and `extras()` to
    add entries that don't depend on matching, such as "create".
    """

    DEFAULT_CSS = """
    PickerScreen { align: center middle; }
    PickerScreen > Vertical {
        width: 60; max-width: 90%; height: auto; max-height: 70%;
        border: round $accent; background: $surface; padding: 0 1;
    }
    PickerScreen .title { text-style: bold; color: $accent; padding: 0 0 1 0; }
    PickerScreen .hint { color: $text-muted; margin-top: 1; }
    PickerScreen Input, PickerScreen Input:focus { border: none; height: 1; padding: 0; margin-bottom: 1; }
    PickerScreen OptionList { border: none; height: auto; max-height: 20; background: transparent; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("down,ctrl+n,ctrl+j", "cursor(1)", "Down", show=False),
        Binding("up,ctrl+p,ctrl+k", "cursor(-1)", "Up", show=False),
    ]

    HINT = ""

    def __init__(self, title: str, choices: list[Choice[T]] | Callable[[], Awaitable[list[Choice[T]]]]) -> None:
        super().__init__()
        self.title_text = title
        self.loader = None if isinstance(choices, list) else choices
        self.choices: list[Choice[T]] = choices if isinstance(choices, list) else []
        self.loaded = self.loader is None
        self.shown: list[Choice[T]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title")
            yield Input(placeholder="Type to filter…")
            yield OptionList()
            if self.HINT:
                yield Label(self.HINT, classes="hint")

    def on_mount(self) -> None:
        if self.loader:
            self.query_one(OptionList).set_options([Option(Text("Loading…", style="dim"), disabled=True)])
            self.load()
        else:
            self.refilter()

    @work
    async def load(self) -> None:
        try:
            self.choices = await self.loader()
        except BackendError as exc:
            self.notify(str(exc), severity="error")
            self.dismiss(None)
            return
        self.loaded = True
        self.refilter()

    @property
    def query_text(self) -> str:
        return self.query_one(Input).value

    @on(Input.Changed)
    def on_query(self) -> None:
        if self.loaded:
            self.refilter()

    def extras(self, query: str) -> list[Choice[T]]:
        return []

    def refilter(self) -> None:
        query = self.query_text
        options = self.query_one(OptionList)
        if query:
            matcher = Matcher(query)
            scored = [(matcher.match(c.label), c) for c in self.choices]
            matches = [c for score, c in sorted(scored, key=lambda sc: -sc[0]) if score > 0]
            prompts = [matcher.highlight(c.label) for c in matches]
        else:
            matches = self.choices
            prompts = [c.label for c in matches]
        extras = self.extras(query)
        self.shown = matches + extras
        options.set_options([self.option(p, c) for p, c in zip(prompts, matches)]
                            + [self.option(c.label, c) for c in extras])
        options.highlighted = 0 if self.shown else None

    @staticmethod
    def option(prompt: str | Content, choice: Choice) -> Option:
        """`prompt` is the label, or the label with the matched letters highlighted."""
        marker = choice.marker or Text("")
        hint = Text(f"  {choice.hint}", style="dim") if choice.hint else Text("")
        if has_rtl(choice.label):  # fuzzy highlighting is in logical order; show the reordered name instead
            return Option(BidiText(Text.assemble(marker, choice.label, hint), align_rtl=False))
        return Option(Content.assemble(Content.from_rich_text(marker), prompt, Content.from_rich_text(hint)))

    def action_cursor(self, step: int) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            options.highlighted = ((options.highlighted or 0) + step) % options.option_count

    def action_close(self) -> None:
        self.dismiss(None)

    def choose(self, choice: Choice[T]) -> None:
        self.dismiss(choice.value)

    @on(Input.Submitted)
    def on_submit(self) -> None:
        highlighted = self.query_one(OptionList).highlighted
        if highlighted is not None and self.shown:
            self.choose(self.shown[highlighted])

    @on(OptionList.OptionSelected)
    def on_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index < len(self.shown):
            self.choose(self.shown[event.option_index])


class TextPromptScreen(ModalScreen[str | None]):
    """A text box. Enter saves, alt+enter (or ctrl+j) starts a new line, Esc cancels.

    With `mentions` (a coroutine function returning members), typing "@" shows matching members below the box:
    tab or enter puts in the highlighted one's @username, up and down choose, Esc hides the list.
    """

    DEFAULT_CSS = """
    TextPromptScreen { align: center middle; }
    TextPromptScreen > Vertical {
        width: 70; max-width: 90%; height: auto; border: round $accent; background: $surface; padding: 0 1;
    }
    TextPromptScreen .title { text-style: bold; color: $accent; }
    TextPromptScreen .hint { color: $text-muted; }
    TextPromptScreen TextArea { height: 10; }
    TextPromptScreen #mentions { display: none; height: auto; max-height: 8; border: none; background: $boost; }
    TextPromptScreen #mentions.visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter,ctrl+s", "save", "Save", priority=True),
        Binding("tab", "accept_mention", "Mention", show=False, priority=True),
        Binding("down", "mention_cursor(1)", show=False, priority=True),
        Binding("up", "mention_cursor(-1)", show=False, priority=True),
        Binding("alt+enter,ctrl+j", "newline", "New line", priority=True),  # alt+enter needs ui/keys_compat.py
    ]

    def __init__(self, title: str, mentions: Callable[[], Awaitable[list[Member]]] | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.mentions_loader = mentions
        self.members: list[Member] | None = None
        self.suggested: list[Member] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title")
            yield TextArea()
            yield OptionList(id="mentions")
            hint = "enter send · alt+enter new line · esc cancel"
            yield Label(f"{hint} · @ mention" if self.mentions_loader else hint, classes="hint")

    @property
    def suggesting(self) -> bool:
        return bool(self.suggested)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # While no suggestions are showing, tab and the arrows belong to the text box.
        if action in ("accept_mention", "mention_cursor"):
            return self.suggesting
        return True

    @on(TextArea.Changed)
    @on(TextArea.SelectionChanged)
    def on_text(self) -> None:
        self.suggest()

    @work(exclusive=True, group="mentions")
    async def suggest(self) -> None:
        query = self.typing()
        if query is None or not self.mentions_loader:
            self.show_suggestions([])
            return
        if self.members is None:
            try:
                self.members = await self.mentions_loader()
            except BackendError as exc:
                self.notify(str(exc), severity="error")
                self.members = []
        self.show_suggestions(candidates(self.members, query))

    def typing(self) -> str | None:
        area = self.query_one(TextArea)
        row, column = area.cursor_location
        return typing_mention(area.document.get_line(row)[:column])

    def show_suggestions(self, members: list[Member]) -> None:
        from tui_trello.ui.bidi import visual

        self.suggested = members
        options = self.query_one("#mentions", OptionList)
        options.set_class(bool(members), "visible")
        options.set_options(
            Option(Text.assemble((f"@{m.username}", "bold cyan"), "  ", visual(Text(m.full_name, style="dim"))))
            for m in members
        )
        options.highlighted = 0 if members else None
        self.refresh_bindings()

    def action_mention_cursor(self, step: int) -> None:
        options = self.query_one("#mentions", OptionList)
        options.highlighted = ((options.highlighted or 0) + step) % len(self.suggested)

    def action_accept_mention(self) -> None:
        query = self.typing()
        highlighted = self.query_one("#mentions", OptionList).highlighted
        if query is None or highlighted is None:
            return
        area = self.query_one(TextArea)
        row, column = area.cursor_location
        area.replace(f"@{self.suggested[highlighted].username} ", (row, column - len(query) - 1), (row, column))
        self.show_suggestions([])

    def action_cancel(self) -> None:
        if self.suggesting:
            self.show_suggestions([])
        else:
            self.dismiss(None)

    def action_save(self) -> None:
        if self.suggesting:
            self.action_accept_mention()
            return
        text = self.query_one(TextArea).text.strip()
        self.dismiss(text or None)

    def action_newline(self) -> None:
        self.query_one(TextArea).insert("\n")


class LabelPickerScreen(PickerScreen):
    """A card's labels: Enter puts the highlighted label on the card or takes it off, and the picker stays open
    so several can be changed; typing a name that doesn't exist offers to create it."""

    HINT = "enter: on/off · a new name creates it · esc: done"

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        super().__init__("Labels", self.label_choices)

    @property
    def card(self):
        return self.app.store.find_card(self.card_id)

    async def label_choices(self) -> list[Choice]:
        from tui_trello.ui.bidi import visual

        card = self.card
        on = {label.id for label in card.labels}
        self.query_one(".title", Label).update(Text.assemble("Labels for “", visual(card.name), "”"))
        return [
            Choice(label.name or label.color or "?", label, "✓" if label.id in on else "",
                   Text("█ ", style=label.rich_colour))
            for label in await self.app.store.labels(card.board_id)
        ]

    def extras(self, query: str) -> list[Choice]:
        name = query.strip()
        if not name or any(c.label.lower() == name.lower() for c in self.choices):
            return []
        return [Choice(f"create “{name}”", ("create", name), marker=Text("+ ", style="bold green"))]

    def choose(self, choice: Choice) -> None:
        self.apply(choice.value)

    @work(exclusive=True, group="labels")
    async def apply(self, value) -> None:
        store, card = self.app.store, self.card
        try:
            if isinstance(value, tuple):  # ("create", name)
                await store.create_label(card, value[1])
                self.query_one(Input).value = ""
            else:
                await store.toggle_label(card, value)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
        highlighted = self.query_one(OptionList).highlighted
        self.choices = await self.label_choices()
        self.refilter()
        if highlighted is not None and not isinstance(value, tuple):
            self.query_one(OptionList).highlighted = min(highlighted, len(self.shown) - 1)
