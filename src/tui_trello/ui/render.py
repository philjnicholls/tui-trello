"""How models look on screen: one place, so every view shows a card the same way."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from rich.text import Text

from tui_trello.models import Card, CardContext, Label, Notification
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


def unread_badge(count: int) -> Text:
    """Unread notifications on a board, list or card, in the bell's colour; blank for none."""
    return Text(f"●{count}", style="bold yellow") if count else Text("")


def badges(card: Card, now: datetime | None = None, *, due: bool = True, unread: int = 0) -> Text:
    parts = Text()
    if unread:
        parts.append_text(unread_badge(unread))
        parts.append(" ")
    if card.comment_count:
        parts.append(f"✎{card.comment_count} ", style="dim")
    checked, total = card.checklist
    if total:
        parts.append(f"☑{checked}/{total} ", style="green" if checked == total else "dim")
    if card.attachment_count:
        parts.append(f"📎{card.attachment_count} ", style="dim")
    if due:
        parts.append_text(due_text(card, now))
    return parts


def members_text(card: Card, context: CardContext) -> Text:
    initials = [visual(Text(context.members[m].initials, style="cyan")) for m in card.member_ids
                if m in context.members]
    return Text(" ", style="cyan").join(initials)


def card_block(card: Card, context: CardContext, now: datetime | None = None, unread: int = 0) -> BidiText:
    """A card summary for columns: the name (wrapped), then labels, badges (`unread` notifications first) and
    members."""
    block = Text(card.name, style="bold")
    meta = Text.assemble(label_dots(card.labels), " " if card.labels else "", badges(card, now, unread=unread), " ",
                         members_text(card, context))
    if meta.plain.strip():
        block.append("\n")
        block.append_text(meta)
    return BidiText(block)


# What happened, by Trello notification type: "{who} <verb> <card>". The rest read as their type, split into words.
NOTIFICATION_VERBS = {
    "mentionedOnCard": "mentioned you on",
    "commentCard": "commented on",
    "addedToCard": "added you to",
    "removedFromCard": "removed you from",
    "changeCard": "moved",
    "createdCard": "created",
    "addedAttachmentToCard": "attached a file to",
    "updateCheckItemStateOnCard": "ticked an item on",
    "addedToBoard": "added you to the board",
    "addAdminToBoard": "made you an admin of the board",
    "invitedToBoard": "invited you to the board",
    "closeBoard": "closed the board",
    "addedToOrganization": "added you to a workspace",
}


def notification_summary(notification: Notification) -> str:
    """One line in plain words: "Grace Hopper mentioned you on Move cards between lists"."""
    n = notification
    if n.type == "cardDueSoon":
        return f"{n.card_name} is due soon"
    verb = NOTIFICATION_VERBS.get(n.type) or re.sub(r"(?<!^)(?=[A-Z])", " ", n.type).lower()
    subject = n.card_name if n.card_id else n.board_name
    line = " ".join(part for part in (n.creator or "Trello", verb, subject) if part)
    if n.type == "changeCard" and n.list_name:
        line += f" to {n.list_name}"
    return line


def ago(date: datetime | None, now: datetime | None = None) -> str:
    if date is None:
        return ""
    seconds = ((now or datetime.now(timezone.utc)) - date).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return "now"
