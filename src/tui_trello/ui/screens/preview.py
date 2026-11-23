"""A popup showing what a link points to, without going there: a card or comment (the whole card, drawn with the card
pane) or an attachment. Esc closes it and leaves everything below as it was. Board and web links have no preview:
they are followed (`tui_trello.ui.follow`)."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from tui_trello import links
from tui_trello.backend import BackendError
from tui_trello.files import human_size
from tui_trello.models import Attachment, CardPreview, Member
from tui_trello.ui import clipboard, follow
from tui_trello.ui.bidi import visual
from tui_trello.ui.screens.picker import attachment_hint
from tui_trello.ui.widgets.card_view import CardView
from tui_trello.ui.widgets.spinner import Spinner

PREVIEWED = ("card", "comment", "attachment")
ARCHIVED = {"card": "Archived card", "list": "In an archived list", "board": "On a closed board"}


def previewable(url: str, hosts: frozenset[str] = links.TRELLO_HOSTS) -> bool:
    """Whether the link has a preview: a card, comment or attachment. Board and web links don't."""
    return links.parse(url, hosts).kind in PREVIEWED


class PreviewContext:
    """The `CardContext` a CardView needs to draw a previewed card: its location and its members. Nothing else is
    used, since the preview has no keys that act on the card."""

    def __init__(self, preview: CardPreview) -> None:
        self.preview = preview
        self.members: dict[str, Member] = preview.members

    def location(self, card) -> str:
        return self.preview.location


class PreviewCardView(CardView):
    KEY_HINTS = False  # x, a, c and e don't work in the popup, so it doesn't say they do
    MISSING_COMMENT = ("That comment isn't on the card any more, or is older than the 50 shown; "
                       "ctrl+o opens it on trello.com")

    def say_comment_missing(self) -> None:
        """In the popup, under the title, not in a toast that outlives it."""
        note = self.screen.query_one("#preview-note", Static)
        said = str(note.content)
        note.update(f"{said}\n{self.MISSING_COMMENT}" if said else self.MISSING_COMMENT)


