"""`[keys]`: the ids, the checks on an override, and the keys shown in text. No app is running unless a test says so."""

import re
from pathlib import Path

import pytest
from textual.binding import Binding
from textual.keys import _normalize_key_list
from textual.screen import Screen

from tui_trello import config
from tui_trello.config import Settings
from tui_trello.ui import follow, keymap, tips
from tui_trello.ui.app import TrelloApp
from tui_trello.ui.keymap import KeyMap, class_bindings, contexts, normalise_key
from tui_trello.ui.screens import base, keys, picker, preview, search
from tui_trello.ui.widgets import card_view

ID_FORM = re.compile(r"[a-z_]+\.[a-z_]+\Z")


def screen_classes() -> list[type]:
    found, todo = [TrelloApp], [Screen]
    while todo:
        cls = todo.pop()
        todo += cls.__subclasses__()
        if cls.__module__.startswith("tui_trello.ui"):
            found.append(cls)
    return found


def test_every_binding_has_a_known_id() -> None:
    known = KeyMap.default().entries
    defaults: dict[str, set[str]] = {}
    for cls in screen_classes():
        own: dict[str, set[str]] = {}
        for binding in Binding.make_bindings(vars(cls).get("BINDINGS", [])):
            assert binding.id and ID_FORM.match(binding.id), f"{cls.__name__}: {binding.key} has no group.name id"
            assert binding.id in known, f"{binding.id} is not in the catalogue"
            own.setdefault(binding.id, set()).add(normalise_key(binding.key))
        for key_id, keys_ in own.items():
            assert defaults.setdefault(key_id, keys_) == keys_, f"{key_id} has different keys in different places"


def test_every_description_is_for_a_known_id() -> None:
    assert set(keymap.WHAT) == set(KeyMap.default().entries)


def test_defaults_have_no_warnings() -> None:
    default = KeyMap.build({})
    assert default.warnings == [] and default.textual == {}


@pytest.mark.parametrize("key_id, value, expected", [
    ("card.archive", "A", "A"), ("card.archive", "ctrl+a", "ctrl+a"), ("list.filter", ["f", "ctrl+f"], "f,ctrl+f"),
    ("app.down", "j,down", "j,down"), ("app.help", "?", "question_mark"), ("popup.preview", "ctrl+/", "ctrl+slash"),
    ("card.delete", "shift+d", "D"), ("card.react", " ctrl+r ", "ctrl+r"), ("card.react", ",", "comma"),
    ("card.open", "F5", "f5"), ("card.open", "alt+enter", "alt+enter"), ("card.open", "ctrl++", "ctrl+plus"),
    ("card.open", "space", "space"), ("list.clear_filter", "esc", "escape"), ("card.open", "ctrl+esc", "ctrl+escape"), ("card.open", ["ctrl+o", "ctrl+shift+left"], "ctrl+o,ctrl+shift+left"),
])
def test_override_and_value_forms(key_id, value, expected) -> None:
    built = KeyMap.build({key_id: value})
    assert built.warnings == []
    assert built.textual == {key_id: expected}


def test_normalise_matches_textual() -> None:
    for sample in ["a", "Z", "1", "?", "/", ":", " ", "-", ".", "=", "@", "\\", "_", "up", "enter", "ctrl+a"]:
        assert normalise_key(sample) == _normalize_key_list(sample), sample


@pytest.mark.parametrize("key_id, value", [
    ("card.archiv", "x"),  # not an id
    ("card.move", 3), ("card.move", ""), ("card.move", []), ("card.move", "ctrl+"), ("card.move", "hyper+zz"),
    ("card.move", "notakey"), ("chord.top", "home"), ("chord.top", "ggg"), ("chord.top", ["g", "g"]),
])
def test_bad_entries_warn_and_keep_the_default(key_id, value) -> None:
    built = KeyMap.build({key_id: value})
    assert len(built.warnings) == 1 and key_id in built.warnings[0]
    assert built.textual == {} and built.chords == KeyMap.default().chords


def test_unknown_id_suggests_the_near_one() -> None:
    assert "did you mean `card.archive`?" in KeyMap.build({"card.archiv": "x"}).warnings[0]


def test_printable_key_in_a_popup_is_refused() -> None:
    assert "j" in KeyMap.build({"picker.down": "j"}).warnings[0]
    assert KeyMap.build({"popup.preview": "p"}).warnings
    assert KeyMap.build({"picker.down": "ctrl+n"}).warnings == []
    assert KeyMap.build({"card.move": "M"}).warnings == []  # a view has no text box focused


def test_clash_with_a_default_drops_the_override() -> None:
    built = KeyMap.build({"card.archive": "m"})
    assert len(built.warnings) == 1
    assert 'm already does "Move the card to another list" (card.move) in the browser' in built.warnings[0]
    assert "the card screen" in built.warnings[0] and "card.archive keeps A" in built.warnings[0]
    assert built.keys("card.archive") == ["A"] and built.textual == {}


def test_clash_with_an_app_key() -> None:
    built = KeyMap.build({"app.quit": "c"})
    assert "(card.comment)" in built.warnings[0] and built.keys("app.quit") == ["q"]


def test_clash_with_a_widget_key() -> None:
    built = KeyMap.build({"card.move": "enter"})
    assert "enter already does" in built.warnings[0] and "can't be changed" in built.warnings[0]
    assert built.keys("card.move") == ["m"]


