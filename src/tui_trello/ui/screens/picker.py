"""Reusable modals: a fuzzy picker (boards, lists, labels, checklist items, attachments, files, ...) and a text
prompt (comments, descriptions)."""

from __future__ import annotations

import re
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from rich.style import Style
from rich.text import Span, Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.content import Content
from textual.fuzzy import Matcher
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Label, OptionList, TextArea
from textual.widgets.option_list import Option

from tui_trello.backend import BackendError
from tui_trello.emoji import with_emoji
from tui_trello.files import human_size
from tui_trello.mentions import candidates, typing_mention
from tui_trello.models import Attachment, Card, Checklist, Member
from tui_trello.ui import clipboard, keymap, markdown
from tui_trello.ui.bidi import BidiText, has_rtl
from tui_trello.ui.commands import match_score

T = TypeVar("T")


def to_content(text: Text) -> Content:
    """A Rich `Text` as Textual `Content`. Textual parses a style given as a string with its own colour names, which
    differ from Rich's (`dark_orange`, `dodger_blue1`), and drops the colour without a word if it can't; so a string
    style, the text's own or a span's, is parsed by Rich first."""
    text = text.copy()
    if isinstance(text.style, str) and text.style:
        text.style = Style.parse(text.style)
    text.spans = [Span(span.start, span.end, Style.parse(span.style) if isinstance(span.style, str) else span.style)
                  for span in text.spans]
    return Content.from_rich_text(text)


@dataclass(frozen=True)
class Choice(Generic[T]):
    label: str  # what typing matches against
    value: T
    hint: str = ""  # dim text after the label
    marker: Text | None = None  # shown before the label, e.g. a label's colour
    text: Text | None = None  # the label styled, e.g. from Markdown; its plain text must be the label
    search: str = ""  # the name as stored, if the label shows it differently (`:rocket:` as 🚀): typing matches it too
    search_only: bool = False  # match `search` alone: the label is long, and fuzzy matching all of it would be slow


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
    PickerScreen .hint { color: $text-muted; margin-top: 1; width: 100%; }
    PickerScreen Input, PickerScreen Input:focus { border: none; height: 1; padding: 0; margin-bottom: 1; }
    PickerScreen OptionList { border: none; height: auto; max-height: 20; background: transparent; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", id="picker.close"),
        Binding("ctrl+j,down,ctrl+n", "cursor(1)", "Down", show=False, id="picker.down"),
        Binding("ctrl+k,up,ctrl+p", "cursor(-1)", "Up", show=False, id="picker.up"),
    ]

    FOCUS_WIDGETS = (Input, OptionList)  # the widgets whose own keys can't be changed
    HINT = ""  # with {id} placeholders for keys
    PLACEHOLDER = "Type to filter…"

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
            yield Input(placeholder=self.PLACEHOLDER)
            yield OptionList()
            if self.HINT:
                yield Label(keymap.of(self.app).fill(self.HINT), classes="hint")

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
            scored = [(self.score(matcher, c), c) for c in self.choices]
            matches = [c for score, c in sorted(scored, key=lambda sc: -sc[0]) if score > 0]
            prompts = [self.highlight(matcher, c) for c in matches]
        else:
            matches = self.choices
            prompts = [to_content(c.text) if c.text else c.label for c in matches]
        extras = self.extras(query)
        self.shown = matches + extras
        options.set_options([self.option(p, c) for p, c in zip(prompts, matches, strict=True)]
                            + [self.option(c.label, c) for c in extras])
        options.highlighted = 0 if self.shown else None

    @staticmethod
    def score(matcher: Matcher, choice: Choice) -> float:
        """How well the query matches the label or, if it has one, the stored name."""
        if choice.search_only:
            return matcher.match(choice.search)
        return match_score(matcher, choice.label, choice.search)

    @staticmethod
    def highlight(matcher: Matcher, choice: Choice) -> Content:
        """The label, styled if the choice has `text`, with the matched letters highlighted."""
        content = to_content(choice.text) if choice.text else Content(choice.label)
        if choice.search_only:
            return content
        _, offsets = matcher.fuzzy_search.match(matcher.query, choice.label)
        for offset in offsets:
            if not choice.label[offset].isspace():
                content = content.stylize(matcher.match_style, offset, offset + 1)
        return content

    @staticmethod
    def option(prompt: str | Content, choice: Choice) -> Option:
        """`prompt` is the label, or the label with the matched letters highlighted."""
        marker = choice.marker or Text("")
        hint = Text(f"  {choice.hint}", style="dim") if choice.hint else Text("")
        if has_rtl(choice.label):  # fuzzy highlighting is in logical order; show the reordered name instead
            return Option(BidiText(Text.assemble(marker, choice.text or choice.label, hint), align_rtl=False))
        return Option(Content.assemble(to_content(marker), prompt, to_content(hint)))

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


