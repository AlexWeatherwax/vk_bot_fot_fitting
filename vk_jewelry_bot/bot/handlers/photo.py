"""
Обработчик состояния "ждём фото": принимает присланное фото и ставит
примерку выбранного украшения в FIFO-очередь.
"""
import logging

from vkbottle.bot import BotLabeler
from vkbottle.bot import Message

from ..jewelry.catalog import catalog
from ..states import TryOnStates
from ..tryon.queue import (
    DuplicateTryOnJob,
    TryOnJob,
    TryOnQueueFull,
    tryon_queue,
)
from ..vk_media import download_first_photo

photo_labeler = BotLabeler()
logger = logging.getLogger("vk_jewelry_bot.photo")

CANCEL_WORDS = {"отмена", "cancel", "стоп", "стой"}


@photo_labeler.message(state=TryOnStates.WAITING_PHOTO)
async def photo_handler(message: Message):
    # Локальный импорт, чтобы избежать циклической зависимости bot.app <-> bot.handlers.photo
    from ..app import bot

    state = await bot.state_dispenser.get(message.peer_id)
    item_id = state.payload.get("item_id") if state else None
    item = next((i for i in catalog.items if i.id == item_id), None)

    if item is None:
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("Что-то пошло не так, попробуйте выбрать украшение заново.")
        return

    text = (message.text or "").strip().lower()
    if text in CANCEL_WORDS:
        if tryon_queue.has_peer(message.peer_id):
            await message.answer(
                "Фото уже принято в обработку, поэтому остановить текущую примерку сейчас нельзя."
            )
            return
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("Хорошо, отменила. Напишите название другого украшения.")
        return

    if tryon_queue.has_peer(message.peer_id):
        await message.answer(
            "Ваше фото уже в очереди на примерку. Дождитесь результата перед отправкой нового."
        )
        return

    photo_bytes = await download_first_photo(message)
    if photo_bytes is None:
        await message.answer("Жду именно фото 🙂 Прикрепите снимок к сообщению (или напишите «отмена»).")
        return

    job = TryOnJob(
        message=message,
        bot=bot,
        item=item,
        overlay_path=catalog.image_path(item),
        photo_bytes=photo_bytes,
    )
    try:
        position = await tryon_queue.enqueue(job)
    except DuplicateTryOnJob:
        await message.answer(
            "Ваше фото уже в очереди на примерку. Дождитесь результата перед отправкой нового."
        )
        return
    except TryOnQueueFull:
        logger.warning("Очередь примерок переполнена, peer_id=%s", message.peer_id)
        await message.answer(
            "Сейчас слишком много примерок в очереди 🙁 Попробуйте отправить фото чуть позже."
        )
        return

    if position == 1:
        await message.answer("Фото принято ✨ Начинаю примерку.")
    else:
        await message.answer(
            f"Фото принято ✨ Вы №{position} в очереди. "
            "Результат пришлю автоматически, пересылать фото ещё раз не нужно."
        )
