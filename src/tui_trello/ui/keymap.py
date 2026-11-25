"""The keys of the app, and the `[keys]` table of config.toml that changes them.

Every `Binding` in the app has an *id* of the form `group.name` (`card.archive`). `[keys]` maps ids to keys; the
:class:`KeyMap` built from it is handed to Textual's `App.set_keymap`, which swaps the keys of every binding with
that id, on every screen and popup, and the footer shows them. Two-key sequences (`gg`) are the app's own, so their
overrides are handled here. Strings that name a key (the `?` help, tips, hints) are written with `{id}` placeholders
and filled by :meth:`KeyMap.fill`, so they show the key in use.

An override is checked against the bindings that are live together in each place (a *context*: a view with the app's
keys, or a popup). One that is not a key, or that another action already holds in a place where both apply, is
skipped with a warning; the id keeps its default.
"""

from __future__ import annotations

import difflib
import functools
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from textual.binding import Binding
from textual.keys import KEY_NAME_REPLACEMENTS, Keys, format_key

# id -> (sequence, action, what it does). A chord is two keys, one after the other.
CHORD_DEFAULTS = {
    "chord.top": ("gg", "motion('top')", "First"),
    "chord.next_view": ("gt", "cycle_mode(1)", "Next view"),
    "chord.previous_view": ("gT", "cycle_mode(-1)", "Previous view"),
}

# What each id does, for `tui-trello keys` and the README (a binding's own description is what the footer says).
WHAT = {
    "app.browser": "Go to the browser view", "app.triage": "Go to the triage view", "app.mywork": "Go to my work",
    "app.notifications": "Go to notifications", "app.boards": "Pick a board", "app.refresh": "Reload from Trello",
    "app.done_items": "Show or hide ticked checklist items", "app.down": "Move down (any list, table or pane)",
    "app.up": "Move up", "app.bottom": "Jump to the last row", "app.top": "Jump to the first row",
    "app.half_down": "Half a page down", "app.half_up": "Half a page up", "app.commands": "Command palette",
    "app.help": "Show or close the key help", "app.search": "Search every board on Trello",
    "app.news": "Show or close the news about tui-trello", "app.quit": "Quit",
    "chord.top": "Jump to the first row", "chord.next_view": "Go to the next view",
    "chord.previous_view": "Go to the previous view",
    "card.move": "Move the card to another list", "card.comment": "Write a comment",
    "card.description": "Edit the description", "card.labels": "Put labels on the card or take them off",
    "card.checklist": "Tick checklist items, add items", "card.attachments": "Attachments: open, add",
    "card.reply": "Reply to a comment", "card.react": "React to a comment", "card.copy_link": "Copy the card's link",
    "card.copy_comment_link": "Copy the link to a comment", "card.open": "Open the card in the web browser",
    "card.follow_link": "Follow a link on the card", "card.archive": "Archive the card (asks first)",
    "card.delete": "Delete the card for good (asks first)", "card.edit_comment": "Edit one of your comments",
    "card.delete_comment": "Delete one of your comments (asks first)",
    "list.filter": "Filter the cards on screen", "list.clear_filter": "Clear the filter",
    "list.new_card": "Make a new card", "list.open": "Open the card", "board.copy_link": "Copy the board's link",
    "browser.in": "Into the cards; open a card", "browser.out": "Back to the lists", "triage.sort": "Cycle the sort",
    "mywork.preview": "Show or hide the preview", "card_screen.back": "Close the card",
    "notifications.mark_read": "Mark the notification read",
    "notifications.mark_all_read": "Mark every notification read",
    "notifications.toggle_read": "Hide or show the ones you've read", "help.close": "Close the key help",
    "news.close": "Close the news", "help.all": "Every key, or just this view's",
    "preview.close": "Close the link preview",
    "preview.follow": "Follow the link", "popup.open_in_browser": "Open the link in the web browser",
    "popup.copy_link": "Copy the link", "popup.preview": "Preview the highlighted link or result",
    "picker.close": "Close the popup", "picker.down": "Next row", "picker.up": "Previous row",
    "attachments.save": "Say how to save the file (open it in the browser)",
    "editor.cancel": "Close the editor (a draft is kept)",
    "editor.enter": "Send (a new line in a description)", "editor.save": "Save", "editor.mention": "Pick the @mention",
    "editor.mention_down": "Next @mention", "editor.mention_up": "Previous @mention",
    "editor.newline": "Start a new line", "editor.attach": "Attach a file", "confirm.yes": "Confirm",
    "confirm.no": "Cancel",
}

