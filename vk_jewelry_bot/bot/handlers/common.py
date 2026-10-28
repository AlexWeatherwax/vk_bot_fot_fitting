"""
Приветствие, помощь и список каталога — команды, не завязанные на состояние диалога.
"""
from vkbottle.bot import BotLabeler
from vkbottle.bot import Message

from ..jewelry.catalog import catalog
from ..jewelry.models import CATEGORY_TITLES

common_labeler = BotLabeler()

WELCOME = (
    "Привет! Я бот-примерочная украшений 💎\n\n"
    "Напишите название украшения из каталога (например «{example}»), "
    "и я подскажу, какое фото нужно прислать, чтобы виртуально его примерить.\n\n"
    "Команда «каталог» — список всех украшений.\n"
    "Команда «отмена» — прервать текущую примерку."
)


@common_labeler.message(text=["начать", "старт", "start", "привет", "hello"])
async def start_handler(message: Message):
    example = catalog.items[0].name if catalog.items else "Кольцо Роза"
    await message.answer(WELCOME.format(example=example))


@common_labeler.message(text=["каталог", "список", "help", "помощь"])
async def catalog_list_handler(message: Message):
    if not catalog.items:
        await message.answer("Каталог пока пуст.")
        return
    lines = [f"— {item.name} ({CATEGORY_TITLES[item.category]})" for item in catalog.items]
    await message.answer("Доступные украшения:\n" + "\n".join(lines))
