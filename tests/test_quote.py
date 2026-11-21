from tui_trello import quote


def test_short_comment_is_quoted_whole() -> None:
    assert quote.fits("Looks good to me.")
    assert quote.reply("Looks good to me.", "grace") == "> Looks good to me.\n\n@grace "


def test_reply_quotes_every_line() -> None:
    assert quote.reply("one\n\n- two", "") == "> one\n>\n> - two\n\n"


def test_earlier_quotes_are_left_out() -> None:
    assert quote.own_text("> Ship it?\n\n@grace yes, today.") == "@grace yes, today."
    assert quote.own_text("> only a quote") == "> only a quote"


def test_shorten_cuts_at_a_word() -> None:
    text = "word " * 100
    short = quote.shorten(text)
    assert len(short) <= quote.LIMIT + 1 and short.endswith("word…")
    assert quote.shorten("\n".join(f"line {n}" for n in range(10))).endswith("line 5…")


def test_parts() -> None:
    long = "x " * 200
    assert quote.parts(f"First.\n\n{long}\n\nLast.") == ["First.", quote.shorten(long.strip()), "Last."]
    assert quote.parts("one\ntwo\nthree") == ["one", "two", "three"]
    assert quote.parts("Is it done? Yes. Ship it!") == ["Is it done?", "Yes.", "Ship it!"]
