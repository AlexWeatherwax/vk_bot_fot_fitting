"""
Сборка бота: создаёт объект Bot и подключает обработчики.

Порядок bot.labeler.load(...) важен: обработчики проверяются в порядке
регистрации, и первый подошедший "забирает" сообщение себе. Поэтому:
1. photo_labeler   — самый специфичный (только пока пользователь в состоянии
                      "ждём фото"), должен проверяться первым;
2. common_labeler  — точные команды (старт/каталог/помощь);
3. catalog_labeler — catch-all для остального текста (поиск по названию),
                      должен идти последним.
"""
import logging

from vkbottle.bot import Bot

from .config import config
from .handlers.catalog import catalog_labeler
from .handlers.common import common_labeler
from .handlers.photo import photo_labeler

logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vk_jewelry_bot")

bot = Bot(token=config.vk_token)

bot.labeler.load(photo_labeler)
bot.labeler.load(common_labeler)
bot.labeler.load(catalog_labeler)


def run() -> None:
    logger.info("Бот запускается, group_id=%s", config.group_id)
    # run() сам поднимает asyncio-цикл и слушает Group Long Poll ВК —
    # отдельного сервера/вебхука/домена для этого не требуется.
    bot.run()
