"""How models look on screen: one place, so every view shows a card the same way."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text

from tui_trello.models import Card, CardContext, Label
from tui_trello.ui.bidi import BidiText, visual


def label_chips(labels: tuple[Label, ...] | list[Label]) -> Text:
    text = Text()
    for label in labels:
        text.append_text(visual(Text(f" {label.name or ' '} ", style=f"bold black on {label.rich_colour}")))
        text.append(" ")
    return text


def label_dots(labels: tuple[Label, ...]) -> Text:
    """A compact form for narrow rows: one coloured block per label."""
    return Text.assemble(*(("▌", label.rich_colour) for label in labels))


def due_text(card: Card, now: datetime | None = None) -> Text:
    if card.due is None:
        return Text("")
    now = now or datetime.now(timezone.utc)
    days = (card.due.date() - now.date()).days
    if card.due_complete:
        return Text(f"✓ {card.due:%d %b}", style="green")
    if days < 0:
        return Text(f"! {card.due:%d %b}", style="bold red")
    if days <= 2:
        return Text(f"◷ {card.due:%d %b}", style="yellow")
    return Text(f"◷ {card.due:%d %b}", style="dim")


def badges(card: Card, now: datetime | None = None, *, due: bool = True) -> Text:
    parts = Text()
    if card.comment_count:
        parts.append(f"✎{card.comment_count} ", style="dim")
    checked, total = card.checklist
    if total:
        parts.append(f"☑{checked}/{total} ", style="green" if checked == total else "dim")
    if due:
        parts.append_text(due_text(card, now))
    return parts


def members_text(card: Card, context: CardContext) -> Text:
    initials = [visual(Text(context.members[m].initials, style="cyan")) for m in card.member_ids
                if m in context.members]
    return Text(" ", style="cyan").join(initials)


def card_block(card: Card, context: CardContext, now: datetime | None = None) -> BidiText:
    """A card summary for columns: the name (wrapped), then labels, badges and members."""
    block = Text(card.name, style="bold")
    meta = Text.assemble(label_dots(card.labels), " " if card.labels else "", badges(card, now), " ",
                         members_text(card, context))
    if meta.plain.strip():
        block.append("\n")
        block.append_text(meta)
    return BidiText(block)
