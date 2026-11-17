"""Markdown, as Trello writes it in descriptions and comments, rendered as Rich renderables.

Textual's `Markdown` widget lays paragraphs out itself, so RTL text would come out in logical order. Here each block
becomes styled `Text` laid out by `BidiText`, which wraps and reorders RTL lines: Arabic and English get the same
styling. List markers and quote bars hang outside the text, and sit on the right of RTL items.

Supported: paragraphs and line breaks, **bold**, *italic*, ~~strikethrough~~, `code`, links (and bare URLs), @mentions,
headings, bullet and numbered lists (nested), block quotes, code blocks, rules, tables and images (shown by name).
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from rich import box
from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from tui_trello.ui.bidi import BidiText, base_is_rtl, visual

# Trello turns single newlines into line breaks.
PARSER = MarkdownIt("commonmark", {"breaks": True, "linkify": True}).enable(["table", "strikethrough", "linkify"])

INLINE = {"strong": Style(bold=True), "em": Style(italic=True), "s": Style(strike=True)}
CODE = Style(color="magenta")
LINK = Style(color="bright_blue", underline=True)
MENTION = Style(color="cyan", bold=True)
MUTED = Style(dim=True)
HEADINGS = {1: Style(bold=True, underline=True), 2: Style(bold=True), 3: Style(bold=True, italic=True)}
BULLETS = ("• ", "◦ ", "▪ ")
QUOTE = "▌ "
CODE_BAR = "│ "

MENTION_PATTERN = re.compile(r"(?<![\w@])@[\w.\-]+")


def render(source: str) -> RenderableType:
    """The renderable for a Markdown description or comment."""
    root = SyntaxTreeNode(PARSER.parse(source))
    return Group(*_spaced(_blocks(root.children, depth=0)))


def _spaced(blocks: list[RenderableType]) -> list[RenderableType]:
    """Top-level blocks with a blank line between them."""
    spaced: list[RenderableType] = []
    for n, block in enumerate(blocks):
        if n:
            spaced.append(Text(""))
        spaced.append(block)
    return spaced


def _blocks(nodes: list[SyntaxTreeNode], depth: int) -> list[RenderableType]:
    blocks: list[RenderableType] = []
    for node in nodes:
        if node.type == "paragraph":
            blocks.append(BidiText(_inline(node.children[0])))
        elif node.type == "heading":
            style = HEADINGS.get(int(node.tag[1:]), Style(bold=True))
            blocks.append(BidiText(_inline(node.children[0], style)))
        elif node.type in ("bullet_list", "ordered_list"):
            blocks.append(_list(node, depth))
        elif node.type == "blockquote":
            blocks.append(_hanging(Text(QUOTE, MUTED), Group(*_blocks(node.children, depth)), _plain(node),
                                   style=MUTED))
        elif node.type in ("fence", "code_block"):
            blocks.append(_hanging(Text(CODE_BAR, MUTED), Text(node.content.rstrip("\n"), CODE), ""))
        elif node.type == "hr":
            blocks.append(Rule(style=MUTED))
        elif node.type == "table":
            blocks.append(_table(node))
        elif node.type == "html_block":
            blocks.append(BidiText(Text(node.content.rstrip("\n"))))
        elif node.children:
            blocks.extend(_blocks(node.children, depth))
    return blocks


def _list(node: SyntaxTreeNode, depth: int) -> RenderableType:
    start = int(node.attrs.get("start", 1))
    items = []
    for n, item in enumerate(node.children):
        marker = f"{start + n}. " if node.type == "ordered_list" else BULLETS[depth % len(BULLETS)]
        items.append(_hanging(Text(marker, MUTED), Group(*_blocks(item.children, depth + 1)), _plain(item)))
    return Group(*items)


def _hanging(marker: Text, body: RenderableType, plain: str, style: Style | None = None) -> Table:
    """`body` with `marker` beside its first line and the space under the marker left empty; the marker goes on the
    right when the body reads right to left."""
    grid = Table.grid(expand=True)
    rtl = base_is_rtl(plain)
    if rtl:  # "1. " reads ".1" from the right, with the gap on the text's side
        marker = Text.assemble(" ", visual(Text(marker.plain.rstrip(), marker.style), rtl=True))
    columns = [(marker, {"width": marker.cell_len, "no_wrap": True}), (body, {"ratio": 1})]
    if rtl:
        columns.reverse()
    for _, options in columns:
        grid.add_column(**options)
    grid.add_row(*(cell for cell, _ in columns), style=style)
    return grid


def _table(node: SyntaxTreeNode) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style=Style(bold=True))
    head, *bodies = node.children
    for cell in head.children[0].children:
        table.add_column(_cell(cell))
    for body in bodies:
        for row in body.children:
            table.add_row(*(_cell(cell) for cell in row.children))
    return table


def _cell(cell: SyntaxTreeNode) -> BidiText:
    return BidiText(_inline(cell.children[0]) if cell.children else Text(""))


def _inline(node: SyntaxTreeNode, style: Style = Style()) -> Text:
    text = Text()
    for child in node.children:
        if child.type == "text":
            _append_mentions(text, child.content, style)
        elif child.type in ("softbreak", "hardbreak"):
            text.append("\n")
        elif child.type == "code_inline":
            text.append(child.content, style + CODE)
        elif child.type in INLINE:
            text.append_text(_inline(child, style + INLINE[child.type]))
        elif child.type == "link":
            href = child.attrs.get("href")
            text.append_text(_inline(child, style + LINK + Style(link=str(href) if href else None)))
        elif child.type == "image":
            alt = _plain(child) or str(child.attrs.get("src", ""))
            text.append(f"[image: {alt}]", style + MUTED)
        elif child.children:
            text.append_text(_inline(child, style))
        else:
            text.append(child.content, style)
    return text


def _append_mentions(text: Text, content: str, style: Style) -> None:
    position = 0
    for match in MENTION_PATTERN.finditer(content):
        text.append(content[position:match.start()], style)
        text.append(match.group(), style + MENTION)
        position = match.end()
    text.append(content[position:], style)


def _plain(node: SyntaxTreeNode) -> str:
    """The node's text, to tell which way it reads."""
    if node.type in ("text", "code_inline"):
        return node.content
    return "".join(_plain(child) for child in node.children)
