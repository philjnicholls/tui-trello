"""`remote.py`: the newsfeed read from GitHub, cached and validated. No test reaches the network: every one hands
`RemoteFiles` an `httpx.MockTransport`."""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from tui_trello import remote
from tui_trello.remote import NEWS_FILE, NEWS_LIMIT, TIMEOUT, RemoteFiles, parse_news

NEWS = "# News\n\n## 2026-01-02: Second\n\nHello **there**.\n\n## 2026-01-03: Third\n\nNewest.\n"


class Server:
    """A fake raw.githubusercontent.com: serves `files`, with ETags, and records the requests."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = {NEWS_FILE: NEWS} if files is None else files
        self.requests: list[httpx.Request] = []
        self.etag = 1

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in self.files:
            return httpx.Response(404)
        etag = f'"{self.etag}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, text=self.files[name], headers={"etag": etag})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def files_for(tmp_path: Path, handler) -> RemoteFiles:
    return RemoteFiles(tmp_path / "cache", httpx.MockTransport(handler))


async def test_refresh_caches_the_newsfeed(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    assert files.news() == [] and files.last_fetched() is None
    assert await files.refresh() is True
    assert [item.title for item in files.news()] == ["Third", "Second"]
    assert files.last_fetched() is not None
    assert all(request.headers["user-agent"] == "tui-trello" for request in server.requests)
    assert [item.title for item in RemoteFiles(tmp_path).news()] == ["Third", "Second"]  # a new run reads the cache


async def test_only_the_newsfeed_is_requested(tmp_path) -> None:
    server = Server()
    await RemoteFiles(tmp_path, server.transport).refresh(force=True)
    assert [request.url.path for request in server.requests] == [
        "/philjnicholls/tui-trello/main/remote/newsfeed.md"]


async def test_not_modified_keeps_the_cache_and_sends_the_etag(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    first = files.last_fetched()
    server.requests.clear()
    time.sleep(0.01)
    assert await files.refresh(force=True) is False
    assert [request.headers["if-none-match"] for request in server.requests] == ['"1"']
    assert len(files.news()) == 2
    assert files.last_fetched() > first


async def test_a_changed_file_is_fetched_again_and_reports_new_news(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    server.etag = 2
    server.files[NEWS_FILE] = "## 2026-02-01: Fourth\n\nMore.\n" + NEWS
    assert await files.refresh(force=True) is True
    assert [item.title for item in files.news()][0] == "Fourth"


async def test_offline_keeps_the_last_good_copy(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    files.transport = httpx.MockTransport(offline)
    assert await files.refresh(force=True) is False
    assert len(files.news()) == 2


async def test_timeout_gives_up_within_the_bound(tmp_path) -> None:
    async def never(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        return httpx.Response(200)

    files = files_for(tmp_path, never)
    started = time.monotonic()
    assert await files.refresh() is False
    assert time.monotonic() - started < 2 * TIMEOUT + 1


@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(500), httpx.Response(
    301, headers={"location": "https://example.com/newsfeed.md"}), httpx.Response(
    302, headers={"location": "https://example.com/"}, text=NEWS)])
async def test_404_and_redirects_are_ignored(tmp_path, response) -> None:
    requests: list[httpx.Request] = []
    files = files_for(tmp_path, lambda request: requests.append(request) or response)
    assert await files.refresh() is False
    assert files.news() == []
    assert files.last_fetched() is None
    assert all(request.url.host == "raw.githubusercontent.com" for request in requests)  # nothing was followed


async def test_oversized_body_is_ignored(tmp_path) -> None:
    server = Server({NEWS_FILE: "## 2026-01-01: T\n" + "x" * NEWS_LIMIT})
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    assert files.news() == []


def test_news_parses_items_newest_first_and_skips_bad_headings() -> None:
    text = """# tui-trello news

## 2026-03-01: Older

Body one, with `code`.

## Not a dated heading

Skipped.

## 2026-13-45: Not a date

Skipped too.

## 2026-04-01: Newer: with a colon

