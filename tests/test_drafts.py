import stat

from tui_trello.drafts import Draft, Drafts


def test_drafts_survive_a_restart(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    drafts = Drafts(path)
    assert drafts.set("comment", "c1", "half a thought")
    assert drafts.set("desc", "c1", "new words", base="old words")
    assert not drafts.set("comment", "c1", "half a thought")  # unchanged: no write
    again = Drafts(path)
    assert again.get("comment", "c1") == Draft("half a thought")
    assert again.get("desc", "c1") == Draft("new words", "old words")
    assert again.kinds("c1") == ["comment", "desc"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600  # private until sent


def test_blank_text_drops_the_draft(tmp_path) -> None:
    drafts = Drafts(tmp_path / "drafts.json")
    drafts.set("comment", "c1", "hello")
    assert drafts.set("comment", "c1", "  \n")
    assert drafts.get("comment", "c1") is None
    assert Drafts(tmp_path / "drafts.json").kinds("c1") == []


def test_a_damaged_file_is_ignored(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    path.write_text("{not json")
    assert Drafts(path).kinds("c1") == []


def test_a_sent_card_draft_is_remembered(tmp_path) -> None:
    path = tmp_path / "drafts.json"
    drafts = Drafts(path)
    drafts.set("card", "l1/a", "name")
    drafts.mark_sent("card", "l1/a", True)
    again = Drafts(path)
    assert again.get("card", "l1/a") == Draft("name", sent=True)
    assert not again.set("card", "l1/a", "name")  # the box closing on the same text: still sent
    assert again.set("card", "l1/a", "new name")
    assert again.get("card", "l1/a") == Draft("new name", sent=True)  # an edit doesn't unmake the card
    assert again.discard("card", "l1/a")
    again.set("card", "l1/a", "afresh")
    assert again.get("card", "l1/a") == Draft("afresh")