def test_swap_is_not_a_clash() -> None:
    built = KeyMap.build({"card.archive": "D", "card.delete": "A"})
    assert built.warnings == []
    assert built.textual == {"card.archive": "D", "card.delete": "A"}


def test_two_overrides_clash() -> None:
    built = KeyMap.build({"card.archive": "ctrl+a", "card.delete": "ctrl+a"})
    assert len(built.warnings) == 1 and "(card.archive)" in built.warnings[0]
    assert built.textual == {"card.archive": "ctrl+a"} and built.keys("card.delete") == ["D"]


def test_dropping_an_override_can_free_a_clash_for_the_next() -> None:
    """card.delete = "m" is dropped (m is Move); card.move = "x" then clashes with the Checklist default."""
    built = KeyMap.build({"card.delete": "m", "card.move": "x"})
    assert len(built.warnings) == 2
    assert built.textual == {} and built.keys("card.move") == ["m"]


def test_chord_overrides() -> None:
    built = KeyMap.build({"chord.next_view": "g n"})
    assert built.warnings == [] and built.chords["gn"] == "cycle_mode(1)" and "gt" not in built.chords
    assert built.chord_prefixes == {"g"} and built.textual == {}
    clash = KeyMap.build({"card.move": "g"})
    assert "g already does" in clash.warnings[0] and clash.keys("card.move") == ["m"]
    moved = KeyMap.build({"chord.top": "z z", "chord.next_view": "z t", "chord.previous_view": "z T",
                          "card.move": "g"})
    assert moved.warnings == [] and moved.chord_prefixes == {"z"}
    same = KeyMap.build({"chord.next_view": "g g"})
    assert "chord.top" in same.warnings[0]


def test_fill() -> None:
    default = KeyMap.default()
    assert default.fill("{list.filter} {app.help} {preview.close:all} {chord.top}") == "f ? esc / q gg"
    assert KeyMap.build({"list.filter": "ctrl+f"}).fill("{list.filter}").startswith("ctrl+f")
    assert KeyMap.build({"card.move": "ctrl+/"}).fill("{card.move}") == "ctrl+/"
    assert default.fill("a {card.move} and a brace {not an id}") == "a m and a brace {not an id}"
    with pytest.raises(KeyError):
        default.fill("{card.nothing}")


def placeholder_strings() -> list[tuple[str, str]]:
    found = [(f"KEYS {row[0]}", text) for _, _, rows in keys.KEYS for row in rows for text in row[:2]]
    found += [(f"TIPS {n}", tip) for n, tip in enumerate(tips.TIPS)]
    found += [(f"{cls.__name__}.HINT", cls.HINT) for cls in [*picker.PickerScreen.__subclasses__(),
                                                              picker.PickerScreen, search.SearchScreen,
                                                              preview.LinkPreviewScreen]]
    found += [("FILTER_HELP", base.FILTER_HELP), ("IN_BROWSER", follow.IN_BROWSER),
              ("card_view.MISSING_COMMENT", card_view.CardView.MISSING_COMMENT),
              ("preview.MISSING_COMMENT", preview.PreviewCardView.MISSING_COMMENT)]
    return found


def test_placeholders_name_known_ids() -> None:
    known = KeyMap.default()
    strings = placeholder_strings()
    assert len(strings) > 60
    for where, text in strings:
        for key_id, _ in keymap.PLACEHOLDER.findall(text):
            assert key_id in known.entries, f"{where}: {{{key_id}}} is not a key id"
        known.fill(text)  # raises KeyError for an unknown id


def test_settings_reads_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('''
[keys]
card.archive = "ctrl+a"
"card.delete" = "ctrl+x"
list.filter = ["f", "ctrl+f"]

[keys.app]
quit = "Q"
''')
    settings = Settings.load(path)
    assert settings.keys == {"card.archive": "ctrl+a", "card.delete": "ctrl+x", "list.filter": ["f", "ctrl+f"],
                             "app.quit": "Q"}
    assert settings.warnings == []
    path.write_text('keys = "x"\n')
    settings = Settings.load(path)
    assert settings.keys == {} and "[keys] must be a table" in settings.warnings[0]
    path.write_text("")
    assert Settings.load(path).keys == {}


def test_flatten_keys() -> None:
    assert config.flatten_keys({"card": {"archive": "A"}, "app.quit": "Q", "x": {"y": {"z": 1}}}) == {
        "card.archive": "A", "app.quit": "Q", "x.y.z": 1}


def test_contexts_cover_every_popup_class() -> None:
    names = [place.name for place in contexts()]
    assert "the search popup" in names and "the links popup" in names and "the editor" in names
    assert all(place.text_box for place in contexts() if "popup" in place.name and "confirmation" not in place.name)


def test_readme_lists_every_binding_id() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    table = readme.split("<!-- keys-table -->\n", 1)[1].split("\n<!-- /keys-table -->", 1)[0]
    assert table == keymap.markdown_table(), "regenerate the table: python -c 'from tui_trello.ui import keymap; ...'"
    assert all(len(line) <= 120 for line in table.splitlines())


def test_class_bindings_walks_the_classes() -> None:
    ids = {b.id for b in class_bindings(base.ListScreen)}
    assert {"list.filter", "card.archive"} <= ids