class LinkPreviewScreen(ModalScreen[str | None]):
    """What a link points to, without going there. Dismisses with the URL to follow (enter on this link, or a click
    on a board link inside), "" if the link was opened in the web browser (ctrl+o), or None when closed (esc)."""

    HELP_PLACE = "preview"  # which keys `?` shows

    DEFAULT_CSS = """
    LinkPreviewScreen { align: center middle; }
    LinkPreviewScreen > Vertical {
        width: 100; max-width: 95%; height: 80%;
        border: round $accent; background: $surface; padding: 0 1;
    }
    LinkPreviewScreen Horizontal { height: 1; }
    LinkPreviewScreen .title { text-style: bold; color: $accent; width: 1fr; }
    LinkPreviewScreen .where, LinkPreviewScreen .hint { color: $text-muted; }
    LinkPreviewScreen .hint { margin-top: 1; width: 100%; }
    LinkPreviewScreen #preview-note { height: auto; color: $warning; }
    LinkPreviewScreen #preview-slot { height: 1fr; }
    LinkPreviewScreen #preview-body { height: 1fr; padding: 1 0; }
    LinkPreviewScreen PreviewCardView { height: 1fr; padding: 0; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,q", "close", "Close"),
        Binding("enter", "follow", "Follow", show=False),
        Binding("ctrl+o", "open_in_browser", "Open in the browser", show=False),
        Binding("ctrl+y", "copy_link", "Copy link", show=False),
        # App bindings don't reach a modal screen: these are the app keys that work here.
        Binding("question_mark", "app.toggle_help", "Keys", show=False),
        Binding("X", "app.toggle_done_check_items", "Done items", show=False),
        Binding("j,down", "app.motion('down')", "Down", show=False),
        Binding("k,up", "app.motion('up')", "Up", show=False),
        Binding("G,end", "app.motion('bottom')", "Bottom", show=False),
        Binding("home", "app.motion('top')", "Top", show=False),
        Binding("ctrl+d,pagedown", "app.motion('half_down')", "Half page down", show=False),
        Binding("ctrl+u,pageup", "app.motion('half_up')", "Half page up", show=False),
    ]

    HINT = "enter: follow · ctrl+o: open in the browser · ctrl+y: copy link · esc: close"

    def __init__(self, url: str, where: str = "") -> None:
        super().__init__()
        self.url = url
        self.where = where  # the picker row's hint: where the link was found

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                yield Label(classes="title")
                yield Spinner()
            if self.where:
                yield Label(self.where, classes="where", markup=False)
            yield Static(id="preview-note")
            yield Vertical(id="preview-slot")
            yield Label(self.HINT, classes="hint")

    def on_mount(self) -> None:
        self.link = links.parse(self.url, self.app.store.link_hosts)
        self.query_one(".title", Label).update(
            f"{follow.ICONS[self.link.kind]}{follow.KIND_NAMES.get(self.link.kind, self.link.kind).capitalize()}")
        self.query_one("#preview-slot").mount(Static(Text("Loading…", style="dim"), id="preview-loading"))
        self.load()

    @work(exclusive=True)
    async def load(self) -> None:
        """Fetch what the link points to and draw it; a failure is said in the popup, which stays. Closing the popup
        cancels this."""
        slot = self.query_one("#preview-slot", Vertical)
        shown = None  # the card to draw in the card pane, once it is mounted
        try:
            if self.link.kind == "attachment":
                widget = await self.attachment_body()
            else:
                shown = await self.app.store.card_preview(self.link.short_link)
                if shown.archived:
                    self.query_one("#preview-note", Static).update(ARCHIVED[shown.archived])
                widget = PreviewCardView()
        except BackendError as exc:
            widget = VerticalScroll(Static(Text(str(exc), style="red")), id="preview-body")
        await slot.remove_children()
        await slot.mount(widget)
        if shown:
            widget.show(shown.card, PreviewContext(shown), self.link.comment_id)
        widget.focus()

    async def attachment_body(self) -> VerticalScroll:
        store = self.app.store
        attachments, preview = await asyncio.gather(store.attachments(self.link.card_id),
                                                    store.card_preview(self.link.card_id))
        found = next((a for a in attachments if a.id == self.link.attachment_id), None)
        if found is None:
            body: Text | Group = Text("That attachment is no longer on its card", style="yellow")
        else:
            body = self.attachment_lines(found, preview)
        return VerticalScroll(Static(body), id="preview-body")

    @staticmethod
    def attachment_lines(attachment: Attachment, preview: CardPreview) -> Group:
        lines = [Text.assemble(("📎 " if attachment.is_upload else "🔗 "), visual(Text(attachment.name, style="bold")))]
        if attachment.is_upload:
            facts = [("File", attachment.file_name or attachment.name),
                     ("Size", human_size(attachment.size) if attachment.size else ""),
                     ("Type", attachment.mime_type),
                     ("Added", f"{attachment.date:%d %b %Y}" if attachment.date else "")]
            lines += [Text.assemble((f"{name:<6}", "dim"), value) for name, value in facts if value]
        else:
            lines += [Text.assemble(("Link  ", "dim"), attachment.url), Text(attachment_hint(attachment), style="dim")]
        lines += [Text(""), Text.assemble(("On card  ", "dim"), visual(Text(preview.card.name, style="bold"))),
                  Text.assemble(("         ", "dim"), visual(Text(preview.location)),
                                (f"  ({ARCHIVED[preview.archived].lower()})" if preview.archived else "", "yellow"))]
        return Group(*lines)

    def open_link(self, url: str) -> None:
        """A click on a link inside the preview: preview that, on top (esc comes back here); a board goes to the
        board; a web page opens in the browser."""
        if previewable(url, self.app.store.link_hosts):
            self.preview_further(url)
        elif links.parse(url, self.app.store.link_hosts).kind == "web":
            follow.open_in_browser(self.app, url)
        else:
            self.dismiss(url)

    @work
    async def preview_further(self, url: str) -> None:
        result = await self.app.preview_link(url, nested=True)
        if result is not None:  # followed or opened: the whole stack of previews goes
            self.dismiss(result)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_follow(self) -> None:
        self.dismiss(self.url)

    def action_open_in_browser(self) -> None:
        follow.open_in_browser(self.app, self.url)
        self.dismiss("")

    def action_copy_link(self) -> None:
        clipboard.copy(self.url, self.app.copy_to_clipboard)
        self.notify(self.url, title="Copied the link", markup=False)
