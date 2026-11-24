"""Приём фото текущего шага и редактирование выбора перед примеркой."""
import asyncio
import logging

from vkbottle.bot import BotLabeler, Message

from ..jewelry.catalog import catalog
from ..jewelry.selection import current_photo_step, photo_instructions, photo_steps
from ..states import TryOnStates
from ..commands import command_key, item_command
from ..tryon.service import TryOnError, apply_tryon_many
from ..vk_media import PhotoDownloadError, download_first_photo, upload_photo_for_message
from .catalog import CANCEL_WORDS, RESET_WORDS, search_handler, selected_items
from .common import CATALOG_WORDS, CATEGORY_COMMANDS, START_WORDS, catalog_list_handler, start_handler
from .master import is_master_request, request_master

photo_labeler = BotLabeler()
logger = logging.getLogger("vk_jewelry_bot.photo")
# Только снимки состояния: изображения и результаты живут внутри одного запроса.
# Второе фото того же шага не должно запустить параллельную отправку результата.
_active_photos = {}


async def _is_current(bot, message, payload, session_token):
    from ..app import consent_gate, session_gate
    latest = await bot.state_dispenser.get(message.peer_id)
    return (latest is not None and latest.payload == payload
            and consent_gate.is_allowed(message)
            and session_gate.is_current(message, session_token))


@photo_labeler.message(state=TryOnStates.WAITING_PHOTO)
async def photo_handler(message: Message):
    from ..app import bot, consent_gate, session_gate

    if await session_gate.intercept(bot, message, consent_gate):
        return
    session_token = session_gate.current_token(message)

    if is_master_request(message.text):
        await request_master(bot, message)
        return
    if await consent_gate.intercept(bot, message):
        return
    text = command_key(message.text)
    if (text in CANCEL_WORDS | RESET_WORDS | {"добавить", "убрать", "примерить"}
            or item_command(message.text) is not None):
        await search_handler(message)
        return
    if text in CATALOG_WORDS or text in CATEGORY_COMMANDS:
        await catalog_list_handler(message)
        return
    if text in START_WORDS:
        await start_handler(message)
        return

    state = await bot.state_dispenser.get(message.peer_id)
    # Пользователь может изменить выбор или отменить его во время обработки.
    payload = dict(state.payload) if state else {}
    try:
        items = selected_items(state)
        step_index = payload.get("step_index", 0)
        render_items = current_photo_step(items, step_index)
        steps = photo_steps(items[0])
    except ValueError as exc:
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer(str(exc))
        return

    try:
        photo_bytes = await download_first_photo(message)
    except PhotoDownloadError as exc:
        logger.info("Не удалось скачать фото для примерки: %s", exc)
        if await _is_current(bot, message, payload, session_token):
            await message.answer(str(exc))
        return
    except Exception:
        logger.exception("Неожиданная ошибка загрузки фото для примерки")
        if await _is_current(bot, message, payload, session_token):
            await message.answer("Не удалось загрузить фото. Попробуйте прислать его ещё раз.")
        return

    if not await _is_current(bot, message, payload, session_token):
        return
    if photo_bytes is None:
        if text:
            await search_handler(message)
        else:
            await message.answer("Прикрепите фото для примерки. Можно выбрать другое украшение или набор по названию. Для отмены напишите «отмена».")
        return

    if _active_photos.get(message.peer_id) == payload:
        await message.answer("Предыдущее фото ещё обрабатывается. Дождитесь результата примерки.")
        return
    _active_photos[message.peer_id] = payload
    try:
        await _render_step(bot, message, items, render_items, steps, step_index, payload, photo_bytes, session_token)
    finally:
        if _active_photos.get(message.peer_id) is payload:
            del _active_photos[message.peer_id]


async def _render_step(bot, message, items, render_items, steps, step_index, payload, photo_bytes, session_token):
    ids = ", ".join(item.id for item in render_items)
    try:
        result_bytes = await asyncio.to_thread(
            apply_tryon_many, render_items,
            [catalog.image_path(item) for item in render_items], photo_bytes,
        )
    except TryOnError as exc:
        logger.info("Не удалось примерить %s: %s", ids, exc)
        if await _is_current(bot, message, payload, session_token):
            await message.answer(str(exc))
        return
    except Exception:
        logger.exception("Неожиданная ошибка примерки для %s", ids)
        if await _is_current(bot, message, payload, session_token):
            await message.answer("Не получилось обработать это фото. Попробуйте другое.")
        return

    if not await _is_current(bot, message, payload, session_token):
        return
    try:
        attachment = await upload_photo_for_message(bot.api, result_bytes, message.peer_id)
        if not await _is_current(bot, message, payload, session_token):
            return
        result_items = render_items if len(steps) > 1 else items
        names = " + ".join(f"«{item.name}»" for item in result_items)
        text = f"Вот как выглядит {names} 💍"
        next_step = step_index + 1
        if next_step < len(steps):
            text += "\n\nПродолжим примерку набора.\n" + photo_instructions(items, next_step)
        await message.answer(text, attachment=attachment)
    except Exception:
        logger.exception("Не удалось отправить результат примерки для %s", ids)
        if await _is_current(bot, message, payload, session_token):
            await message.answer("Примерка получилась, но не вышло отправить фото обратно 🙁 Попробуйте прислать это же фото ещё раз.")
        return

    if await _is_current(bot, message, payload, session_token):
        if next_step < len(steps):
            await bot.state_dispenser.set(
                message.peer_id, TryOnStates.WAITING_PHOTO,
                **{**payload, "step_index": next_step},
            )
        else:
            await bot.state_dispenser.delete(message.peer_id)