class ConfirmScreen(ModalScreen[bool]):
    """A question with a yes: only the yes key confirms (not Enter, which a habit could press). Dismisses with True
    for yes, False for anything else. `title` and `message` are drawn as they are: they may hold a card's name."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 60; max-width: 90%; height: auto; border: round $accent; background: $surface; padding: 0 1;
    }
    ConfirmScreen .title { text-style: bold; color: $accent; }
    ConfirmScreen .hint { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes", id="confirm.yes"),
        Binding("n,escape", "cancel", "Cancel", id="confirm.no"),
    ]

    def __init__(self, title: str, message: str, verb: str) -> None:
        super().__init__()
        self.title_text = title
        self.message = message
        self.verb = verb

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title", markup=False)
            yield Label(self.message, markup=False)
            yield Label(keymap.of(self.app).fill("{confirm.yes}: ") + f"{self.verb} · "
                        + keymap.of(self.app).fill("{confirm.no}: cancel"), classes="hint", markup=False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TextPromptScreen(ModalScreen[str | None]):
    """A text box. Enter saves, alt+enter (or ctrl+j) starts a new line, Esc cancels. Dismisses with the text
    (stripped, unless `strip` is False; None if blank), or None if cancelled.

    `multiline` makes it an editor for longer text: bigger, enter starts a new line, ctrl+s saves, and it dismisses
    with the text as typed, blank included (clearing a description is an edit), None only if cancelled.

    `text` is what the box starts with (a draft). `on_change` is called with the text a moment after typing stops,
    and when the box closes either way, so the caller can keep a draft. `hint` is added to the keys shown below.

    With `mentions` (a coroutine function returning members), typing "@" shows matching members below the box:
    tab or enter puts in the highlighted one's @username, up and down choose, Esc hides the list.

    With `attach` (a coroutine function that uploads a file and returns the text to put in for it), ctrl+o browses
    for a file and puts its link in at the cursor.
    """

    DEFAULT_CSS = """
    TextPromptScreen { align: center middle; }
    TextPromptScreen > Vertical {
        width: 70; max-width: 90%; height: auto; border: round $accent; background: $surface; padding: 0 1;
    }
    TextPromptScreen .title { text-style: bold; color: $accent; }
    TextPromptScreen .hint { color: $text-muted; }
    TextPromptScreen TextArea { height: 10; }
    TextPromptScreen.editor > Vertical { width: 100; }
    TextPromptScreen.editor TextArea { height: 70vh; }
    TextPromptScreen .notice { color: $warning; }
    TextPromptScreen #mentions { display: none; height: auto; max-height: 8; border: none; background: $boost; }
    TextPromptScreen #mentions.visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True, id="editor.cancel"),
        Binding("enter", "enter", "Save", priority=True, id="editor.enter"),
        Binding("ctrl+s", "save", "Save", show=False, priority=True, id="editor.save"),
        Binding("tab", "accept_mention", "Mention", show=False, priority=True, id="editor.mention"),
        Binding("down", "mention_cursor(1)", "Next mention", show=False, priority=True, id="editor.mention_down"),
        Binding("up", "mention_cursor(-1)", "Previous mention", show=False, priority=True, id="editor.mention_up"),
        # alt+enter needs ui/keys_compat.py
        Binding("alt+enter,ctrl+j", "newline", "New line", priority=True, id="editor.newline"),
        Binding("ctrl+o", "attach", "Attach a file", show=False, priority=True, id="editor.attach"),
    ]

    FOCUS_WIDGETS = (TextArea,)

    DRAFT_DELAY = 0.4  # seconds after the last key before `on_change`

    def __init__(self, title: str, mentions: Callable[[], Awaitable[list[Member]]] | None = None, *,
                 text: str = "", multiline: bool = False, on_change: Callable[[str], None] | None = None,
                 notice: str = "", attach: Callable[[Path], Awaitable[str]] | None = None, hint: str = "",
                 strip: bool = True) -> None:
        super().__init__(classes="editor" if multiline else "")
        self.attach = attach
        self.title_text = title
        self.initial_text = text
        self.multiline = multiline
        self.on_change = on_change
        self.notice = notice
        self.hint = hint
        self.strip = strip
        self.change_timer: Timer | None = None
        self.mentions_loader = mentions
        self.members: list[Member] | None = None
        self.suggested: list[Member] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="title")
            if self.notice:
                yield Label(self.notice, classes="notice")
            yield TextArea(self.initial_text)
            yield OptionList(id="mentions")
            if self.multiline:
                hint = "{editor.save} save · {editor.enter} new line · {editor.cancel} close"
            else:
                hint = "{editor.enter} send · {editor.newline} new line · {editor.cancel} close"
            if self.on_change:
                hint += " (keeps a draft)"
            if self.mentions_loader:
                hint += " · @ mention"
            if self.attach:
                hint += " · {editor.attach} attach a file"
            if self.hint:
                hint += f" · {self.hint}"
            yield Label(keymap.of(self.app).fill(hint), classes="hint")

    def on_mount(self) -> None:
        area = self.query_one(TextArea)
        area.move_cursor(area.document.end)

    @property
    def suggesting(self) -> bool:
        return bool(self.suggested)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # While no suggestions are showing, tab and the arrows belong to the text box.
        if action in ("accept_mention", "mention_cursor"):
            return self.suggesting
        if action == "attach":
            return self.attach is not None
        return True

    @on(TextArea.Changed)
    @on(TextArea.SelectionChanged)
    def on_text(self) -> None:
        self.suggest()

    @on(TextArea.Changed)
    def on_edit(self) -> None:
        if self.on_change:
            if self.change_timer:
                self.change_timer.stop()
            self.change_timer = self.set_timer(self.DRAFT_DELAY, self.report_change)

    def report_change(self) -> None:
        if self.change_timer:
            self.change_timer.stop()
            self.change_timer = None
        if self.on_change:
            self.on_change(self.query_one(TextArea).text)

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
            self.report_change()
            self.dismiss(None)

    def action_enter(self) -> None:
        if self.suggesting:
            self.action_accept_mention()
        elif self.multiline:
            self.action_newline()
        else:
            self.action_save()

    def action_save(self) -> None:
        if self.suggesting:
            self.action_accept_mention()
            return
        self.report_change()  # the caller drops the draft once the text is safely on Trello
        text = self.query_one(TextArea).text
        if self.multiline:
            self.dismiss(text)
        else:
            self.dismiss((text.strip() if self.strip else text) if text.strip() else None)

    def action_newline(self) -> None:
        self.query_one(TextArea).insert("\n")

    @work(group="attach")
    async def action_attach(self) -> None:
        if not self.attach or not (path := await self.app.push_screen_wait(FilePickerScreen())):
            return
        try:
            text = await self.attach(path)
        except BackendError as exc:
            self.notify(str(exc), severity="error")
            return
        area = self.query_one(TextArea)
        area.insert(text)
        area.focus()


