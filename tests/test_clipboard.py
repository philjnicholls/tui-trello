from tui_trello.ui import clipboard


def test_local_tool_per_session(monkeypatch) -> None:
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert clipboard.command({"WAYLAND_DISPLAY": "wayland-0"}, "linux") == ["wl-copy"]
    assert clipboard.command({"DISPLAY": ":0"}, "linux") == ["xclip", "-selection", "clipboard"]
    assert clipboard.command({}, "darwin") == ["pbcopy"]
    assert clipboard.command({"DISPLAY": ":0", "SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22"}, "linux") is None
    assert clipboard.command({}, "linux") is None


def test_falls_back_to_the_terminal(monkeypatch) -> None:
    monkeypatch.setattr(clipboard, "command", lambda: None)
    sent: list[str] = []
    clipboard.copy("https://trello.com/c/abc", sent.append)
    assert sent == ["https://trello.com/c/abc"]
