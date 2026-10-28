"""
Вспомогательные функции для работы с фото в сообщениях ВК:
скачивание присланного пользователем фото и загрузка готового результата
обратно, чтобы прикрепить его к ответному сообщению.
"""
import io
from typing import Optional

import aiohttp
from vkbottle import PhotoMessageUploader
from vkbottle.bot import Message


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

    async with aiohttp.ClientSession() as session:
        async with session.get(best.url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def upload_photo_for_message(api, image_bytes: bytes, peer_id: int) -> str:
    """Загружает картинку на сервер ВК и возвращает attachment-строку вида
    photo<owner_id>_<id>, готовую для передачи в message.answer(attachment=...)."""
    uploader = PhotoMessageUploader(api)
    return await uploader.upload(io.BytesIO(image_bytes), peer_id=peer_id)