class LabelPickerScreen(PickerScreen):
    """A card's labels: Enter puts the highlighted label on the card or takes it off, and the picker stays open
    so several can be changed; typing a name that doesn't exist offers to create it."""

    HINT = "enter: on/off · a new name creates it · {picker.close}: done"

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
        self.query_one(".title", Label).update(Text.assemble("Labels for “", visual(with_emoji(card.name)), "”"))
        return [
            Choice(with_emoji(label.name) or label.color or "?", label, "✓" if label.id in on else "",
                   Text("█ ", style=label.rich_colour), search=label.name)
            for label in await self.app.store.labels(card.board_id)
        ]

    def extras(self, query: str) -> list[Choice]:
        name = query.strip()
        if not name or any(name.lower() in (c.label.lower(), c.value.name.lower()) for c in self.choices):
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


class MemberPickerScreen(PickerScreen):
    """A card's members: Enter puts the highlighted board member on the card or takes them off, and the picker stays
    open so several can be changed. You come first."""

    HINT = "enter: on/off · {picker.close}: done"

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        super().__init__("Members", self.member_choices)

    @property
    def card(self):
        return self.app.store.find_card(self.card_id)

    async def member_choices(self) -> list[Choice]:
        from tui_trello.ui.bidi import visual

        store, card = self.app.store, self.card
        me = await store.me()
        members = await store.members(card.board_id)
        self.query_one(".title", Label).update(Text.assemble("Members of “", visual(with_emoji(card.name)), "”"))
        ordered = sorted(members, key=lambda m: (m.id != me.id, (m.full_name or m.username).lower()))
        return [
            Choice(member.full_name or member.username, member,
                   " ".join(part for part in ("✓" if member.id in card.member_ids else "",
                                              "you" if member.id == me.id else "") if part),
                   visual(Text(f"{member.initials} ", style="cyan")), search=member.username)
            for member in ordered
        ]

    def choose(self, choice: Choice) -> None:
        self.apply(choice.value)

    @work(group="members")  # not exclusive: a second Enter queues behind the first in the store, never cancels it
    async def apply(self, member: Member) -> None:
        store, card = self.app.store, self.card
        if not card:  # an earlier press took the card away
            self.dismiss(None)
            return
        try:
            await store.toggle_member(card, member)
        except BackendError as exc:
            self.notify(str(exc), severity="error", markup=False)
        else:
            if not self.card and member.id == store.me_id:  # you left a card that only my work held
                self.notify(f"You left “{with_emoji(card.name)}”", markup=False)
        if not self.card:  # the card is gone from the store
            self.dismiss(None)
            return
        highlighted = self.query_one(OptionList).highlighted
        self.choices = await self.member_choices()
        self.refilter()
        if highlighted is not None:
            self.query_one(OptionList).highlighted = min(highlighted, len(self.shown) - 1)


