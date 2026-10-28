"""
Сопоставление товаров из папки «Украшения» с уже существующими записями
каталога (те 58, что раньше выгружались из группы ВК).

Таблица составлена вручную и сверена глазами по картинкам: автоматическое
сопоставление по названию здесь врёт. Например, в папке есть и заколка
«Гроза», и кулон «Гроза» — это разные изделия; «Каффы/лесное лето» — это
кафф, а не серьги «Лесное лето»; «Кулоны/кулон Ранняя осень» — не венец
«Ранняя Осень».

Ключ — (раздел, название) из папки, значение — id записи в manifest.json.
Товары, которых здесь нет, добавляются в каталог как новые.
"""

REPLACES: dict[tuple[str, str], str] = {
    ("Диадемы", "Зимние ягоды диадема+серьги"): "imladris_diadem_venets-diadema-zimnie-yagody-i-sergi",
    ("Диадемы", "Ранняя осень"): "imladris_diadem_venets-diadema-rannyaya-osen",
    ("Диадемы", "Течение"): "imladris_diadem_venets-techenie",

    ("Кольца", "особенное"): "imladris_ring_koltso-osobennoe",
    ("Кольца", "Лазурные воды"): "imladris_ring_koltso-lazurnye-vody",
    ("Кольца", "Парад планет"): "imladris_ring_koltso-parad-planet",
    ("Кольца", "Пески времени"): "imladris_ring_koltso-peski-vremeni",
    ("Кольца", "Свет луны"): "imladris_ring_koltso-svet-luny",

    ("Кулоны 2", "Вишневое дерево"): "imladris_pendant_kulon-vishnevoe-derevo",
    ("Кулоны 2", "Внутренняя сила"): "imladris_pendant_kulon-vnutrennyaya-sila",
    ("Кулоны 2", "Гроза"): "imladris_pendant_kulon-groza",
    ("Кулоны 2", "Зимний лес"): "imladris_pendant_kulon-zimniy-les",
    ("Кулоны 2", "Золотое сердце"): "imladris_pendant_kulon-zolotoe-serdtse",
    ("Кулоны 2", "Зеленая яшма"): "imladris_pendant_kulon-zelenaya-yashma",
    ("Кулоны 2", "Искристый"): "imladris_pendant_kulon-iskristyy",
    ("Кулоны 2", "Колье лесной дождь"): "imladris_beads_kole-lesnoy-dozhd",
    ("Кулоны 2", "Кулон с красной яшмой"): "imladris_pendant_kulon-s-krasnoy-yashmoy-pustynnaya-zmeyka",
    ("Кулоны 2", "Лавандовый лёд"): "imladris_pendant_kulon-lavandovyy-led",
    ("Кулоны 2", "Лаванда"): "imladris_pendant_kulon-lavanda",
    ("Кулоны 2", "Лесная тропинка"): "imladris_pendant_kulon-lesnaya-tropinka",
    ("Кулоны 2", "Мох"): "imladris_pendant_kulon-moh",
    ("Кулоны 2", "Небесный купол"): "imladris_pendant_kulon-nebesnyy-kupol",
    ("Кулоны 2", "Нежность"): "imladris_pendant_kulon-nezhnost",
    ("Кулоны 2", "Обещание"): "imladris_pendant_kulon-s-klubnichnym-kvartsem-obeshchanie",
    ("Кулоны 2", "Предание"): "imladris_pendant_kulon-predanie",
    ("Кулоны 2", "Снежный барбарис"): "imladris_pendant_kulon-snezhnyy-barbaris",
    ("Кулоны 2", "Тигр"): "imladris_pendant_kulon-tigr",
    ("Кулоны 2", "Туманность"): "imladris_pendant_kulon-tumannost",
    ("Кулоны 2", "Теплый янтарь"): "imladris_pendant_kulon-teplyy-yantar",
    ("Кулоны 2", "Хмель"): "imladris_pendant_kulon-hmel",
    ("Кулоны 2", "Шелковые травы"): "imladris_pendant_kulon-shelkovye-travy",
    ("Кулоны 2", "Это был зуб"): "imladris_pendant_kulon-eto-byl-zub",

    ("Серьги", "Лауреломэ"): "imladris_earrings_sergi-laurelome",
    ("Серьги", "Лесное лето"): "imladris_earrings_sergi-lesnoe-leto",
    ("Серьги", "Летнее солнце"): "imladris_earrings_sergi-letnee-solntse",
    ("Серьги", "Летнее море"): "imladris_earrings_sergi-letnee-more",
    ("Серьги", "Ночь"): "imladris_earrings_sergi-noch",
    ("Серьги", "Нежные"): "imladris_earrings_sergi-nezhnye",
    ("Серьги", "Прибой"): "imladris_earrings_sergi-priboy",
    ("Серьги", "Розовый лед"): "imladris_earrings_sergi-rozovyy-led",
    ("Серьги", "Серьги с капельками"): "imladris_earrings_sergi-s-kapelkami",
    ("Серьги", "Трикветр"): "imladris_earrings_sergi-trikvetr",
    ("Серьги", "Ягодные"): "imladris_earrings_sergi-yagodnye",
    ("Серьги", "Ясное небо"): "imladris_earrings_sergi-yasnoe-nebo",
    ("Серьги", "сложи камушки друг на друга"): "imladris_earrings_sergi-slozhi-kamushki-drug-na-druga",
    ("Серьги", "серьги с лабрадоритом2"): "imladris_earrings_sergi-s-labradoritom-2",
    ("Серьги", "серьги с агатом"): "imladris_earrings_sergi-s-agatom",
    ("Серьги", "серьги с нефритом"): "imladris_earrings_sergi-s-nefritom",
    ("Серьги", "серьги чёрно-золотые"): "imladris_earrings_sergi-cherno-zolotye",
    ("Серьги", "серьги чёрные капли"): "imladris_earrings_sergi-chernye-kapli",
    ("Серьги", "первая зелень"): "imladris_earrings_sergi-pervaya-zelen",
    ("Серьги", "цветение"): "imladris_earrings_sergi-tsvetenie"    ,
    ("Серьги", "морские"): "imladris_earrings_sergi-morskie",
}

