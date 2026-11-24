"""Приветствие и навигация по категориям каталога."""
from vkbottle.bot import BotLabeler, Message

from ..jewelry.catalog import catalog
from ..jewelry.models import Category
from ..commands import CATALOG_WORDS, CATEGORY_COMMANDS, START_WORDS, command_key
from ..sessions import session_keyboard

common_labeler = BotLabeler()

CATEGORY_HEADINGS = {
    Category.EARRINGS: "Серьги", Category.PENDANT: "Кулоны",
    Category.RING: "Кольца", Category.BEADS: "Бусы",
    Category.DIADEM: "Диадемы", Category.HAIRPIN: "Заколки",
    Category.BROOCH: "Броши", Category.BRACELET: "Браслеты",
    Category.KAFFY: "Каффы", Category.SET: "Наборы",
}
WELCOME = (
    "Привет! Я бот-примерочная украшений 💎\n\n"
    "Напишите название украшения или готового набора из каталога "
    "(например «{example}»), и я подскажу, какое фото прислать.\n\n"
    "Готовые наборы примеряются на одном фото в фас или по частям — "
    "я попрошу отдельное фото для каждого ракурса. "
    "Остальные украшения примеряются по одному.\n\n"
    "«Каталог» — все украшения; «наборы» — готовые комплекты.\n"
    "«Позови мастера» — отметить диалог для мастера.\n"
    "«Отмена» — прервать текущую примерку.\n"
    "«Завершить примерку» — выключить бота и перейти к общению с владельцем.\n"
    "«Согласие» — условия обработки данных; «Отозвать согласие» — отозвать согласие."
)


@common_labeler.message(text=START_WORDS)
async def start_handler(message: Message):
    from ..app import bot, consent_gate, session_gate
    if await session_gate.intercept(bot, message, consent_gate):
        return
    if await consent_gate.intercept(bot, message):
        return
    await send_welcome(message)


async def send_welcome(message: Message):
    catalog.reload_if_changed()
    example = catalog.items[0].name if catalog.items else "Серьги Ягодные"
    await message.answer(WELCOME.format(example=example), keyboard=session_keyboard(True))


@common_labeler.message(text=CATALOG_WORDS + list(CATEGORY_COMMANDS))
async def catalog_list_handler(message: Message):
    from ..app import bot, consent_gate, session_gate
    if await session_gate.intercept(bot, message, consent_gate):
        return
    if await consent_gate.intercept(bot, message):
        return
    catalog.reload_if_changed()
    requested = CATEGORY_COMMANDS.get(command_key(message.text))
    items = [item for item in catalog.items if requested is None or item.category == requested]
    if not items:
        await message.answer("В этой категории пока нет украшений." if requested else "Каталог пока пуст.")
        return
    groups = []
    for category in Category:
        names = [f"— {item.name}" for item in items if item.category == category]
        if names:
            groups.append(CATEGORY_HEADINGS[category] + ":\n" + "\n".join(names))
    await message.answer(
        "\n\n".join(groups)
        + "\n\nДля примерки напишите одно название украшения или набора."
        + "\nЧтобы обратиться к мастеру, напишите «Позови мастера»."
    )
