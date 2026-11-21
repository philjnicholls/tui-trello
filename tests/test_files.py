from pathlib import Path

from tui_trello.files import download_dir, human_size, unique_path


def test_unique_path(tmp_path) -> None:
    assert unique_path(tmp_path, "notes.txt") == tmp_path / "notes.txt"
    (tmp_path / "notes.txt").touch()
    (tmp_path / "notes (1).txt").touch()
    assert unique_path(tmp_path, "notes.txt") == tmp_path / "notes (2).txt"
    assert unique_path(tmp_path, "../../etc/passwd") == tmp_path / "passwd"  # a name from Trello, not a path


def test_download_dir() -> None:
    assert download_dir({"XDG_DOWNLOAD_DIR": "~/Stuff"}) == Path.home() / "Stuff"


def test_human_size() -> None:
    assert [human_size(n) for n in (5, 115146, 3 * 1024 * 1024)] == ["5 B", "112.4 KB", "3.0 MB"]
