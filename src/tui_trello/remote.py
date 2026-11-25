"""The newsfeed the app reads from its public GitHub repository, so news can change without a release.

`remote/newsfeed.md` is read from the repository's `main` branch over HTTPS, at most once an hour, with an ETag so an
unchanged file costs a 304, and kept in `$XDG_STATE_HOME/tui-trello/remote/`. Nothing here raises to its caller: when
GitHub can't be reached, or answers anything unexpected, the last good copy stays. The URL is fixed in this module;
nothing fetched can change where the app fetches from, or any setting. See docs/remote.md.

This module has no UI and imports no Textual, so the command line can use it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from tui_trello.config import state_dir

BASE_URL = "https://raw.githubusercontent.com/philjnicholls/tui-trello/main/remote/"
NEWS_FILE = "newsfeed.md"
NEWS_LIMIT = 64 * 1024
TIMEOUT = 3.0  # seconds per request; a whole refresh gets twice this
CHECK_AFTER = 3600  # seconds since the last attempt before start-up checks again
RECHECK_EVERY = 6 * 3600  # seconds between checks while the app stays open
NEWS_ITEMS = 20  # the most items kept

NEWS_HEADING = re.compile(r"## (\d{4}-\d{2}-\d{2}): (.+?)\s*$")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewsItem:
    id: str  # the heading text: editing it makes the item show as new again
    date: date
    title: str
    body: str  # Markdown


def parse_news(text: str) -> list[NewsItem]:
    """The items of a newsfeed, newest first: one per `## YYYY-MM-DD: Title` heading, its Markdown under it. Other
    `## ` headings are skipped with what is under them."""
    items: list[NewsItem] = []
    current: tuple[str, date, str] | None = None
    body: list[str] = []

    def finish() -> None:
        if current:
            items.append(NewsItem(current[0], current[1], current[2], "\n".join(body).strip()))

    for line in text.splitlines():
        if line.startswith("## "):
            finish()
            current, body = None, []
            if match := NEWS_HEADING.fullmatch(line):
                try:
                    current = (line[3:].strip(), date.fromisoformat(match[1]), match[2])
                except ValueError:  # 2026-13-45
                    pass
        elif current:
            body.append(line)
    finish()
    items.sort(key=lambda item: item.date, reverse=True)  # stable: the file's order within a day
    return items[:NEWS_ITEMS]


def default_transport() -> httpx.AsyncBaseTransport | None:
    """None: httpx's real transport. The tests replace this, so none of them can reach GitHub by accident."""
    return None


class RemoteFiles:
    """The cached copy of the newsfeed, and the fetching that refreshes it."""

    def __init__(self, cache_dir: Path | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cache_dir = cache_dir or state_dir() / "remote"
        self.transport = transport

    # -- reading the cache (never the network) ------------------------------------------------------------------

    def news(self) -> list[NewsItem]:
        try:
            return parse_news((self.cache_dir / NEWS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def last_fetched(self) -> float | None:
        """Unix time of the last successful fetch (a 304 counts), or None."""
        fetched = self._meta().get("fetched")
        return float(fetched) if isinstance(fetched, (int, float)) else None

    def _meta(self) -> dict[str, Any]:
        try:
            data = json.loads((self.cache_dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, name: str, content: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_dir / f".{name}.tmp"
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.cache_dir / name)

    # -- fetching ---------------------------------------------------------------------------------------------------

    async def refresh(self, force: bool = False) -> bool:
        """Fetch the newsfeed if the last attempt is older than `CHECK_AFTER` (or `force`). True if the news changed.
        Never raises (other than being cancelled): on any failure the cache is kept."""
        meta = self._meta()
        attempt = meta.get("attempt")
        if not force and isinstance(attempt, (int, float)) and 0 <= time.time() - attempt < CHECK_AFTER:
            return False
        before = self.news()
        try:
            meta["attempt"] = time.time()
            self._write("meta.json", json.dumps(meta))
            await asyncio.wait_for(self._fetch_news(meta), 2 * TIMEOUT)
        except Exception as exc:  # an optional check must not break the app (a bad proxy URL raises InvalidURL)
            log.debug("remote files: %s: %s", type(exc).__name__, exc)
        return self.news() != before

    async def _fetch_news(self, meta: dict[str, Any]) -> None:
        transport = self.transport or default_transport()
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, transport=transport,
                                     headers={"User-Agent": "tui-trello"}) as client:
            try:
                fetched = await self._fetch(client, NEWS_FILE, NEWS_LIMIT, parse_news, meta)
            except (httpx.HTTPError, OSError, TimeoutError) as exc:  # offline: keep what is cached
                log.debug("remote files: %r", exc)
                fetched = None  # no answer at all: the ETag may still be good
        if fetched:
            meta["fetched"] = time.time()
        elif fetched is False and isinstance(meta.get("etags"), dict):
            meta["etags"].pop(NEWS_FILE, None)  # a refused or invalid answer forgets the ETag, so a bad one can't stick
        self._write("meta.json", json.dumps(meta))

    async def _fetch(self, client: httpx.AsyncClient, name: str, limit: int, check: Any,
                     meta: dict[str, Any]) -> bool:
        """Update one file in the cache; True if GitHub answered with the file or a 304, False if it was refused."""
        if not isinstance(meta.get("etags"), dict):
            meta["etags"] = {}
        etags = meta["etags"]
        headers = {}
        etag = etags.get(name)
        if (isinstance(etag, str) and etag and etag.isascii() and etag.isprintable()
                and (self.cache_dir / name).exists()):
            headers["If-None-Match"] = etag
        async with client.stream("GET", BASE_URL + name, headers=headers) as response:
            if response.status_code == 304 and headers:
                return True
            if response.status_code != 200:
                return False
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    log.debug("remote files: %s is over %d bytes", name, limit)
                    return False
            new_etag = response.headers.get("etag", "")
        try:
            text = body.decode("utf-8")
            check(text)
        except ValueError as exc:  # also UnicodeDecodeError
            log.debug("remote files: ignoring %s: %s", name, exc)
            return False
        self._write(name, text)
        etags[name] = new_etag
        return True