- a
- b
"""
    older_first = [item.id for item in parse_news(text)]
    assert older_first == ["2026-04-01: Newer: with a colon", "2026-03-01: Older"]
    newer, older = parse_news(text)
    assert (newer.title, str(newer.date), newer.body) == ("Newer: with a colon", "2026-04-01", "- a\n- b")
    assert older.body == "Body one, with `code`."
    assert parse_news("") == []
    assert len(parse_news("".join(f"## 2026-01-{n:02d}: t{n}\n\nx\n" for n in range(1, 29)))) == 20


async def test_refresh_is_skipped_until_check_after(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    count = len(server.requests)
    assert await files.refresh() is False and len(server.requests) == count  # too soon
    meta = json.loads((tmp_path / "meta.json").read_text())
    meta["attempt"] -= remote.CHECK_AFTER + 1
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    await files.refresh()
    assert len(server.requests) == count + 1


async def test_a_failed_attempt_counts_as_an_attempt(tmp_path) -> None:
    requests: list[httpx.Request] = []
    files = files_for(tmp_path, lambda request: requests.append(request) or httpx.Response(404))
    await files.refresh()
    await files.refresh()
    assert len(requests) == 1  # the second call is too soon after the first attempt


async def test_non_dict_etags_are_reset(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    meta = json.loads((tmp_path / "meta.json").read_text())
    meta["etags"] = ["not", "a", "dict"]
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    await files.refresh(force=True)
    assert isinstance(json.loads((tmp_path / "meta.json").read_text())["etags"], dict)
    assert len(files.news()) == 2


async def test_a_non_string_etag_is_not_sent(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    meta = json.loads((tmp_path / "meta.json").read_text())
    meta["etags"] = {name: 5 for name in meta["etags"]}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    await files.refresh(force=True)
    assert all(isinstance(etag, str) for etag in json.loads((tmp_path / "meta.json").read_text())["etags"].values())


async def test_refresh_never_raises(tmp_path) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("bad proxy")

    files = files_for(tmp_path, broken)
    assert await files.refresh(force=True) is False


async def test_a_non_printable_etag_is_not_sent(tmp_path) -> None:
    """CR31: a stored ETag that isn't printable ASCII is dropped, not sent, and the next answer replaces it."""
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    for bad in ("caf\u00e9", '"a\x00b"', "\n"):
        meta = json.loads((tmp_path / "meta.json").read_text())
        meta["etags"] = {NEWS_FILE: bad}
        (tmp_path / "meta.json").write_text(json.dumps(meta))
        server.requests.clear()
        await files.refresh(force=True)
        assert "if-none-match" not in server.requests[0].headers
        assert json.loads((tmp_path / "meta.json").read_text())["etags"] == {NEWS_FILE: '"1"'}


async def test_an_empty_etag_is_not_sent(tmp_path) -> None:
    """CR44."""
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    meta = json.loads((tmp_path / "meta.json").read_text())
    meta["etags"] = {NEWS_FILE: ""}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    server.requests.clear()
    await files.refresh(force=True)
    assert "if-none-match" not in server.requests[0].headers


async def test_offline_keeps_the_etag(tmp_path) -> None:
    """CR45: no answer says nothing about the ETag, so the next start can still get a 304."""
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    files.transport = httpx.MockTransport(offline)
    await files.refresh(force=True)
    assert json.loads((tmp_path / "meta.json").read_text())["etags"] == {NEWS_FILE: '"1"'}


async def test_a_failed_fetch_forgets_the_etag(tmp_path) -> None:
    server = Server()
    files = RemoteFiles(tmp_path, server.transport)
    await files.refresh()
    assert json.loads((tmp_path / "meta.json").read_text())["etags"] == {NEWS_FILE: '"1"'}
    del server.files[NEWS_FILE]
    await files.refresh(force=True)  # 404
    assert json.loads((tmp_path / "meta.json").read_text())["etags"] == {}
    assert len(files.news()) == 2  # the last good copy stays


def test_published_files_are_valid() -> None:
    folder = Path(__file__).parent.parent / "remote"
    assert parse_news((folder / "newsfeed.md").read_text())
    assert [path.name for path in folder.iterdir()] == ["newsfeed.md"]
