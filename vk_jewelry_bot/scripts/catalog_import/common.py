"""
Общие утилиты импорта локального каталога из папки «Украшения».

Главное, ради чего он существует:
- имена подпапок в исходной папке пришли в «кракозябрах» (байты CP866,
  прочитанные как MacCyrillic) — demojibake() возвращает нормальное название;
- нужен латинский slug для имени файла и id в manифесте — slugify();
- папки верхнего уровня («Серьги», «Кулоны 2», ...) нужно сопоставить
  категориям бота — CATEGORY_BY_FOLDER.
"""
from __future__ import annotations

import unicodedata

# Символы, которые реально встречаются в нормальных русских названиях товаров.
_PLAUSIBLE = set(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " -+()[].,!?:;/_&'\"«»№#%"
)


def demojibake(name: str) -> str:
    """
    Чинит имя папки/файла, если оно пришло как байты CP866, прочитанные
    как MacCyrillic (типичная порча при распаковке архива на macOS).

    Строку, в которой и так только «нормальные» символы, не трогаем:
    признак порчи — присутствие символов вроде † • ≠ ® Ѓ ™ ° ¶.
    """
    name = unicodedata.normalize("NFC", name)
    if all(ch in _PLAUSIBLE for ch in name):
        return name
    try:
        return unicodedata.normalize("NFC", name.encode("mac_cyrillic").decode("cp866"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


# Транслитерация в стиле уже существующих файлов каталога imladris
# («Кулон Гроза» -> kulon-groza, «серьги чёрные капли» -> sergi-chernye-kapli).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str) -> str:
    """«Кулон Гроза» -> 'kulon-groza'. Только [a-z0-9-]."""
    out = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum()):
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


# Папка верхнего уровня в «Украшения» -> категория примерки бота.
# None означает «картинку готовим, но в каталог пока не добавляем»:
# у бота нет подходящей точки крепления.
CATEGORY_BY_FOLDER: dict[str, str | None] = {
    "Серьги": "earrings",
    "Кулоны": "pendant",
    "Кулоны 2": "pendant",
    "Кольца": "ring",
    "Диадемы": "diadem",
    "Броши": "brooch",
    "Заколки": "hairpin",
    "браслеты": "bracelet",
    "Каффы": "kaffy",  # сидит на ушной раковине — своя точка крепления, не мочка
    "Наборы": None,    # комплект из нескольких предметов — примерка не определена
}

# Отдельные товары, для которых категория не выводится из папки.
# «Колье лесной дождь» лежит среди кулонов, но это колье (beads).
CATEGORY_BY_ITEM: dict[str, str] = {
    "Колье лесной дождь": "beads",
}


def category_for(section: str, title: str) -> str | None:
    if title in CATEGORY_BY_ITEM:
        return CATEGORY_BY_ITEM[title]
    return CATEGORY_BY_FOLDER.get(section)