class ChecklistPickerScreen(PickerScreen):
    """A card's checklist items: Enter ticks the highlighted one or unticks it, and the picker stays open so several
    can be done; typing text that matches no item offers to add it to a checklist, or to start a new checklist."""

    HINT = "enter: tick/untick · new text adds an item · {picker.close}: done"

    def __init__(self, card_id: str) -> None:
        self.card_id = card_id
        self.checklists: list[Checklist] = []
        super().__init__("Checklist", self.item_choices)

    async def item_choices(self) -> list[Choice]:
        from tui_trello.ui.bidi import visual

        store = self.app.store
        if card := store.find_card(self.card_id):
            self.query_one(".title", Label).update(Text.assemble("Checklist for “", visual(with_emoji(card.name)), "”"))
        self.checklists = await store.checklists(self.card_id)
        several = len(self.checklists) > 1
        choices = []
        for checklist in self.checklists:
            for item in checklist.items:
                text = markdown.inline(item.name)
                choices.append(Choice(text.plain, ("toggle", item), with_emoji(checklist.name) if several else "",
                                      Text("☑ ", style="green") if item.checked else Text("☐ ", style="dim"), text,
                                      search=item.name))
        return choices

    def extras(self, query: str) -> list[Choice]:
        name = query.strip()
        if not name or any(name.lower() in (c.label.lower(), c.value[1].name.lower()) for c in self.choices):
            return []
        plus = Text("+ ", style="bold green")
        return [Choice(f"add “{name}” to {with_emoji(checklist.name)}", ("add", checklist.id, name), marker=plus)
                for checklist in self.checklists] + [Choice(f"new checklist “{name}”", ("new", name), marker=plus)]

    def choose(self, choice: Choice) -> None:
        self.apply(choice.value)

    @work(exclusive=True, group="checklist")
    async def apply(self, value: tuple) -> None:
        store = self.app.store
        try:
            if value[0] == "toggle":
                await store.toggle_check_item(self.card_id, value[1])
            elif value[0] == "add":
                await store.add_check_item(self.card_id, value[1], value[2])
                self.query_one(Input).value = ""
            else:
                await store.create_checklist(self.card_id, value[1])
                self.query_one(Input).value = ""
        except BackendError as exc:
            self.notify(str(exc), severity="error")
        highlighted = self.query_one(OptionList).highlighted
        self.choices = await self.item_choices()
        self.refilter()
        if highlighted is not None and value[0] == "toggle" and self.shown:
            self.query_one(OptionList).highlighted = min(highlighted, len(self.shown) - 1)


