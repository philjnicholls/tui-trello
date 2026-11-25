"""`scripts/arabic_forms.py`, which joins Arabic letters for the screenshots: loaded by path, as `test_release.py`
runs `scripts/release_notes.py`."""

import importlib.util
import unicodedata
from pathlib import Path

from tui_trello.ui.bidi import has_rtl, visual

SCRIPT = Path(__file__).parent.parent / "scripts" / "arabic_forms.py"
spec = importlib.util.spec_from_file_location("arabic_forms", SCRIPT)
assert spec and spec.loader
arabic_forms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arabic_forms)
shape = arabic_forms.shape


def test_shape_joins_a_word() -> None:
    # meem initial, reh final (it joins only the letter before it), hah initial, beh medial, alef final
    assert shape("مرحبا") == "\ufee3\ufeae\ufea3\ufe92\ufe8e"


def test_lam_alef_stays_two_cells() -> None:
    assert shape("بلا") == "\ufe91\ufee0\ufe8e"  # beh initial, lam medial, alef final: three characters, no ligature
    assert shape("لا") == "\ufedf\ufe8e"
    assert len(shape("الصفحة")) == len("الصفحة")


def test_hamza_and_right_joining_letters_break_the_join() -> None:
    assert shape("ءا") == "\ufe80\ufe8d"  # hamza joins nothing, so the alef after it is isolated
    assert shape("دب") == "\ufea9\ufe8f"  # dal joins nothing after it: dal and beh are both isolated
    assert shape("بد") == "\ufe91\ufeaa"  # ...but it takes the join from the letter before it


def test_other_text_is_unchanged() -> None:
    for text in ("Fix it", "2.5 ٢٫٥ 50%", "ok 😀 👍🏽", "(x) - y"):
        assert shape(text) == text
    assert shape("ك\u064eت\u064eب\u064e")[1] == "\u064e"  # a fatha stays where it was, and doesn't break the join
    assert shape("ك\u064eت\u064eب\u064e") == "\ufedb\u064e\ufe98\u064e\ufe90\u064e"


def test_shaped_text_is_still_rtl() -> None:
    shaped = shape("مرحبا")
    assert has_rtl(shaped)
    assert all(unicodedata.bidirectional(char) == "AL" for char in shaped)
    assert visual(shaped).plain == shaped[::-1]