# group -> the heading `tui-trello keys` and the README give it, in the order they are listed.
GROUPS = {
    "app": "everywhere",
    "chord": "two-key sequences, everywhere (two characters, such as \"g t\")",
    "card": "on a card: the browser, triage, my work and the card screen",
    "list": "lists of cards: the browser, triage and my work",
    "board": "the open board: the browser and triage",
    "browser": "the browser's columns",
    "triage": "the triage table",
    "mywork": "my work",
    "card_screen": "the full-screen card",
    "notifications": "the notifications view",
    "help": "the key help",
    "news": "the news popup",
    "preview": "the link preview popup",
    "popup": "popups that share a verb: links, search, preview",
    "picker": "every list popup",
    "attachments": "the attachments popup",
    "editor": "the comment and description editor",
    "confirm": "the confirmation popup",
}

MODIFIERS = ("ctrl", "alt", "shift", "meta", "super")
# Every named key Textual knows (its `Keys` enum), less the internal ones and the plain-character name `space`.
NAMED_KEYS = frozenset(key.value for key in Keys if "+" not in key.value and not key.value.startswith(("<", "ctrl-"))
                       and key.value not in ("space", "return"))
PLACEHOLDER = re.compile(r"\{([a-z_]+\.[a-z_]+)(:all)?\}")
ID_FORM = re.compile(r"[a-z_]+\.[a-z_]+\Z")


def normalise_key(key: str) -> str:
    """The key in Textual's normal form, as `App.set_keymap` writes it: a character becomes its name (`?` is
    `question_mark`), after the modifiers too (`ctrl+/` is `ctrl+slash`, which Textual leaves as written), and
    `shift+a` is `A`, which is what Textual receives for Shift+A."""
    modifiers, base = split_key(key.strip())
    modifiers = [m.lower() for m in modifiers]
    if base.lower() == "esc":  # what the help and footer call it
        base = "escape"
    if len(base) == 1:
        if modifiers == ["shift"] and base.isalpha():
            return base.upper()
        base = character_name(base)
    elif base.lower() in NAMED_KEYS | CHARACTER_NAMES:
        base = base.lower()
    return "+".join([*modifiers, base])


def split_key(key: str) -> tuple[list[str], str]:
    """`"ctrl+a"` as (["ctrl"], "a"); a `+` as the key itself is `"+"` or `"ctrl++"`."""
    if key == "+":
        return [], "+"
    if key.endswith("++"):
        return key[:-2].split("+"), "+"
    *modifiers, base = key.split("+")
    return modifiers, base


def character_name(character: str) -> str:
    """Textual's name for a character: itself if a letter or digit, else its Unicode name (`?` is `question_mark`)."""
    if character.isalnum():
        return character
    try:
        name = unicodedata.name(character).lower().replace("-", "_").replace(" ", "_")
    except ValueError:
        name = "tab" if character == "\t" else character
    return KEY_NAME_REPLACEMENTS.get(name, name)


# The names of the printable ASCII characters (`slash`, `question_mark`, `comma`), which a key can be written as.
CHARACTER_NAMES = frozenset(character_name(chr(code)) for code in range(33, 127)) | {"space"}


def is_printable(key: str) -> bool:
    """Whether a text box would type this (normalised) key: a letter, digit, symbol or space, with no modifier."""
    return len(key) == 1 or key in CHARACTER_NAMES