class AttachmentPickerScreen(PickerScreen):
    """A card's attachments. Enter opens the highlighted one in the web browser: a link, or an upload, which
    trello.com serves to the logged-in browser. ctrl+s can't save an upload (Trello refuses downloads with the OAuth
    login), so it says to open it in the browser instead; ctrl+y copies the link. "attach a file" browses for one
    to upload; typing or pasting a URL offers to attach it as a link."""

    HINT = ("enter: open in the browser (save files from there) · {popup.copy_link}: copy link · "
            "paste a URL to attach it")
    SAVE_IN_BROWSER = ("Trello doesn't let apps save uploaded files with the OAuth login (tui-trello login). "
                       "Press enter to open it in your web browser and save it from there.")

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", show=False, id="attachments.save"),
        Binding("ctrl+y", "copy_link", "Copy link", show=False, id="popup.copy_link"),
    ]

    def __init__(self, card_id: str, target: str = "") -> None:
        """`target` is the id of the attachment to start on."""
        self.card_id = card_id
        self.target_id = target
        super().__init__("Attachments", self.attachment_choices)

    def refilter(self) -> None:
        super().refilter()
        if self.target_id and self.loaded:  # the first fill only; typed text has the highlight, not the target
            index = next((i for i, c in enumerate(self.shown)
                          if isinstance(c.value, Attachment) and c.value.id == self.target_id), None)
            if index is not None and not self.query_text:
                self.query_one(OptionList).highlighted = index
            self.target_id = ""

    async def attachment_choices(self) -> list[Choice]:
        from tui_trello.ui.bidi import visual

        store = self.app.store
        if card := store.find_card(self.card_id):
            title = Text.assemble("Attachments on “", visual(with_emoji(card.name)), "”")
            self.query_one(".title", Label).update(title)
        return [Choice(with_emoji(a.name), a, attachment_hint(a), attachment_marker(a), search=a.name)
                for a in await store.attachments(self.card_id)]

    def extras(self, query: str) -> list[Choice]:
        plus = Text("+ ", style="bold green")
        url = query.strip()
        link = [Choice(f"attach the link {url}", ("link", url), marker=plus)] if re.match(r"https?://\S+$", url) else []
        return link + [Choice("attach a file…", ("file",), marker=plus)]

    def highlighted(self) -> Attachment | None:
        highlighted = self.query_one(OptionList).highlighted
        if highlighted is None or highlighted >= len(self.shown):
            return None
        value = self.shown[highlighted].value
        return value if isinstance(value, Attachment) else None

    def choose(self, choice: Choice) -> None:
        if isinstance(choice.value, Attachment):
            webbrowser.open(choice.value.url)
            self.dismiss(None)
        else:
            self.add(choice.value)

    @work(group="attachments")
    async def add(self, value: tuple[str, ...]) -> None:
        store = self.app.store
        try:
            if value[0] == "link":
                attachment = await store.attach_link(self.card_id, value[1])
            elif path := await self.app.push_screen_wait(FilePickerScreen()):
                attachment = await store.attach_file(self.card_id, path)
            else:
                return
        except BackendError as exc:
            self.notify(str(exc), severity="error")
            return
        self.notify(f"Attached {attachment.name}")
        self.query_one(Input).value = ""
        self.choices = await self.attachment_choices()
        self.refilter()

    def action_save(self) -> None:
        if not (attachment := self.highlighted()):
            return
        if not attachment.is_upload:
            self.notify("That's a link, not a file: enter opens it")
            return
        self.notify(self.SAVE_IN_BROWSER, title=f"Can't save {attachment.name}", severity="warning", timeout=10)

    def action_copy_link(self) -> None:
        if attachment := self.highlighted():
            clipboard.copy(attachment.url, self.app.copy_to_clipboard)
            self.notify(attachment.url, title="Copied the link")


