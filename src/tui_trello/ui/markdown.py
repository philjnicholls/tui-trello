"""Markdown, as Trello writes it in descriptions and comments, rendered as Rich renderables.

Textual's `Markdown` widget lays paragraphs out itself, so RTL text would come out in logical order. Here each block
becomes styled `Text` laid out by `BidiText`, which wraps and reorders RTL lines: Arabic and English get the same
styling. List markers and quote bars hang outside the text, and sit on the right of RTL items.

Supported: paragraphs and line breaks, **bold**, *italic*, ~~strikethrough~~, `code`, links (and bare URLs), @mentions,
headings, bullet and numbered lists (nested), block quotes, code blocks, rules, tables and images (shown by name),
emoji :shortcodes:.
`inline()` renders just the inline part, for one-line text such as checklist items. With `clickable`, links and
images carry a click action, `app.open_link(url)`, so a click on them is handled by the app.
`links()` lists the links and images of a text, in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from rich import box
from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from tui_trello.emoji import CACHE_LIMIT, with_emoji
from tui_trello.ui.bidi import BidiText, base_is_rtl, visual

# Trello turns single newlines into line breaks.
PARSER = MarkdownIt("commonmark", {"breaks": True, "linkify": True}).enable(["table", "strikethrough", "linkify"])

# An escaped colon stands in for itself as this character until the emoji are shown, so `\:tada:` stays literal.
ESCAPED_COLON = "\ue000"


def _protect_escaped_colons(state) -> None:
    """Core rule, before `text_join` merges the text: mark an escaped colon (`text_special`) so no shortcode forms."""
    def mark(tokens) -> None:
        for token in tokens:
            if token.type == "text_special" and token.markup == "\\:" and token.content == ":":
                token.content = ESCAPED_COLON
            if token.children:
                mark(token.children)

    mark(state.tokens)


PARSER.core.ruler.before("text_join", "escaped_colon", _protect_escaped_colons)

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


@dataclass(frozen=True)
class Link:
    text: str  # a link's text, an image's alt text; the URL for a bare URL
    url: str
    stored: str = field(default="", compare=False)  # the text as written (shortcodes unshown), for a picker to search


def render(source: str, *, clickable: bool = False, hyperlinks: bool = True) -> RenderableType:
    """The renderable for a Markdown description or comment. With `clickable`, a click on a link or image runs the
    app's `open_link` action. Without `hyperlinks`, links are drawn as styled text only, with no terminal hyperlink
    (OSC 8) hiding the target, which is shown in plain text after the link text: for text from outside, such as the
    news."""
    root = SyntaxTreeNode(PARSER.parse(source))
    return Group(*_spaced(_blocks(root.children, 0, clickable, hyperlinks)))


def inline(source: str, style: Style = Style(), *, clickable: bool = False) -> Text:
    """The styled text for one line of Markdown (a checklist or its item): code, emphasis, links and mentions, with
    no blocks, so "# 1" or "- x" stay as written."""
    root = SyntaxTreeNode(PARSER.parseInline(source))
    return _inline(root.children[0], style, clickable) if root.children else Text(source, style)


def links(source: str, *, one_line: bool = False) -> list[Link]:
    """The links and images in the Markdown, in the order they come; `one_line` for text that `inline()` draws."""
    root = SyntaxTreeNode(PARSER.parseInline(source) if one_line else PARSER.parse(source))
    found: list[Link] = []

    def walk(node: SyntaxTreeNode) -> None:
        if node.type in ("link", "image"):
            href = node.attrs.get("href" if node.type == "link" else "src")
            if href:
                found.append(Link(_plain(node) or str(href), str(href), _stored(node)))
        for child in node.children:
            if node.type != "image":  # an image's children are its alt text
                walk(child)

    walk(root)
    return found


def plain(source: str, limit: int = 1000) -> str:
    """One line of Markdown source as plain text, the way the card view shows it: emoji, escapes and code resolved.
    A source over `limit` characters is cut first (at a space or line break if there is one near, with "…"), as the
    text is meant to be short (a notification or the start of a comment). Short sources are cached: notifications
    are drawn again on every resize."""
    if len(source) > limit:
        cut_at = max(source.rfind(" ", 0, limit), source.rfind("\n", 0, limit))
        source = source[:cut_at if cut_at > limit // 2 else limit].rstrip() + "…"
        return inline(source).plain
    return _plain_short(source) if len(source) <= CACHE_LIMIT else inline(source).plain


@lru_cache(maxsize=512)
def _plain_short(source: str) -> str:
    return inline(source).plain


def _spaced(blocks: list[RenderableType]) -> list[RenderableType]:
    """Top-level blocks with a blank line between them."""
    spaced: list[RenderableType] = []
    for n, block in enumerate(blocks):
        if n:
            spaced.append(Text(""))
        spaced.append(block)
    return spaced


def _blocks(nodes: list[SyntaxTreeNode], depth: int, clickable: bool = False,
            hyperlinks: bool = True) -> list[RenderableType]:
    blocks: list[RenderableType] = []
    for node in nodes:
        if node.type == "paragraph":
            blocks.append(BidiText(_inline(node.children[0], clickable=clickable, hyperlinks=hyperlinks)))
        elif node.type == "heading":
            style = HEADINGS.get(int(node.tag[1:]), Style(bold=True))
            blocks.append(BidiText(_inline(node.children[0], style, clickable, hyperlinks)))
        elif node.type in ("bullet_list", "ordered_list"):
            blocks.append(_list(node, depth, clickable, hyperlinks))
        elif node.type == "blockquote":
            quoted = Group(*_blocks(node.children, depth, clickable, hyperlinks))
            blocks.append(_hanging(Text(QUOTE, MUTED), quoted, _plain(node), style=MUTED))
        elif node.type in ("fence", "code_block"):
            blocks.append(_hanging(Text(CODE_BAR, MUTED), Text(node.content.rstrip("\n"), CODE), ""))
        elif node.type == "hr":
            blocks.append(Rule(style=MUTED))
        elif node.type == "table":
            blocks.append(_table(node, clickable, hyperlinks))
        elif node.type == "html_block":
            blocks.append(BidiText(Text(node.content.rstrip("\n"))))
        elif node.children:
            blocks.extend(_blocks(node.children, depth, clickable, hyperlinks))
    return blocks


def _list(node: SyntaxTreeNode, depth: int, clickable: bool, hyperlinks: bool) -> RenderableType:
    start = int(node.attrs.get("start", 1))
    items = []
    for n, item in enumerate(node.children):
        marker = f"{start + n}. " if node.type == "ordered_list" else BULLETS[depth % len(BULLETS)]
        body = Group(*_blocks(item.children, depth + 1, clickable, hyperlinks))
        items.append(_hanging(Text(marker, MUTED), body, _plain(item)))
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


def _table(node: SyntaxTreeNode, clickable: bool, hyperlinks: bool) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style=Style(bold=True))
    head, *bodies = node.children
    for cell in head.children[0].children:
        table.add_column(_cell(cell, clickable, hyperlinks))
    for body in bodies:
        for row in body.children:
            table.add_row(*(_cell(cell, clickable, hyperlinks) for cell in row.children))
    return table


def _cell(cell: SyntaxTreeNode, clickable: bool, hyperlinks: bool) -> BidiText:
    if not cell.children:
        return BidiText(Text(""))
    return BidiText(_inline(cell.children[0], clickable=clickable, hyperlinks=hyperlinks))


def _inline(node: SyntaxTreeNode, style: Style = Style(), clickable: bool = False, hyperlinks: bool = True) -> Text:
    text = Text()
    for child in node.children:
        if child.type == "text":
            bare_url = node.type == "link" and node.markup in ("linkify", "autolink")
            _append_mentions(text, _shown(child.content, emoji=not bare_url), style)
        elif child.type in ("softbreak", "hardbreak"):
            text.append("\n")
        elif child.type == "code_inline":
            text.append(child.content, style + CODE)
        elif child.type in INLINE:
            text.append_text(_inline(child, style + INLINE[child.type], clickable, hyperlinks))
        elif child.type == "link":
            href = child.attrs.get("href")
            hyperlink = Style(link=str(href) if href else None) if hyperlinks else Style()
            text.append_text(_inline(child, style + LINK + hyperlink
                                     + (_click(href) if clickable else Style()), clickable, hyperlinks))
            if href and not hyperlinks and child.markup not in ("linkify", "autolink"):
                text.append(f" ({href})", style)  # no hyperlink to hide the target in: show it
        elif child.type == "image":
            src = child.attrs.get("src", "")
            alt = _plain(child) or str(src)
            text.append(f"[image: {alt}]", style + MUTED + (LINK + _click(src) if clickable and src else Style()))
        elif child.children:
            text.append_text(_inline(child, style, clickable, hyperlinks))
        else:
            text.append(child.content, style)
    return text


def _click(href: object) -> Style:
    """The style that makes text run `App.action_open_link(href)` when clicked."""
    return Style(meta={"@click": ("app.open_link", (str(href),))}) if href else Style()


def _shown(content: str, emoji: bool = True) -> str:
    """Text content as drawn: shortcodes as emoji (unless `emoji` is off), escaped colons as colons."""
    return (with_emoji(content) if emoji else content).replace(ESCAPED_COLON, ":")


def _append_mentions(text: Text, content: str, style: Style) -> None:
    position = 0
    for match in MENTION_PATTERN.finditer(content):
        text.append(content[position:match.start()], style)
        text.append(match.group(), style + MENTION)
        position = match.end()
    text.append(content[position:], style)


def _runs(node: SyntaxTreeNode, literal: bool = False) -> list[tuple[str, bool]]:
    """The node's text as (text, literal) runs: text and escapes, which are shown as emoji, and code and line breaks
    (a space), which are kept as they are. Under a bare URL nothing is shown as emoji."""
    if node.type in ("text", "text_special"):
        return [(node.content, literal)]
    if node.type == "code_inline":
        return [(node.content, True)]
    if node.type in ("softbreak", "hardbreak"):
        return [(" ", True)]
    literal = literal or (node.type == "link" and node.markup in ("linkify", "autolink"))
    return [run for child in node.children for run in _runs(child, literal)]


def _plain(node: SyntaxTreeNode) -> str:
    """The node's text as displayed (emoji shown, code untouched). Text runs are joined before the emoji are
    found, so `:white\\_check\\_mark:` (three runs) forms one."""
    out: list[str] = []
    pending = ""
    for text, literal in _runs(node):
        if literal:
            out += [_shown(pending), text]
            pending = ""
        else:
            pending += text
    out.append(_shown(pending))
    return "".join(out)


def _stored(node: SyntaxTreeNode) -> str:
    """The node's text as written: `_plain` without the emoji."""
    return "".join(text for text, _ in _runs(node)).replace(ESCAPED_COLON, ":")
