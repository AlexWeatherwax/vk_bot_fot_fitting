"""
Вспомогательные функции для работы с фото в сообщениях ВК:
скачивание присланного пользователем фото и загрузка готового результата
обратно, чтобы прикрепить его к ответному сообщению.
"""
import asyncio
import io
import json
from typing import Optional

import aiohttp
from vkbottle import PhotoMessageUploader
from vkbottle.bot import Message


MAX_PHOTO_BYTES = 20 * 1024 * 1024
PHOTO_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=15)
PHOTO_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)


class PhotoDownloadError(Exception):
    """A download failure that can be explained to the user and retried."""


class PhotoUploadError(Exception):
    """An upload failure with diagnostics safe for the application log."""


class _RetryablePhotoUploadError(PhotoUploadError):
    pass


class _MessagePhotoUploader(PhotoMessageUploader):
    async def upload_files(self, upload_url, files):
        # Keep the SDK's server/save/attachment handling, but make the HTTP
        # boundary explicit: its default uploader parses even HTML errors as JSON.
        form = aiohttp.FormData()
        for name, source in files.items():
            form.add_field(
                name, source.getvalue(), filename="tryon.jpg", content_type="image/jpeg",
            )
        try:
            async with aiohttp.ClientSession(timeout=PHOTO_UPLOAD_TIMEOUT) as session:
                async with session.post(upload_url, data=form) as response:
                    raw = await response.read()
                    # Never include the signed upload URL, response body or hash.
                    kind = response.content_type
                    if kind not in {"application/json", "text/html", "text/plain", "text/javascript"}:
                        kind = "other"
                    diagnostic = (
                        f"VK photo upload: HTTP {response.status}, "
                        f"content_type={kind}, body_bytes={len(raw)}"
                    )
                    if not 200 <= response.status < 300:
                        error = (_RetryablePhotoUploadError if response.status in
                                 {408, 425, 429, 500, 502, 503, 504} else PhotoUploadError)
                        raise error(diagnostic)
                    try:
                        result = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise _RetryablePhotoUploadError(diagnostic + ", invalid JSON") from None
                    if (not isinstance(result, dict)
                            or not all(key in result for key in ("server", "photo", "hash"))
                            or not result["photo"] or result["photo"] == "[]"):
                        raise _RetryablePhotoUploadError(diagnostic + ", missing photo")
                    return result
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError):
            # aiohttp exception strings may contain the complete signed URL.
            raise _RetryablePhotoUploadError("VK photo upload: transport failure") from None


async def download_first_photo(message: Message) -> Optional[bytes]:
    """Возвращает байты самого большого доступного размера первого фото
    во вложениях сообщения, либо None, если фото во вложениях нет."""
    attachments = message.attachments or []
    photos = [att.photo for att in attachments if getattr(att, "photo", None)]
    if not photos:
        return None

    sizes = photos[0].sizes or []
    if not sizes:
        return None
    best = max(sizes, key=lambda s: (s.width or 0) * (s.height or 0))
    if not best.url:
        return None

    too_large = "Фото слишком большое. Пришлите изображение размером не больше 20 МБ."
    try:
        async with aiohttp.ClientSession(timeout=PHOTO_DOWNLOAD_TIMEOUT) as session:
            async with session.get(best.url) as resp:
                resp.raise_for_status()
                if resp.content_length is not None and resp.content_length > MAX_PHOTO_BYTES:
                    raise PhotoDownloadError(too_large)
                photo = bytearray()
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    if len(photo) + len(chunk) > MAX_PHOTO_BYTES:
                        raise PhotoDownloadError(too_large)
                    photo.extend(chunk)
                return bytes(photo)
    except asyncio.TimeoutError as exc:
        raise PhotoDownloadError("Фото загружается слишком долго. Пришлите его ещё раз.") from exc
    except (aiohttp.ClientError, OSError) as exc:
        raise PhotoDownloadError("Не удалось скачать фото. Пришлите его ещё раз.") from exc


async def upload_photo_for_message(api, image_bytes: bytes, peer_id: int) -> str:
    """Загружает картинку на сервер ВК и возвращает attachment-строку вида
    photo<owner_id>_<id>, готовую для передачи в message.answer(attachment=...)."""
    uploader = _MessagePhotoUploader(api)
    for attempt in range(2):
        try:
            return await uploader.upload(io.BytesIO(image_bytes), peer_id=peer_id)
        except _RetryablePhotoUploadError as exc:
            if attempt:
                raise PhotoUploadError(str(exc)) from None
            # Request a fresh upload server and construct a fresh multipart body.
            # Retry only before saveMessagesPhoto, never after saving/sending.
            await asyncio.sleep(0.5)
