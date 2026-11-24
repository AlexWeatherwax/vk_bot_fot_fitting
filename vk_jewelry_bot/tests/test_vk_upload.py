"""Exercise the installed VK uploader against a fake HTTP/API boundary."""
import asyncio
import importlib.util
import json
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("vkbottle")


@pytest.fixture
def transport(monkeypatch):
    # Dialog tests replace bot.vk_media as a unit; load the real adapter directly.
    source = Path(__file__).resolve().parents[1] / "bot" / "vk_media.py"
    spec = importlib.util.spec_from_file_location("tested_vk_upload", source)
    media = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(media)
    state = SimpleNamespace(responses=[], posts=[], sessions=[], api_calls=[], save_error=None)

    class Response:
        def __init__(self, status=200, body=None, content_type="application/json"):
            self.status = status
            self.body = body if body is not None else json.dumps({
                "server": 1, "photo": "uploaded-private-photo", "hash": "private-hash",
            }).encode()
            self.content_type = content_type
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def read(self):
            if isinstance(self.body, BaseException):
                raise self.body
            return self.body

    class Session:
        def __init__(self, *, timeout):
            self.timeout = timeout
            self.closed = False
            state.sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        def post(self, url, *, data):
            state.posts.append((url, data))
            return state.responses.pop(0)

    class API:
        async def request(self, method, params):
            state.api_calls.append((method, params))
            if method == "photos.getMessagesUploadServer":
                return {"response": {"upload_url": f"https://upload.example/private-{len(state.api_calls)}"}}
            assert method == "photos.saveMessagesPhoto"
            if state.save_error:
                raise state.save_error
            return {"response": [{"owner_id": -123, "id": 456, "access_key": "private-access"}]}

    async def no_delay(seconds):
        assert seconds <= 1

    monkeypatch.setattr(media.aiohttp, "ClientSession", Session)
    monkeypatch.setattr(media.asyncio, "sleep", no_delay)
    state.media = media
    state.api = API()
    state.Response = Response
    return state


def upload(transport):
    return asyncio.run(transport.media.upload_photo_for_message(transport.api, b"result-jpeg", 987))


@pytest.mark.parametrize("bom", [False, True])
def test_real_sdk_saves_upload_and_keeps_access_key(transport, bom):
    response = transport.Response(content_type="text/plain")
    if bom:
        response.body = b"\xef\xbb\xbf" + response.body
    transport.responses = [response]
    assert upload(transport) == "photo-123_456_private-access"
    assert transport.api_calls == [
        ("photos.getMessagesUploadServer", {"peer_id": 987}),
        ("photos.saveMessagesPhoto", {
            "server": 1, "photo": "uploaded-private-photo", "hash": "private-hash",
        }),
    ]
    assert response.closed and transport.sessions[0].closed
    assert transport.sessions[0].timeout.total == 60
    assert transport.sessions[0].timeout.connect == 10

    async def serialized_form():
        parts = []

        class Writer:
            async def write(self, data):
                parts.append(data)

        payload = transport.posts[0][1]()
        assert payload.headers["Content-Type"].startswith("multipart/form-data;")
        assert payload.size is not None  # Known Content-Length, no chunked file stream.
        await payload.write(Writer())
        return b"".join(parts)

    body = asyncio.run(serialized_form())
    assert b'name="photo"; filename="tryon.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert b"result-jpeg" in body


@pytest.mark.parametrize("status,body", [(200, b"<html>temporary error</html>"), (502, b"Bad Gateway")])
def test_transient_response_retries_a_fresh_server_before_save(transport, status, body):
    first = transport.Response(status, body, "text/html")
    transport.responses = [first, transport.Response()]
    assert upload(transport) == "photo-123_456_private-access"
    assert [method for method, params in transport.api_calls] == [
        "photos.getMessagesUploadServer", "photos.getMessagesUploadServer", "photos.saveMessagesPhoto",
    ]
    assert transport.posts[0][0] != transport.posts[1][0]
    assert transport.posts[0][1] is not transport.posts[1][1]
    assert first.closed and all(session.closed for session in transport.sessions)


def test_permanent_http_error_has_safe_diagnostics_and_does_not_retry(transport):
    transport.responses = [transport.Response(403, b"private-photo-response", "text/html")]
    with pytest.raises(transport.media.PhotoUploadError) as captured:
        upload(transport)
    assert str(captured.value) == "VK photo upload: HTTP 403, content_type=text/html, body_bytes=22"
    assert len(transport.api_calls) == 1
    assert "private" not in str(captured.value)


@pytest.mark.parametrize("body", [b"", b"<html>private-response</html>", b"{}", b'{"server":1,"photo":"[]","hash":"private"}'])
def test_invalid_upload_response_never_reaches_save(transport, body):
    transport.responses = [transport.Response(body=body), transport.Response(body=body)]
    with pytest.raises(transport.media.PhotoUploadError) as captured:
        upload(transport)
    assert len(transport.api_calls) == 2
    assert all(method == "photos.getMessagesUploadServer" for method, params in transport.api_calls)
    assert "private" not in str(captured.value)


def test_network_exception_cannot_leak_signed_url_into_traceback(transport):
    transport.responses = [transport.Response(body=aiohttp.ClientConnectionError(
        "https://upload.example/private-photo-token")) for _ in range(2)]
    with pytest.raises(transport.media.PhotoUploadError) as captured:
        upload(transport)
    rendered = "".join(traceback.format_exception(captured.value))
    assert "transport failure" in rendered
    assert "private-photo-token" not in rendered


def test_save_failure_is_not_retried(transport):
    transport.responses = [transport.Response()]
    transport.save_error = RuntimeError("save rejected")
    with pytest.raises(RuntimeError, match="save rejected"):
        upload(transport)
    assert len(transport.posts) == 1
    assert len(transport.api_calls) == 2