# Как называть в каталоге новые товары: к названию папки спереди
# добавляется слово категории, если его там ещё нет.
NAME_PREFIX = {
    "earrings": "Серьги",
    "pendant": "Кулон",
    "ring": "Кольцо",
    "beads": "Колье",
    "diadem": "Венец (диадема)",
    "hairpin": "Заколка",
    "brooch": "Брошь",
    "bracelet": "Браслет",
    "kaffy": "Кафф",
}


# Слова, с которых название и так начинается «само» — тогда добавлять
# название категории спереди не нужно («Шпилька с яшмой», а не
# «Заколка шпилька с яшмой»).
SELF_NAMING = {
    "hairpin": ("заколка", "шпилька"),
    "brooch": ("брошь", "брошка"),
    "bracelet": ("браслет",),
    "earrings": ("серьги", "серёжки", "моносерьга", "кафф"),
    "pendant": ("кулон", "подвеска"),
    "ring": ("кольцо",),
    "beads": ("колье", "бусы"),
    "diadem": ("венец", "диадема"),
    "kaffy": ("кафф",),
}


def display_name(category: str, title: str) -> str:
    """Название для каталога: «ягоды» -> «Заколка Ягоды», но «шпилька с
    яшмой» остаётся «Шпилька с яшмой»."""
    title = title.strip()
    title = title[0].upper() + title[1:]
    lowered = title.lower()
    if any(lowered.startswith(w) for w in SELF_NAMING.get(category, ())):
        return title
    prefix = NAME_PREFIX.get(category)
    return f"{prefix} {title}" if prefix else title


# Поля записи каталога, которые нельзя вывести автоматически, — проставлены
# по внешнему виду выбранного кадра.
#
# chain_color: бот подрисовывает на шее свою цепочку под кулон; выбираем ту,
# что не спорит с металлом самого украшения ("gold" — латунь/медь/золото).
# pair_image: на картинке обе серьги пары. False там, где в кадр попала
# только одна — тогда бот сам отразит её на второе ухо.
ENTRY_OVERRIDES: dict[str, dict] = {
    "kulony__kulon-plamya":            {"chain_color": "gold"},
    "kulony__kulon-plamya-oseni":      {"chain_color": "gold"},
    "kulony__kulon-rannyaya-osen":     {"chain_color": "gold"},
    "kulony-2__amrot":                 {"chain_color": "gold"},
    "kulony-2__vishnevoe-derevo":      {"chain_color": "gold"},
    "kulony-2__vnutrennyaya-sila":     {"chain_color": "gold"},
    "kulony-2__zelenaya-yashma":       {"chain_color": "gold"},
    "kulony-2__iskristyy":             {"chain_color": "gold"},
    "kulony-2__kulon-s-krasnoy-yashmoy": {"chain_color": "gold"},
    "kulony-2__lesnaya-tropinka":      {"chain_color": "gold"},
    "kulony-2__nebesnyy-kupol":        {"chain_color": "gold"},
    "kulony-2__nezhnost":              {"chain_color": "gold"},
    "kulony-2__teplyy-yantar":         {"chain_color": "gold"},
    "kulony-2__finduilas":             {"chain_color": "gold"},
    "kulony-2__hmel":                  {"chain_color": "gold"},
    "kulony-2__shelkovye-travy":       {"chain_color": "gold"},
    "kulony-2__eto-byl-zub":           {"chain_color": "gold"},
    "kulony-2__zolotoe-serdtse":       {"chain_color": "gold"},

    # в кадр попала одна серьга из пары — бот отразит её на второе ухо
    "sergi__yasnoe-nebo":              {"pair_image": False},
    # перья двух серёг на кадре перекрываются, пару не разделить —
    # кадр обрезан до одной серьги, бот отразит её на второе ухо
    "sergi__letnee-solntse":           {"pair_image": False},

    # у колье концы на картинке обрезаны там, где оно уходит за шею, и бот
    # масштабирует его по ширине шеи — отдельная поправка не нужна
}