def parse_key(key: str) -> str:
    """One key as written in config.toml, normalised. Raises ValueError, with what is wrong, if it is not one."""
    if not key.strip():
        raise ValueError("an empty key")
    modifiers, base = split_key(key.strip())
    for modifier in modifiers:
        if modifier.lower() not in MODIFIERS:
            raise ValueError(f"{modifier!r} is not a modifier (ctrl, alt, shift, meta, super)")
    if not base:
        raise ValueError(f"{key!r} has no key after the +")
    if len(base) > 1 and base.lower() not in NAMED_KEYS | CHARACTER_NAMES | {"esc"}:
        raise ValueError(f"{base!r} is not a key name Textual knows")
    return normalise_key(key)


def parse_value(value: object) -> list[str]:
    """The keys a `[keys]` value gives, normalised, with no repeats. Raises ValueError, with what is wrong."""
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise ValueError("must be a key, or a list of keys, as text")
    keys: list[str] = []
    for item in items:
        if not item.strip():
            raise ValueError("is empty")
        for key in ["comma"] if item.strip() == "," else item.split(","):
            if (parsed := parse_key(key)) not in keys:
                keys.append(parsed)
    if not keys or not items:
        raise ValueError("is empty")
    return keys


def parse_chord(value: object) -> str:
    """A chord's sequence, from "g t" or "gt": two characters. Raises ValueError, with what is wrong."""
    if not isinstance(value, str):
        raise ValueError('must be two characters as text, such as "g t"')
    sequence = "".join(value.split())
    if len(sequence) != 2:
        raise ValueError('must be two characters, such as "g t"')
    return sequence


def display(key: str) -> str:
    """A normalised key as the app writes it for the user: the character for a printable key (`?`, `/`), `esc` for
    escape, a chord written together (`gg`), anything else as it is (`ctrl+o`, `pagedown`)."""
    modifiers, base = split_key(key)
    if base == "escape":
        shown = "esc"
    elif base in NAMED_KEYS or len(base) == 1 or base == "space":
        shown = base
    else:
        shown = format_key(base)
    return "+".join([*modifiers, shown])


def written_key(key: str) -> str:
    """The key as config.toml takes it: a character as itself, a name as the name (`escape`, not `esc`)."""
    _, base = split_key(key)
    if base in NAMED_KEYS or base in ("space", "comma", "quotation_mark", "backslash"):
        return key
    return display(key)


def listing(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def show_value(value: object) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value).replace("'", '"')


@dataclass
class Context:
    """One place where a set of bindings is live together."""

    name: str  # for warnings: "the browser", "the links popup"
    bindings: list[Binding]
    fixed: list[tuple[str, str]] = field(default_factory=list)  # (key, what it does) of widgets: not changeable
    text_box: bool = False  # a text box has the focus, so it types every printable key
    chords: bool = False  # the chord handler is live: the first key of a chord is swallowed


@dataclass
class Entry:
    """A key id: its default keys, what it does and where."""

    id: str
    keys: list[str]
    description: str
    where: list[str] = field(default_factory=list)

    @property
    def group(self) -> str:
        return self.id.partition(".")[0]


def class_bindings(cls: type) -> list[Binding]:
    """The bindings of a class and of the classes it inherits from, as Textual collects them (nearest first)."""
    found: list[Binding] = []
    for klass in cls.__mro__:
        if "BINDINGS" in vars(klass):
            found += Binding.make_bindings(vars(klass)["BINDINGS"])
    return found


def widget_keys(classes: Iterable[type]) -> list[tuple[str, str]]:
    return [(normalise_key(b.key), b.description or b.action) for cls in classes for b in class_bindings(cls)]


