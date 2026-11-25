"""Arabic letters in their joined shapes, for the screenshots: `shape("مرحبا")`.

Terminals draw joined Arabic themselves, but an SVG screenshot holds one `<text>` element per character, and a letter
alone in its element is drawn in its isolated form. So the screenshot script turns each Arabic letter into the
character for the shape it takes in its word (Arabic Presentation Forms-B, U+FE70 to U+FEFF), one character for one,
with no ligatures: a lam before an alef stays two characters, each keeping its cell. The app never does this:
it leaves joining to the terminal (see "Known limitation" in the README for terminals that shape on their own).
"""

import unicodedata
from functools import cache

FIRST, LAST = "ء", "ي"  # the Arabic letters, hamza to yeh
TATWEEL = "ـ"  # the letter-stretching stroke: it joins both sides and is not drawn in another shape


@cache
def form(letter: str, which: str) -> str | None:
    """The presentation form of `letter` ("ISOLATED", "INITIAL", "MEDIAL" or "FINAL"), or None if it has none."""
    try:
        return unicodedata.lookup(f"{unicodedata.name(letter)} {which} FORM")
    except KeyError:
        return None


def is_letter(char: str) -> bool:
    return FIRST <= char <= LAST and char != TATWEEL


def joins_next(char: str) -> bool:
    """Whether `char` joins the letter after it: a letter with an initial form, or a tatweel."""
    return char == TATWEEL or (is_letter(char) and form(char, "INITIAL") is not None)


def joins_prev(char: str) -> bool:
    """Whether `char` can join the letter before it: a letter with a final form, or a tatweel."""
    return char == TATWEEL or (is_letter(char) and form(char, "FINAL") is not None)


def shape(text: str) -> str:
    """`text` with each Arabic letter in the shape its neighbours call for. Harakat (marks on a letter) are skipped
    over when looking for neighbours; every other character is left alone."""
    chars = list(text)
    letters = [i for i, c in enumerate(text) if unicodedata.category(c) != "Mn"]  # the characters that have neighbours
    for n, i in enumerate(letters):
        char = text[i]
        if not is_letter(char):
            continue
        before = joins_prev(char) and n > 0 and joins_next(text[letters[n - 1]])
        after = joins_next(char) and n + 1 < len(letters) and joins_prev(text[letters[n + 1]])
        which = ("MEDIAL" if before else "INITIAL") if after else ("FINAL" if before else "ISOLATED")
        chars[i] = form(char, which) or form(char, "ISOLATED") or char
    return "".join(chars)
