"""A card's details: header, description, attachments, checklists and comments. Used as the browser's preview pane and the card screen."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from tui_trello.backend import BackendError
from tui_trello.models import Attachment, Card, CardContext, Checklist
from tui_trello.ui import markdown, render
from tui_trello.ui.bidi import BidiText, visual
from tui_trello.ui.screens.picker import attachment_hint, attachment_marker


class CardView(VerticalScroll):
    DEFAULT_CSS = """
    CardView { padding: 0 1; }
    CardView #card-title { text-style: bold; color: $accent; margin-bottom: 1; }
    CardView #card-meta { margin-bottom: 1; }
    CardView .section { text-style: bold; color: $text-muted; border-bottom: solid $panel-lighten-2; }
    CardView #card-desc { margin-bottom: 1; }
    CardView #card-comments { margin-bottom: 1; min-height: 1; }
    CardView .checklists, CardView .attachments { display: none; }
    CardView .checklists.visible, CardView .attachments.visible { display: block; }
    CardView #card-attachments { margin-bottom: 1; }
    CardView #card-checklists { margin-bottom: 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.card: Card | None = None
        self.context: CardContext | None = None

    def on_mount(self) -> None:
        self.app.store.drafts_changed.subscribe(self, self.on_draft_changed)
        self.app.store.notifications_changed.subscribe(self, lambda _: self.on_notifications_changed())
        self.app.store.comments_changed.subscribe(self, self.on_comments_changed)

    def on_comments_changed(self, card_id: str) -> None:
        if self.card and self.card.id == card_id:
            self.load_comments(self.card)

    def on_notifications_changed(self) -> None:
        if self.card and self.context:
            self.show_meta(self.card, self.context)

    def on_draft_changed(self, card_id: str) -> None:
        if self.card and self.context and self.card.id == card_id:
            self.show_meta(self.card, self.context)

    def compose(self) -> ComposeResult:
        yield Static(id="card-title")
        yield Static(id="card-meta")
        yield Static("Description", classes="section")
        yield Static(id="card-desc")
        yield Static("Attachments", classes="section attachments")
        yield Static(id="card-attachments", classes="attachments")
        yield Static("Checklists", classes="section checklists")
        yield Static(id="card-checklists", classes="checklists")
        yield Static("Comments", classes="section")
        yield Static(id="card-comments")

    def show(self, card: Card | None, context: CardContext) -> None:
        self.card, self.context = card, context
        self.scroll_home(animate=False)
        if card is None:
            self.query_one("#card-title", Static).update(Text("No card selected", style="dim"))
            self.query_one("#card-meta", Static).update("")
            self.show_description("")
            self.show_attachments([])
            self.show_checklists([])
            self.query_one("#card-comments", Static).update("")
            return
        self.query_one("#card-title", Static).update(BidiText(card.name))
        self.show_meta(card, context)
        self.show_description(card.desc)
        self.query_one("#card-comments", Static).update("")  # the top bar's spinner shows comments loading
        self.load_comments(card)
        if card.attachment_count or self.app.store.has_attachments(card.id):
            self.load_attachments(card)
        else:
            self.show_attachments([])
        if card.checklist[1] or self.app.store.has_checklists(card.id):
            self.load_checklists(card)
        else:
            self.show_checklists([])

    def show_meta(self, card: Card, context: CardContext) -> None:
        meta = Text.assemble(
            ("in ", "dim"), visual(Text(context.location(card), style="bold")), "  ",
            render.badges(card, unread=self.app.store.unread_by_card()[card.id]), "\n",
        )
        names = [context.members[m].full_name for m in card.member_ids if m in context.members]
        if names:
            meta.append_text(Text.assemble(("👤 ", "dim"), Text(", ", style="cyan").join(
                visual(Text(name, style="cyan")) for name in names), "\n"))
        meta.append_text(render.label_chips(card.labels))
        drafts = {"comment": "c: unsent comment", "desc": "e: unsaved description"}
        for kind in self.app.store.drafts.kinds(card.id):
            meta.append_text(Text.assemble("\n", ("✐ draft", "bold yellow"), (f"  {drafts[kind]}", "yellow")))
        self.query_one("#card-meta", Static).update(meta)

    def show_description(self, desc: str) -> None:
        self.query_one("#card-desc", Static).update(
            markdown.render(desc) if desc.strip() else Text("No description.", style="dim italic"))

    def show_checklists(self, checklists: list[Checklist]) -> None:
        self.query(".checklists").set_class(bool(checklists), "visible")
        parts: list[RenderableType] = []
        for checklist in checklists:
            done = checklist.done == len(checklist.items) and checklist.items
            parts.append(BidiText(Text.assemble(
                markdown.inline(checklist.name, Style(bold=True)), "  ",
                (f"{checklist.done}/{len(checklist.items)}", "green" if done else "dim"))))
            for item in checklist.items:
                parts.append(BidiText(
                    Text.assemble(("☑ ", "green"), markdown.inline(item.name, Style(dim=True, strike=True)))
                    if item.checked else Text.assemble(("☐ ", "dim"), markdown.inline(item.name))))
            parts.append(Text(""))
        self.query_one("#card-checklists", Static).update(Group(*parts[:-1]))

    def show_attachments(self, attachments: list[Attachment]) -> None:
        self.query(".attachments").set_class(bool(attachments), "visible")
        rows = [Text.assemble(attachment_marker(a), visual(a.name), ("  " + attachment_hint(a), "dim"))
                for a in attachments]
        if rows:
            rows.append(Text("a: open, save or add", style="dim"))
        self.query_one("#card-attachments", Static).update(Group(*rows))

    @work(exclusive=True, group="attachments")
    async def load_attachments(self, card: Card) -> None:
        try:
            attachments = await self.app.store.attachments(card.id)
        except BackendError as exc:
            self.query(".attachments").add_class("visible")
            self.query_one("#card-attachments", Static).update(Text(str(exc), style="red"))
            return
        if self.card is not None and self.card.id == card.id:
            self.show_attachments(attachments)

    @work(exclusive=True, group="checklists")
    async def load_checklists(self, card: Card) -> None:
        try:
            checklists = await self.app.store.checklists(card.id)
        except BackendError as exc:
            self.query(".checklists").add_class("visible")
            self.query_one("#card-checklists", Static).update(Text(str(exc), style="red"))
            return
        if self.card is not None and self.card.id == card.id:
            self.show_checklists(checklists)

    @work(exclusive=True, group="comments")
    async def load_comments(self, card: Card, refresh: bool = False) -> None:
        try:
            comments = await self.app.store.comments(card.id, refresh=refresh)
            me_id = (await self.app.store.me()).id
        except BackendError as exc:
            comments_text = Text(str(exc), style="red")
        else:
            if self.card is None or self.card.id != card.id:
                return  # the user has moved on
            parts = []
            for comment in comments:
                when = f"{comment.date:%d %b %H:%M}" if comment.date else ""
                parts += [Text.assemble(("● ", "magenta"), visual(Text(comment.author, style="bold")), "  ",
                                        (when, "dim")), markdown.render(comment.text)]
                if counts := comment.reaction_counts(me_id):
                    parts.append(Text("  ").join(Text(f"{native} {n}", style="bold cyan" if mine else "dim")
                                                 for _, native, n, mine in counts))
                parts.append(Text(""))
            comments_text = Group(*parts) if parts else Text("No comments.", style="dim")
        self.query_one("#card-comments", Static).update(comments_text)