@functools.cache
def contexts() -> list[Context]:
    """Every place the app's bindings are live, built from the screens themselves. Imports the UI here, so that
    `ui.app` can import this module."""
    from tui_trello.ui.app import TrelloApp
    from tui_trello.ui.screens.browser import BrowserScreen
    from tui_trello.ui.screens.card import CardScreen
    from tui_trello.ui.screens.keys import KeysScreen
    from tui_trello.ui.screens.mywork import MyWorkScreen
    from tui_trello.ui.screens.news import NewsScreen
    from tui_trello.ui.screens.notifications import NotificationsScreen
    from tui_trello.ui.screens.picker import ConfirmScreen, PickerScreen, TextPromptScreen
    from tui_trello.ui.screens.preview import LinkPreviewScreen
    from tui_trello.ui.screens.triage import TriageScreen

    found = []
    app_bindings = class_bindings(TrelloApp)
    for name, cls in [("the browser", BrowserScreen), ("triage", TriageScreen), ("my work", MyWorkScreen),
                      ("notifications", NotificationsScreen), ("the card screen", CardScreen)]:
        found.append(Context(name, app_bindings + class_bindings(cls), widget_keys(cls.FOCUS_WIDGETS), chords=True))
    # The app's bindings stop at a modal screen, but the chord handler runs before bindings.
    for name, cls in [("the link preview", LinkPreviewScreen), ("the key help", KeysScreen),
                      ("the news", NewsScreen), ("the confirmation popup", ConfirmScreen)]:
        found.append(Context(name, class_bindings(cls), widget_keys(getattr(cls, "FOCUS_WIDGETS", ())), chords=True))
    # The chord handler skips text boxes. A picker that adds no bindings is the same as `PickerScreen`.
    pickers = [PickerScreen]
    todo = list(PickerScreen.__subclasses__())
    while todo:
        cls = todo.pop(0)
        todo += cls.__subclasses__()
        if "BINDINGS" in vars(cls):
            pickers.append(cls)
    for cls in pickers:
        found.append(Context(POPUP_NAMES.get(cls.__name__, f"the {cls.__name__} popup"), class_bindings(cls),
                             widget_keys(cls.FOCUS_WIDGETS), text_box=True))
    found.append(Context("the editor", class_bindings(TextPromptScreen), widget_keys(TextPromptScreen.FOCUS_WIDGETS),
                         text_box=True))
    return found


POPUP_NAMES = {"PickerScreen": "the list popups", "LinkPickerScreen": "the links popup",
               "AttachmentPickerScreen": "the attachments popup", "SearchScreen": "the search popup"}


def catalogue(places: list[Context]) -> dict[str, Entry]:
    """Every id with its default keys, what it does and the places it works, in the order a listing shows them: by
    group, then as found."""
    found: dict[str, Entry] = {}
    for place in places:
        keys: dict[str, list[str]] = {}
        for binding in place.bindings:
            if binding.id:
                if (key := normalise_key(binding.key)) not in keys.setdefault(binding.id, []):
                    keys[binding.id].append(key)
                found.setdefault(binding.id, Entry(binding.id, keys[binding.id],
                                                   WHAT.get(binding.id) or binding.description))
        for binding_id in keys:
            if place.name not in found[binding_id].where:
                found[binding_id].where.append(place.name)
        if place.chords:
            for chord_id in CHORD_DEFAULTS:
                entry = found.setdefault(chord_id, Entry(chord_id, [CHORD_DEFAULTS[chord_id][0]],
                                                         WHAT.get(chord_id) or CHORD_DEFAULTS[chord_id][2]))
                if place.name not in entry.where:
                    entry.where.append(place.name)
    order = {group: n for n, group in enumerate(GROUPS)}
    return dict(sorted(found.items(), key=lambda item: order.get(item[1].group, len(order))))