class LinkPickerScreen(PickerScreen[str]):
    """The links in a card's text. Enter dismisses with the highlighted link's URL, for the caller to follow;
    ctrl+o opens it in the web browser whatever it is, ctrl+y copies it, alt+p previews a card, comment or
    attachment link in a popup (any other link is followed, as on enter)."""

    HINT = ("enter: follow · {popup.preview}: preview · {popup.open_in_browser}: open in the browser · "
            "{popup.copy_link}: copy link")

    BINDINGS = [
        # priority: a terminal sends alt+p as ESC then p, which reaches the filter box as a printable `p` that it
        # would type instead of letting the screen's binding see it.
        Binding("alt+p", "preview", "Preview", show=False, priority=True, id="popup.preview"),
        Binding("ctrl+o", "open_in_browser", "Open in the browser", show=False, id="popup.open_in_browser"),
        Binding("ctrl+y", "copy_link", "Copy link", show=False, id="popup.copy_link"),
    ]

    def __init__(self, card: Card, choices: list[Choice[str]]) -> None:
        self.card = card
        super().__init__(f"Links on “{with_emoji(card.name)}”", choices)

    def on_mount(self) -> None:
        from tui_trello.ui.bidi import visual

        self.query_one(".title", Label).update(Text.assemble("Links on “", visual(with_emoji(self.card.name)), "”"))

    def highlighted(self) -> str | None:
        highlighted = self.query_one(OptionList).highlighted
        return self.shown[highlighted].value if highlighted is not None and highlighted < len(self.shown) else None

    @work
    async def action_preview(self) -> None:
        """Preview the highlighted link on top of this list. Esc there comes back here as it was; enter follows the
        link, ctrl+o opens it in the browser (this list closes either way). A link with no preview is followed."""
        # Imported here: preview imports follow, which imports this module.
        from tui_trello.ui.screens.preview import previewable

        highlighted = self.query_one(OptionList).highlighted
        if highlighted is None or highlighted >= len(self.shown):
            return
        choice = self.shown[highlighted]
        if not previewable(choice.value, self.app.store.link_hosts):
            self.dismiss(choice.value)
        elif (result := await self.app.preview_link(choice.value, choice.hint)) is not None:
            self.dismiss(result or None)  # "" if it went to the web browser

    def action_open_in_browser(self) -> None:
        from tui_trello.ui import follow

        if url := self.highlighted():
            follow.open_in_browser(self.app, url)
            self.dismiss(None)

    def action_copy_link(self) -> None:
        if url := self.highlighted():
            clipboard.copy(url, self.app.copy_to_clipboard)
            self.notify(url, title="Copied the link", markup=False)


def attachment_marker(attachment: Attachment) -> Text:
    return Text("📎 " if attachment.is_upload else "🔗 ")


def attachment_hint(attachment: Attachment) -> str:
    """An upload's size and date; a link's site."""
    if not attachment.is_upload:
        return re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", attachment.url)
    when = f"{attachment.date:%d %b %Y}" if attachment.date else ""
    return " · ".join(part for part in (human_size(attachment.size) if attachment.size else "", when) if part)


class FilePickerScreen(PickerScreen):
    """Browse for a file to attach. Enter goes into a folder or picks a file; typing filters the folder, and typing a
    path (~ works) offers to pick that file or go to that folder. Hidden files are left out unless typed. Starts
    where the last file was picked, this session, else in the working directory."""

    HINT = "enter: open folder / pick file · type a path to go there · {picker.close}: cancel"

    last_dir: Path | None = None

    def __init__(self, title: str = "Attach which file?", start: Path | None = None) -> None:
        self.base_title = title
        self.cwd = (start or FilePickerScreen.last_dir or Path.cwd()).resolve()
        super().__init__(self.heading(), self.listing())

    def heading(self) -> str:
        home = str(Path.home())
        where = str(self.cwd)
        return f"{self.base_title}  {'~' + where[len(home):] if where.startswith(home) else where}"

    def listing(self) -> list[Choice[Path]]:
        folder = Text("▸ ", style="bold blue")
        choices = [Choice("../", self.cwd.parent, marker=folder)] if self.cwd.parent != self.cwd else []
        try:
            entries = sorted(self.cwd.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            return [*choices, Choice(f"can't read this folder: {exc.strerror}", self.cwd.parent, marker=folder)]
        files = []
        for path in entries:
            if path.name.startswith("."):
                continue
            try:
                if path.is_dir():
                    choices.append(Choice(f"{path.name}/", path, marker=folder))
                else:
                    files.append(Choice(path.name, path, human_size(path.stat().st_size), Text("  ")))
            except OSError:
                continue  # a broken link, or no permission to look
        return choices + files

    def extras(self, query: str) -> list[Choice]:
        typed = query.strip()
        if not typed or not ("/" in typed or typed.startswith("~")):
            return []
        path = Path(typed).expanduser()
        path = path if path.is_absolute() else self.cwd / path
        if path.is_file():
            return [Choice(f"pick {path}", path, marker=Text("+ ", style="bold green"))]
        if path.is_dir():
            return [Choice(f"go to {path}/", path, marker=Text("▸ ", style="bold blue"))]
        return []

    def choose(self, choice: Choice) -> None:
        path: Path = choice.value
        if path.is_dir():
            self.cwd = path.resolve()
            self.query_one(".title", Label).update(self.heading())
            self.choices = self.listing()
            self.query_one(Input).value = ""
            self.refilter()
        else:
            FilePickerScreen.last_dir = path.parent
            self.dismiss(path)
