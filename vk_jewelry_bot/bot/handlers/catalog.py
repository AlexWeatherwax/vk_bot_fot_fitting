"""
Обработчик свободного текста: поиск украшения по названию и переход
в состояние ожидания фото. Регистрируется как catch-all, поэтому в
bot/app.py его нужно подключать ПОСЛЕДНИМ (после common и photo) —
иначе он перехватит на себя команды вроде "старт"/"каталог" и сообщения
пользователя, ожидающего фото.
"""
from vkbottle.bot import BotLabeler
from vkbottle.bot import Message

from ..jewelry.catalog import catalog
from ..jewelry.models import CATEGORY_TITLES, PHOTO_INSTRUCTIONS
from ..states import TryOnStates

catalog_labeler = BotLabeler()


@catalog_labeler.message()
async def search_handler(message: Message):
    query = (message.text or "").strip()
    if not query:
        return

    item, suggestions = catalog.find(query)

    if item is None:
        if suggestions:
            names = ", ".join(f"«{s.name}»" for s in suggestions)
            await message.answer(f"Не нашла точного совпадения. Возможно, вы имели в виду: {names}?")
        else:
            await message.answer(
                'Не нашла такое украшение в каталоге. Напишите "каталог", чтобы увидеть список.'
            )
        return

    # Локальный импорт, чтобы избежать циклической зависимости bot.app <-> bot.handlers.catalog
    from ..app import bot

    await bot.state_dispenser.set(message.peer_id, TryOnStates.WAITING_PHOTO, item_id=item.id)
    await message.answer(
        f"Отлично, примеряем «{item.name}» ({CATEGORY_TITLES[item.category]}).\n"
        f"{PHOTO_INSTRUCTIONS[item.category]}"
    )
