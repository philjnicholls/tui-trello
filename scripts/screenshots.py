"""Regenerate docs/screenshots/*.svg from the demo backend: `python scripts/screenshots.py`."""

import asyncio
import dataclasses
import os
import tempfile
from pathlib import Path

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()  # keep any drafts away from the real ones

from arabic_forms import shape

from tui_trello.backend import demo
from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.ui.app import TrelloApp


def shaped(value):
    """`value` with every string in it, however deep, run through `shape`."""
    match value:
        case str():
            return shape(value)
        case list() | tuple():
            return type(value)(shaped(item) for item in value)
        case dict():
            return {key: shaped(item) for key, item in value.items()}
        case _:
            return value


def shape_demo_arabic() -> None:
    """Join the demo's Arabic letters before any `DemoBackend` is built. The SVG holds each character in a `<text>`
    element of its own, so a browser would draw every letter isolated; presentation forms are drawn as they are. Only
    this script does it: the app leaves joining to the terminal."""
    for name in [name for name in dir(demo) if name.startswith("ARABIC_")]:
        setattr(demo, name, shaped(getattr(demo, name)))
    member = demo.MEMBERS["m4"]
    demo.MEMBERS["m4"] = dataclasses.replace(member, full_name=shape(member.full_name))
    # The names notifications look cards up by, and the comments' authors, have to match the shaped ones.
    demo.NOTIFICATIONS[:] = shaped(demo.NOTIFICATIONS)


class SlowBackend(DemoBackend):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def board_snapshot(self, board_id: str):
        await self.release.wait()
        return await super().board_snapshot(board_id)


OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

# The app has already put RTL text in display order, cell by cell, as a terminal shows it. Stop browsers viewing the
# SVG from applying bidi again, which would reverse it back.
NO_BIDI = "<style>text { unicode-bidi: bidi-override; direction: ltr; }</style>"


def save(app: TrelloApp, name: str) -> None:
    path = Path(app.save_screenshot(f"{name}.svg", path=str(OUT)))
    svg = path.read_text()
    path.write_text(svg.replace("</svg>", f"{NO_BIDI}</svg>", 1) if NO_BIDI not in svg else svg)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shape_demo_arabic()
    app = TrelloApp(DemoBackend(), Settings(default_board="b-product"))
    async with app.run_test(size=(130, 30)) as pilot:

        async def shot(name: str, *keys: str) -> None:
            await pilot.press(*keys)
            await pilot.pause(0.3)
            save(app, name)

        await shot("browser", "j", "l", "j")
        await shot("move-picker", "m", "d", "o")
        await shot("triage", "escape", "2")
        await shot("triage-filter", "f", *"#feat @ada", "enter")
        await shot("card", "enter")
        await shot("palette", "escape", "colon", *"command")
        await shot("mywork", "escape", "escape", "3")
        await shot("mywork-nopreview", "p")
        await shot("help", "p", "question_mark")
        await shot("notifications", "escape", "4")
        await pilot.press("3")
        await shot("arabic-mywork", "escape")
        app.open_board("b-arabic")
        await shot("arabic-browser", "1", "h", "l", "j", "j")
        await shot("arabic-card", "enter")
        await shot("arabic-triage", "escape", "2")

    app = TrelloApp(DemoBackend(), Settings(default_board="b-product"))
    async with app.run_test(size=(130, 30)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("j", "j", "l", "j", "t")
        await pilot.pause(0.3)
        await pilot.press(*"ur")
        await pilot.pause(0.3)
        save(app, "labels")

    # A board that takes a while to load, for the loading animation.
    backend = SlowBackend()
    app = TrelloApp(backend, Settings(default_board="b-product"))
    async with app.run_test(size=(130, 30)) as pilot:
        await pilot.pause(0.5)
        save(app, "loading")
        backend.release.set()


asyncio.run(main())
