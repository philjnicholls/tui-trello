import pytest
from rich.console import Console
from rich.text import Text

from tui_trello.ui.bidi import BidiText, base_is_rtl, fit, has_rtl, visual


@pytest.mark.parametrize(("logical", "display"), [
    ("plain english", "plain english"),
    ("مرحبا world", "world ابحرم"),
    ("Fix الصفحة الرئيسية now", "Fix ةيسيئرلا ةحفصلا now"),
    ("خطأ 123 في النموذج", "جذومنلا يف 123 أطخ"),  # numbers stay left-to-right
    ("إصلاح (عاجل)", "(لجاع) حالصإ"),  # brackets are mirrored
    ("السعر: 1,000 €", "€ 1,000 :رعسلا"),
    ("50% خصم", "مصخ 50%"),
    ("تحديث API إلى الإصدار 2.5", "2.5 رادصإلا ىلإ API ثيدحت"),
])
def test_visual(logical: str, display: str) -> None:
    assert visual(logical).plain == display


def test_direction() -> None:
    assert has_rtl("abc ب") and not has_rtl("abc 123")
    assert base_is_rtl("123 مرحبا abc") and not base_is_rtl("abc مرحبا")


def test_visual_keeps_styles() -> None:
    text = Text.assemble(("مرحبا", "bold"), " ", ("عالم", "italic"))
    result = visual(text)
    assert result.plain == "ملاع ابحرم"
    assert str(result.get_style_at_offset(Console(), 0)) == "italic"
    assert str(result.get_style_at_offset(Console(), 5)) == "bold"


def test_fit_cuts_the_logical_end() -> None:
    line = fit("بطاقة باسم طويل جدا جدا", 12)
    assert line.cell_len == 12
    assert line.plain.startswith("…")  # the end of the sentence is cut, and in RTL the end is on the left
    assert line.plain.endswith("ةقاطب")  # ...so the first word is still there, on the right


def render(renderable, width: int) -> list[str]:
    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text().splitlines()


def test_bidi_text_wraps_before_reordering() -> None:
    lines = render(BidiText("واحد اثنان ثلاثة أربعة"), 12)
    # Logical lines "واحد اثنان" and "ثلاثة أربعة", each reordered and right-aligned: read top to bottom.
    assert [line.rstrip() for line in lines] == ["  نانثا دحاو", " ةعبرأ ةثالث"]


def test_bidi_text_leaves_ltr_alone() -> None:
    assert render(BidiText("hello world"), 20) == ["hello world"]


def test_explicit_mode_outside_tmux(monkeypatch) -> None:
    import io

    from tui_trello.ui import bidi

    monkeypatch.delenv("TMUX", raising=False)
    out = io.StringIO()
    with bidi.explicit_mode(out):
        assert out.getvalue() == "\x1b[8l"
    assert out.getvalue() == "\x1b[8l\x1b[8h"


def test_explicit_mode_in_tmux(monkeypatch) -> None:
    import io

    from tui_trello.ui import bidi

    calls: list[tuple[str, ...]] = []

    def fake_tmux(*args: str) -> str | None:
        calls.append(args)
        return "off" if args[0] == "show" else ""

    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setattr(bidi, "_tmux", fake_tmux)
    out = io.StringIO()
    with bidi.explicit_mode(out):
        assert out.getvalue() == "\x1bPtmux;\x1b\x1b[8l\x1b\\"
        assert calls[-1] == ("set", "-p", "-t", "%7", "allow-passthrough", "on")
    assert out.getvalue().endswith("\x1bPtmux;\x1b\x1b[8h\x1b\\")
    assert calls[-1] == ("set", "-pu", "-t", "%7", "allow-passthrough")  # put back as it was


@pytest.mark.parametrize("emoji", ["❤️", "👍🏽", "👨‍👩‍👦", "1️⃣"])
def test_visual_keeps_emoji_whole(emoji: str) -> None:
    assert emoji in visual(f"مرحبا {emoji} عالم").plain
    assert visual(f"مرحبا {emoji}").plain.startswith(emoji)


def test_visual_keeps_harakat_on_its_letter() -> None:
    shalom = "كَتَبَ"  # kaf, teh and beh, each with a fatha
    mashal = "بَ" + "تَ" + "كَ"  # the same clusters, last first
    assert visual(shalom + " abc").plain == "abc " + mashal
