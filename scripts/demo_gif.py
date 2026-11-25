"""Record docs/screenshots/demo.gif from the demo backend: `python scripts/demo_gif.py`.

The app is driven by key presses, as in screenshots.py, and an SVG screenshot is taken after each one. Headless Chrome
turns the SVGs into PNGs (it draws them as a browser would on GitHub, fonts included), and ffmpeg joins them into a GIF.
Needs `google-chrome` (or $CHROME) and `ffmpeg` on the PATH.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()  # keep any drafts away from the real ones
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # and the real config's keys out of the recording
os.environ["BROWSER"] = "true"  # nothing in the recording may open a real browser

from tui_trello.backend.demo import DemoBackend
from tui_trello.config import Settings
from tui_trello.ui.app import TrelloApp

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots" / "demo.gif"
SIZE = (120, 32)
WIDTH = 1200  # pixels across the GIF; the height follows from the SVG
TYPING = 0.07  # seconds a frame shows for each typed character
STEP = 0.6  # for each key press
PAUSE = 1.6  # for a frame worth reading

KEY_NAMES = {" ": "space", ":": "colon", "?": "question_mark", "/": "slash", "#": "number_sign", "@": "at"}


class Recorder:
    def __init__(self, app: TrelloApp, pilot) -> None:
        self.app = app
        self.pilot = pilot
        self.frames: list[tuple[str, float]] = []  # (svg, seconds it shows for)

    async def frame(self, seconds: float) -> None:
        await self.pilot.pause(0.3)
        svg = self.app.export_screenshot()
        if self.frames and self.frames[-1][0] == svg:
            self.frames[-1] = (svg, self.frames[-1][1] + seconds)
        else:
            self.frames.append((svg, seconds))

    async def press(self, *keys: str, hold: float = STEP) -> None:
        for key in keys:
            await self.pilot.press(key)
            await self.frame(hold)

    async def type(self, text: str, hold: float = STEP) -> None:
        for char in text:
            await self.pilot.press(KEY_NAMES.get(char, char))
            await self.pilot.pause(0.05)
            self.frames.append((self.app.export_screenshot(), TYPING))
        self.frames[-1] = (self.frames[-1][0], hold)


async def record() -> list[tuple[str, float]]:
    app = TrelloApp(DemoBackend(), Settings(default_board="b-product"))
    async with app.run_test(size=SIZE) as pilot:
        rec = Recorder(app, pilot)
        await rec.frame(PAUSE)
        # The browser: lists, then the cards in one, then a card.
        await rec.press("j", "j", "l")
        await rec.press("l", hold=PAUSE * 1.5)
        # Comment on it, then move it on.
        await rec.press("c")
        await rec.type("Looks good to me :tada: merging today")
        await rec.press("enter", hold=PAUSE)
        await rec.press("m")
        await rec.type("rev")
        await rec.press("enter", hold=PAUSE)
        # Triage, filtered to the bugs.
        await rec.press("escape", "2")
        await rec.press("f")
        await rec.type("#bug")
        await rec.press("enter", hold=PAUSE * 1.5)
        await rec.press("escape")
        # Search every board.
        await rec.press("/")
        await rec.type("palette", hold=PAUSE)
        await rec.press("enter", hold=PAUSE)
        # My work and notifications.
        await rec.press("escape", "3", hold=PAUSE * 1.5)
        await rec.press("4", hold=PAUSE * 1.5)
        # The keys for this view.
        await rec.press("question_mark", hold=PAUSE * 1.5)
    return rec.frames


def rasterise(svgs: list[str], folder: Path) -> list[Path]:
    """Each SVG as a PNG WIDTH pixels across, drawn by headless Chrome with a throwaway profile."""
    chrome = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        sys.exit("needs google-chrome or chromium (or set $CHROME)")
    view_box = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svgs[0])
    assert view_box, "no viewBox in Textual's SVG"
    width, height = map(float, view_box.groups())
    size = f"{WIDTH},{round(WIDTH * height / width)}"
    pngs = []
    for number, svg in enumerate(svgs):
        page = folder / f"{number:04}.html"
        svg = svg.replace("<svg ", '<svg width="100%" ', 1)
        page.write_text(f"<html><body style='margin:0;background:#0c0c0c'><div style='width:{WIDTH}px'>{svg}</div>")
        png = folder / f"{number:04}.png"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={folder / 'profile'}", f"--window-size={size}", f"--screenshot={png}",
                        "--virtual-time-budget=3000", page.as_uri()],
                       check=True, capture_output=True)
        pngs.append(png)
    return pngs


def encode(pngs: list[Path], seconds: list[float], folder: Path) -> None:
    listing = folder / "frames.txt"
    lines = [f"file '{png}'\nduration {duration:.2f}" for png, duration in zip(pngs, seconds, strict=True)]
    listing.write_text("\n".join(lines) + f"\nfile '{pngs[-1]}'\n")  # the concat demuxer drops the last duration
    palette = "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=none"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", f"fps=15,{palette}", "-loop", "0", str(OUT)], check=True)


def main() -> None:
    frames = asyncio.run(record())
    with tempfile.TemporaryDirectory() as folder:
        pngs = rasterise([svg for svg, _ in frames], Path(folder))
        encode(pngs, [seconds for _, seconds in frames], Path(folder))
    print(f"{OUT}: {len(frames)} frames, {sum(s for _, s in frames):.0f}s, {OUT.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
