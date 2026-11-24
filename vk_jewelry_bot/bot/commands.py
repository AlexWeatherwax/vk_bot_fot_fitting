"""Whole-message commands; product names are never normalized through aliases."""
import re
import unicodedata

from .jewelry.models import Category


START_WORDS = ["начать", "старт", "start", "привет", "hello"]
CATALOG_WORDS = ["каталог", "список", "help", "помощь"]
CANCEL_WORDS = {"отмена", "cancel", "стоп", "стой"}
RESET_WORDS = {"сброс", "очистить"}
SESSION_START_WORDS = {"начать", "старт", "start"}
SESSION_FINISH_COMMAND = "завершить примерку"
CATEGORY_COMMANDS = {
    "серьги": Category.EARRINGS,
    "кулоны": Category.PENDANT, "кулон": Category.PENDANT,
    "кольца": Category.RING, "кольцо": Category.RING,
    "бусы": Category.BEADS, "колье": Category.BEADS,
    "диадемы": Category.DIADEM, "диадема": Category.DIADEM,
    "заколки": Category.HAIRPIN, "заколка": Category.HAIRPIN,
    "броши": Category.BROOCH, "брошь": Category.BROOCH,
    "браслеты": Category.BRACELET, "браслет": Category.BRACELET,
    "каффы": Category.KAFFY, "кафф": Category.KAFFY,
    "наборы": Category.SET, "набор": Category.SET,
}

_KEYS = (set(START_WORDS) | set(CATALOG_WORDS) | set(CATEGORY_COMMANDS)
         | CANCEL_WORDS | RESET_WORDS
         | {"добавить", "убрать", "примерить", "позови мастера",
            "согласие", "условия", "конфиденциальность", "отозвать согласие",
            SESSION_FINISH_COMMAND})
_ALIASES = {key: key for key in _KEYS}
_ALIASES.update({
    "catalog": "каталог", "catalogue": "каталог", "katalog": "каталог",
    "каталоги": "каталог", "каталога": "каталог", "католог": "каталог",
    "каталок": "каталог", "каталлог": "каталог", "каталогг": "каталог",
    "меню": "каталог", "menu": "каталог",
    "покажи каталог": "каталог", "показать каталог": "каталог",
    "открой каталог": "каталог", "открыть каталог": "каталог",
    "посмотреть каталог": "каталог", "каталог украшений": "каталог",
    "здравствуйте": "привет", "здравствуй": "привет",
    "отменить": "отмена", "сбросить": "сброс",
    "серги": "серьги", "серьга": "серьги",
    "кафы": "каффы", "каф": "кафф",
    "политика конфиденциальности": "конфиденциальность",
    "закончить примерку": SESSION_FINISH_COMMAND,
    "завершить": SESSION_FINISH_COMMAND, "закончить": SESSION_FINISH_COMMAND,
    "выйти из примерки": SESSION_FINISH_COMMAND, "finish": SESSION_FINISH_COMMAND,
})
_WRONG_LAYOUT = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
    "йцукенгшщзхъфывапролджэячсмитьбю",
)
_ITEM_COMMAND = re.compile(r"^/?(добавить|убрать|примерить)\s+(.+)$", re.I | re.S)


def item_command(text: str | None):
    """Parse a command prefix while keeping the product argument intact."""
    return _ITEM_COMMAND.match(unicodedata.normalize("NFKC", text or "").strip())


def normalize_command(text: str | None) -> str:
    value = " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())
    value = value.replace("ё", "е")
    # Quotes, /commands and trailing punctuation are UI decoration. Internal
    # punctuation/words are preserved, especially negation and product names.
    start, end = 0, len(value)
    while start < end and (value[start].isspace() or unicodedata.category(value[start]).startswith("P")):
        start += 1
    while end > start and (value[end-1].isspace() or unicodedata.category(value[end-1]).startswith("P")):
        end -= 1
    return value[start:end]


def command_key(text: str | None) -> str:
    value = normalize_command(text)
    if value in _ALIASES:
        return _ALIASES[value]
    # Correct a wrong keyboard layout only for an entire known command.
    # Never transliterate a product query or accept consent via a text alias.
    raw = " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())
    translated = normalize_command(raw.translate(_WRONG_LAYOUT))
    return _ALIASES.get(translated, value)
