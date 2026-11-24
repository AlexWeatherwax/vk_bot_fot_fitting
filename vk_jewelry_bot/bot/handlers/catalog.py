"""Выбор одного украшения или готового набора перед отправкой фото."""
import re
from uuid import uuid4

from vkbottle.bot import BotLabeler, Message

from ..jewelry.catalog import catalog
from ..jewelry.models import CATEGORY_TITLES, JewelryItem
from ..jewelry.selection import photo_instructions, validate_selection
from ..states import TryOnStates
from ..commands import CANCEL_WORDS, RESET_WORDS, command_key, item_command
from .master import is_master_request, request_master

catalog_labeler = BotLabeler()
SETS_ONLY = (
    "Совместная примерка доступна только для готовых наборов. "
    "Напишите «наборы» и выберите один комплект. "
    "Остальные украшения примеряются по одному."
)


def selected_items(state) -> list[JewelryItem]:
    """Читает также состояние одиночной примерки предыдущей версии бота."""
    if state is None:
        return []
    catalog.reload_if_changed()
    ids = state.payload.get("item_ids")
    if ids is None:
        ids = [state.payload["item_id"]] if state.payload.get("item_id") else []
    by_id = {item.id: item for item in catalog.items}
    if any(item_id not in by_id for item_id in ids):
        raise ValueError("Каталог изменился. Выберите украшение или набор заново.")
    return [by_id[item_id] for item_id in ids]


async def describe_selection(message: Message, items: list[JewelryItem]) -> None:
    item = items[0]
    await message.answer(
        f"Примеряем «{item.name}» ({CATEGORY_TITLES[item.category]}).\n"
        f"{photo_instructions(items)}\n\n"
        "Чтобы сменить выбор, напишите название другого украшения или набора. "
        "Для отмены напишите «отмена»."
    )


@catalog_labeler.message()
async def search_handler(message: Message):
    from ..app import bot, consent_gate, session_gate

    if await session_gate.intercept(bot, message, consent_gate):
        return

    query = (message.text or "").strip()
    if is_master_request(query):
        await request_master(bot, message)
        return
    if await consent_gate.intercept(bot, message):
        return
    if not query:
        return
    lowered = command_key(query)
    # Common labeler's exact text rules do not catch case/spacing/alias
    # variants. Dispatch them before fuzzy product search, in every state.
    from .common import (CATALOG_WORDS, CATEGORY_COMMANDS, START_WORDS,
                         catalog_list_handler, start_handler)
    if lowered in START_WORDS:
        await start_handler(message)
        return
    if lowered in CATALOG_WORDS or lowered in CATEGORY_COMMANDS:
        await catalog_list_handler(message)
        return
    if lowered in CANCEL_WORDS | RESET_WORDS:
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("Примерка сброшена. Напишите название украшения, набора или «каталог».")
        return

    command = item_command(query)
    if lowered == "добавить" or (command and command.group(1).casefold() == "добавить"):
        await message.answer(SETS_ONLY)
        return
    if lowered == "убрать" or (command and command.group(1).casefold() == "убрать"):
        state = await bot.state_dispenser.get(message.peer_id)
        try:
            current = selected_items(state)
        except ValueError as exc:
            await bot.state_dispenser.delete(message.peer_id)
            await message.answer(str(exc))
            return
        name = command.group(2).strip().strip('«»"') if command else ""
        if name and (not current or name.casefold() not in current[0].name.casefold()):
            await message.answer("Такое украшение сейчас не выбрано. Для отмены примерки напишите «отмена».")
            return
        await bot.state_dispenser.delete(message.peer_id)
        await message.answer("Выбор очищен. Выберите украшение или готовый набор.")
        return
    query = command.group(2).strip() if command else query
    query = query.strip('«»"')

    # Не разделяем названия по «и»: это часть названия «Зимние ягоды и серьги».
    catalog.reload_if_changed()
    exact_name = any(item.name.casefold() == query.casefold() for item in catalog.items)
    if not exact_name and re.search(r"[+;\n]", query):
        await message.answer(SETS_ONLY)
        return
    item, suggestions = catalog.find(query)
    if item is None:
        if suggestions:
            names = ", ".join(f"«{item.name}»" for item in suggestions)
            await message.answer(f"Не нашла точного совпадения. Возможно, вы имели в виду: {names}?")
        else:
            await message.answer('Не нашла такое украшение в каталоге. Напишите «каталог», чтобы увидеть список.')
        return

    try:
        validate_selection([item])
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await bot.state_dispenser.set(
        message.peer_id, TryOnStates.WAITING_PHOTO,
        item_ids=[item.id], selection_token=uuid4().hex, step_index=0,
    )
    await describe_selection(message, [item])
