"""Replies: the part of a comment a reply quotes, cut to a size a reply can carry.

Trello has no threads. A reply is a new comment that starts with the comment it answers as a Markdown block quote
and @mentions its author, so they're notified. A comment too long to quote whole is cut at a word, or the user picks
one of its paragraphs (or, in a single paragraph, its lines or sentences) instead.
"""

from __future__ import annotations

import re

LIMIT = 280  # characters of quoted text
LINES = 6

QUOTED = re.compile(r"^\s*>")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def own_text(text: str) -> str:
    """The comment without the lines it quotes from an earlier one, so quotes don't pile up reply after reply. If
    it is all quote, all of it."""
    own = "\n".join(line for line in text.splitlines() if not QUOTED.match(line)).strip()
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", own) or text.strip()


def fits(text: str) -> bool:
    return len(text) <= LIMIT and len(text.splitlines()) <= LINES


def shorten(text: str) -> str:
    """The text, or its start cut at a word with "…" after it."""
    if fits(text):
        return text
    cut = "\n".join(text.splitlines()[:LINES])[:LIMIT]
    if (space := cut.rfind(" ")) > LIMIT // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-\n") + "…"


def parts(text: str) -> list[str]:
    """The pieces of a long comment a reply can quote instead of its start: its paragraphs; in a single paragraph,
    its lines, else its sentences. Each is shortened."""
    pieces = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(pieces) == 1:
        pieces = [line.strip() for line in text.splitlines() if line.strip()]
    if len(pieces) == 1:
        pieces = [s for s in SENTENCE_END.split(text.strip()) if s]
    return list(dict.fromkeys(shorten(p) for p in pieces))


def reply(quoted: str, username: str) -> str:
    """The start of a reply: `quoted` as a block quote, then a mention of its author for the cursor to follow."""
    block = "\n".join(f"> {line}".rstrip() for line in quoted.splitlines())
    return f"{block}\n\n@{username} " if username else f"{block}\n\n"
