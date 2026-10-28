"""
Обработчик состояния "ждём фото": принимает присланное фото, запускает
примерку выбранного украшения и отправляет результат обратно пользователю.
"""
import logging

from vkbottle.bot import BotLabeler
from vkbottle.bot import Message

from ..jewelry.catalog import catalog
from ..states import TryOnStates
from ..tryon.pipeline import TryOnError, apply_tryon
from ..vk_media import download_first_photo, upload_photo_for_message

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
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("Хорошо, отменила. Напишите название другого украшения.")
        return

    photo_bytes = await download_first_photo(message)
    if photo_bytes is None:
        await message.answer("Жду именно фото 🙂 Прикрепите снимок к сообщению (или напишите «отмена»).")
        return

    try:
        result_bytes = apply_tryon(item, catalog.image_path(item), photo_bytes)
    except TryOnError as exc:
        logger.info("Не удалось примерить %s: %s", item.id, exc)
        await message.answer(str(exc))
        return
    except Exception:
        logger.exception("Неожиданная ошибка примерки для %s", item.id)
        await message.answer("Не получилось обработать это фото. Попробуйте другое.")
        return

    try:
        attachment = await upload_photo_for_message(bot.api, result_bytes, message.peer_id)
        await message.answer(f"Вот как выглядит «{item.name}» 💍", attachment=attachment)
    except Exception:
        # Загрузка готового фото обратно в ВК — отдельный сетевой шаг (может
        # споткнуться о временный сбой VK API даже когда сама примерка уже
        # посчиталась). Без этого except бот падал молча и не отвечал вовсе,
        # плюс пользователь навсегда застревал в состоянии "жду фото".
        logger.exception("Не удалось отправить результат примерки для %s", item.id)
        await message.answer(
            "Примерка получилась, но не вышло отправить фото обратно 🙁 "
            "Попробуйте прислать это же фото ещё раз."
        )
        return

    await bot.state_dispenser.delete(message.peer_id)
