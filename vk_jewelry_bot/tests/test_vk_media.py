"""Download boundaries using fake HTTP/VK adapters; never access the network."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


class FakeBody:
    def __init__(self, chunks=()):
        self.chunks = chunks
        self.reads = 0

    async def iter_chunked(self, size):
        assert size > 0
        for chunk in self.chunks:
            self.reads += 1
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


class FakeResponse:
    def __init__(self, chunks=(), content_length=None, error=None):
        self.content = FakeBody(chunks)
        self.content_length = content_length
        self.error = error
        self.closed = False

    def raise_for_status(self):
        if self.error:
            raise self.error


@pytest.fixture
def media(monkeypatch):
    http = ModuleType("aiohttp")
    http.ClientError = type("ClientError", (Exception,), {})
    http.ClientTimeout = lambda **kwargs: SimpleNamespace(**kwargs)
    transport = SimpleNamespace(response=FakeResponse(), error=None, sessions=[], urls=[])

    class Request:
        async def __aenter__(self):
            if transport.error:
                raise transport.error
            return transport.response

        async def __aexit__(self, *args):
            transport.response.closed = True

    class Session:
        def __init__(self, *, timeout):
            self.timeout = timeout
            self.closed = False
            transport.sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        def get(self, url):
            transport.urls.append(url)
            return Request()

    http.ClientSession = Session
    vk = ModuleType("vkbottle")
    vk.__path__ = []
    vk.PhotoMessageUploader = object
    vk_bot = ModuleType("vkbottle.bot")
    vk_bot.Message = object
    monkeypatch.setitem(sys.modules, "aiohttp", http)
    monkeypatch.setitem(sys.modules, "vkbottle", vk)
    monkeypatch.setitem(sys.modules, "vkbottle.bot", vk_bot)
    # Load this adapter independently: dialog tests intentionally replace
    # bot.vk_media as a unit and do not install aiohttp/vkbottle.
    source = Path(__file__).resolve().parents[1] / "bot" / "vk_media.py"
    spec = importlib.util.spec_from_file_location("tested_vk_media", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(module=module, http=http, transport=transport)


def message(*sizes):
    return SimpleNamespace(attachments=[SimpleNamespace(photo=SimpleNamespace(sizes=list(sizes)))])


def download(media, msg):
    return asyncio.run(media.module.download_first_photo(msg))


def photo_size(url="https://cdn.example/photo", width=100, height=100):
    return SimpleNamespace(url=url, width=width, height=height)


@pytest.mark.parametrize("attachments", [None, [], [SimpleNamespace(photo=None)],
    [SimpleNamespace(photo=SimpleNamespace(sizes=[]))]])
def test_no_photo_returns_none_without_opening_http(media, attachments):
    assert download(media, SimpleNamespace(attachments=attachments)) is None
    assert media.transport.sessions == []


def test_photo_without_download_url_returns_none(media):
    assert download(media, message(photo_size(url=None))) is None
    assert media.transport.sessions == []


def test_largest_first_photo_is_streamed_and_sessions_close(media):
    media.transport.response = FakeResponse([b"first", b"-second"], content_length=12)
    msg = message(photo_size("small", 10, 20), photo_size("large", 20, 30))
    assert download(media, msg) == b"first-second"
    assert media.transport.urls == ["large"]
    session = media.transport.sessions[0]
    assert session.closed and media.transport.response.closed
    assert session.timeout.total == 30
    assert session.timeout.connect == 10
    assert session.timeout.sock_read == 15
    assert media.module.MAX_PHOTO_BYTES == 20 * 1024 * 1024


def test_declared_oversize_is_rejected_before_reading_body(media, monkeypatch):
    monkeypatch.setattr(media.module, "MAX_PHOTO_BYTES", 8)
    response = FakeResponse([b"must-not-be-read"], content_length=9)
    media.transport.response = response
    with pytest.raises(media.module.PhotoDownloadError, match="20 МБ"):
        download(media, message(photo_size()))
    assert response.content.reads == 0
    assert response.closed and media.transport.sessions[0].closed


@pytest.mark.parametrize("content_length", [None, 2])
def test_stream_limit_rejects_missing_or_incorrect_length_early(media, monkeypatch, content_length):
    monkeypatch.setattr(media.module, "MAX_PHOTO_BYTES", 8)
    response = FakeResponse([b"abcd", b"efghi", b"must-not-be-read"], content_length=content_length)
    media.transport.response = response
    with pytest.raises(media.module.PhotoDownloadError, match="слишком большое"):
        download(media, message(photo_size()))
    assert response.content.reads == 2
    assert response.closed and media.transport.sessions[0].closed


def test_photo_at_exact_limit_is_allowed(media, monkeypatch):
    monkeypatch.setattr(media.module, "MAX_PHOTO_BYTES", 8)
    media.transport.response = FakeResponse([b"1234", b"5678"], content_length=8)
    assert download(media, message(photo_size())) == b"12345678"


@pytest.mark.parametrize("failure", ["http", "connect", "read", "timeout-connect", "timeout-read"])
def test_http_network_and_timeout_errors_have_retry_messages(media, failure):
    error = asyncio.TimeoutError() if failure.startswith("timeout") else media.http.ClientError("private-download-url")
    if failure == "http":
        media.transport.response.error = error
    elif failure in ("connect", "timeout-connect"):
        media.transport.error = error
    else:
        media.transport.response = FakeResponse([b"part", error])
    with pytest.raises(media.module.PhotoDownloadError) as captured:
        download(media, message(photo_size()))
    assert "Пришлите его ещё раз" in str(captured.value)
    assert "private-download-url" not in str(captured.value)
    if failure.startswith("timeout"):
        assert "слишком долго" in str(captured.value)
    assert media.transport.sessions[0].closed
    if failure not in ("connect", "timeout-connect"):
        assert media.transport.response.closed


def test_os_network_error_has_retry_message(media):
    media.transport.error = OSError("connection reset")
    with pytest.raises(media.module.PhotoDownloadError, match="ещё раз"):
        download(media, message(photo_size()))