class KeyMap:
    """The keys in use: `[keys]` checked against the bindings, as Textual's keymap, the chords, and what to show."""

    def __init__(self, entries: dict[str, Entry], places: list[Context]) -> None:
        self.entries = entries
        self.places = places
        self.effective: dict[str, list[str]] = {i: list(e.keys) for i, e in entries.items()}
        self.overridden: set[str] = set()
        self.warnings: list[str] = []

    @classmethod
    @functools.cache
    def default(cls) -> KeyMap:
        return cls.build({})

    @classmethod
    def build(cls, raw: dict[str, object], places: list[Context] | None = None) -> KeyMap:
        places = contexts() if places is None else places
        keymap = cls(catalogue(places), places)
        candidates = keymap.parse(raw)
        keymap.drop_clashes(candidates, places, raw)
        for key_id, keys in candidates.items():
            keymap.effective[key_id] = keys
            keymap.overridden.add(key_id)
        return keymap

    # -- checking ---------------------------------------------------------------------------------------------------

    def parse(self, raw: dict[str, object]) -> dict[str, list[str]]:
        """The entries that are keys for ids that exist, by id; a warning for each that is not."""
        found: dict[str, list[str]] = {}
        for key_id, value in raw.items():
            if key_id not in self.entries:
                near = difflib.get_close_matches(key_id, self.entries, n=1)
                hint = f"; did you mean `{near[0]}`?" if near else "; `tui-trello keys` lists the ids"
                self.warnings.append(f"[keys] {key_id}: not a key id{hint}")
                continue
            try:
                keys = [parse_chord(value)] if key_id in CHORD_DEFAULTS else parse_value(value)
            except ValueError as exc:
                self.warnings.append(f"[keys] {key_id} = {show_value(value)}: {exc}; {self.keeps(key_id)}")
                continue
            if key_id not in CHORD_DEFAULTS and (typed := self.typed_in_popup(key_id, keys)):
                self.warnings.append(f"[keys] {key_id} = {show_value(value)}: {typed} would be typed in the text "
                                     f"box; {self.keeps(key_id)}")
                continue
            found[key_id] = keys
        return found

    def keeps(self, key_id: str) -> str:
        return f"{key_id} keeps {' and '.join(display(k) for k in self.entries[key_id].keys)}"

    def typed_in_popup(self, key_id: str, keys: list[str]) -> str:
        """The printable keys, if the id works in a popup with a text box, which would type them."""
        if not any(place.text_box and any(b.id == key_id for b in place.bindings) for place in self.places):
            return ""
        return ", ".join(display(k) for k in keys if is_printable(k))

    def holders(self, place: Context, candidates: dict[str, list[str]]) -> dict[str, list[tuple[str | None, str]]]:
        """The keys in use in the place, each with who holds it: (id, what it does), the id None for a key that
        can't be changed."""
        held: dict[str, list[tuple[str | None, str]]] = {}
        seen: set[str] = set()
        for binding in place.bindings:
            if binding.id is None:
                held.setdefault(normalise_key(binding.key), []).append((None, binding.description or binding.action))
            elif binding.id not in seen:
                seen.add(binding.id)
                for key in candidates.get(binding.id) or self.entries[binding.id].keys:
                    held.setdefault(key, []).append((binding.id, self.entries[binding.id].description))
        for key, what in place.fixed:
            held.setdefault(key, []).append((None, what))
        if place.chords:
            for chord_id in CHORD_DEFAULTS:
                sequence = (candidates.get(chord_id) or self.entries[chord_id].keys)[0]
                held.setdefault(normalise_key(sequence[0]), []).append((chord_id, self.entries[chord_id].description))
        return held

    def drop_clashes(self, candidates: dict[str, list[str]], places: list[Context], raw: dict[str, object]) -> None:
        """Drop each override that takes a key another action holds where both work: one against a default, or
        against an override earlier in the file. Dropping gives back the id's default, which another override may
        clash with, so look again until none is left."""
        order = {key_id: n for n, key_id in enumerate(raw)}
        while True:
            for key_id in list(candidates):
                if message := self.clash(key_id, candidates, places, order):
                    del candidates[key_id]
                    self.warnings.append(f"[keys] {key_id} = {show_value(raw[key_id])}: {message}; "
                                         f"{self.keeps(key_id)}")
                    break
            else:
                return

    def clash(self, key_id: str, candidates: dict[str, list[str]], places: list[Context],
              order: dict[str, int]) -> str:
        """What the id's override clashes with, if it does: "<key> already does "<what>" (<id>) in <places>"."""
        mine = key_id in CHORD_DEFAULTS
        found: dict[tuple[str, str | None, str], list[str]] = {}
        for place in places:
            held = self.holders(place, candidates)
            if mine and not place.chords:
                continue
            if not mine and not any(b.id == key_id for b in place.bindings):
                continue
            # Only keys the id doesn't have already can clash with something.
            new = [normalise_key(candidates[key_id][0][0])] if mine else [
                key for key in candidates[key_id] if key not in self.entries[key_id].keys]
            for key in new:
                for other, what in held.get(key, ()):
                    if other == key_id or (mine and other in CHORD_DEFAULTS):
                        continue
                    if other in candidates and key not in self.entries[other].keys and order[other] > order[key_id]:
                        continue  # the other override comes later: it is the one dropped
                    found.setdefault((key, other, what), []).append(place.name)
        if mine:  # the same sequence as another chord
            for other, entry in self.entries.items():
                if other != key_id and other in CHORD_DEFAULTS:
                    sequence = (candidates.get(other) or entry.keys)[0]
                    if sequence == candidates[key_id][0] and not (other in candidates
                                                                  and order[other] > order[key_id]):
                        found.setdefault((sequence, other, entry.description), []).append("every view")
        if not found:
            return ""
        (key, other, what), names = next(iter(found.items()))
        who = f" ({other})" if other else ", which can't be changed"
        return f'{display(key)} already does "{what}"{who} in {listing(names)}'

    # -- using ------------------------------------------------------------------------------------------------------

    @property
    def textual(self) -> dict[str, str]:
        """What `App.set_keymap` is given: the overridden ids that are single keys, as Textual's key strings."""
        return {i: ",".join(self.effective[i]) for i in self.overridden if i not in CHORD_DEFAULTS}

    @property
    def chords(self) -> dict[str, str]:
        """Each chord's sequence and the action it runs."""
        return {self.effective[i][0]: action for i, (_, action, _) in CHORD_DEFAULTS.items()}

    @property
    def chord_prefixes(self) -> set[str]:
        return {sequence[0] for sequence in self.chords}

    def keys(self, key_id: str) -> list[str]:
        return self.effective[key_id]

    def fill(self, text: str) -> str:
        """`text` with each `{id}` as the id's key, and `{id:all}` as all its keys, as the user is to read them. An
        id that doesn't exist raises KeyError: a mistake in the program."""
        def key(match: re.Match[str]) -> str:
            keys = self.effective[match[1]] if match[1] in CHORD_DEFAULTS else [
                display(k) for k in self.effective[match[1]]]
            return " / ".join(keys) if match[2] else keys[0]

        return PLACEHOLDER.sub(key, text)

    @staticmethod
    def written(key_id: str, keys: list[str]) -> str:
        """The keys as config.toml takes them: a chord as "g t", the others as a comma list."""
        if key_id in CHORD_DEFAULTS:
            return " ".join(keys[0])
        return ",".join(written_key(key) for key in keys)

    def listing(self) -> str:
        """The `[keys]` table that `tui-trello keys` prints: every id, grouped, with the key in use."""
        lines: list[str] = []
        group = ""
        for key_id, entry in self.entries.items():
            if entry.group != group:
                group = entry.group
                lines += ["", f"# {group}: {GROUPS.get(group, '')}"]
            value = self.written(key_id, self.effective[key_id])
            note = f" (default: {self.written(key_id, entry.keys)})" if self.effective[key_id] != entry.keys else ""
            lines.append(f'{key_id} = "{value}"'.ljust(38) + f"  # {entry.description}{note}")
        return "[keys]" + "\n".join(lines) + "\n"


def of(app) -> KeyMap:
    """The app's keys; the defaults for an app that isn't a `TrelloApp` (a widget mounted in a bare `App` in tests)."""
    return getattr(app, "keymap", None) or KeyMap.default()


def markdown_table(keymap: KeyMap | None = None) -> str:
    """Every id with its default key and what it does, as a Markdown table padded to line up (the README holds it;
    a test keeps the two in step)."""
    entries = (keymap or KeyMap.default()).entries
    rows = [("id", "default", "what it does")]
    for key_id, entry in entries.items():
        keys = " ".join(entry.keys[0]) if key_id in CHORD_DEFAULTS else ", ".join(display(k) for k in entry.keys)
        rows.append((f"`{key_id}`", f"`{keys}`", entry.description))
    widths = [max(len(row[n]) for row in rows) for n in range(3)]

    def line(row: tuple[str, ...]) -> str:
        return "| " + " | ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)) + " |"

    return "\n".join([line(rows[0]), "| " + " | ".join("-" * width for width in widths) + " |",
                      *(line(row) for row in rows[1:])])
