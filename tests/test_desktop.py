from tui_trello.ui import desktop


def test_sequence_per_terminal() -> None:
    assert desktop.sequence("Grace; Hopper", "hi", {"VTE_VERSION": "7600"}) == "\x1b]777;notify;Grace, Hopper;hi\x1b\\"
    assert desktop.sequence("Grace", "hi", {"TERM": "xterm-kitty"}) == "\x1b]9;Grace: hi\x1b\\"
    assert desktop.sequence("Grace", "hi", {"TMUX": "/tmp/tmux", "TERM": "tmux"}).startswith("\x1bPtmux;\x1b\x1b]9;")


def test_comment_text_cannot_end_the_sequence() -> None:
    """The body is someone else's comment: it mustn't be able to send the terminal its own escape sequences."""
    seq = desktop.sequence("Grace", "a\x1b\\\x1b]52;c;ZXZpbA==\x07b\nc", {})
    assert seq.count("\x1b") == 2 and "\x07" not in seq and "\n" not in seq


def test_notify_send_only_on_a_local_desktop(monkeypatch) -> None:
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/notify-send")
    assert desktop.use_notify_send({"WAYLAND_DISPLAY": "wayland-0"})
    assert not desktop.use_notify_send({"WAYLAND_DISPLAY": "wayland-0", "SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22"})
    assert not desktop.use_notify_send({})
