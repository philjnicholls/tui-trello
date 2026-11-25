from tui_trello.files import human_size


def test_human_size() -> None:
    assert [human_size(n) for n in (5, 115146, 3 * 1024 * 1024)] == ["5 B", "112.4 KB", "3.0 MB"]
