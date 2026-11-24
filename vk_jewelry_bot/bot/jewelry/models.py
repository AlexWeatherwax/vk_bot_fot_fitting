"""
Модель украшения и справочная информация по категориям:
- человекочитаемое название категории;
- инструкция, какое фото просить у пользователя для этой категории.
"""
from dataclasses import dataclass, field
from enum import Enum
import math


class Category(str, Enum):
    EARRINGS = "earrings"   # серьги
    PENDANT = "pendant"     # кулон
    RING = "ring"           # кольцо
    BEADS = "beads"         # бусы
    DIADEM = "diadem"       # диадема
    HAIRPIN = "hairpin"     # заколка/шпилька
    BROOCH = "brooch"       # брошь
    BRACELET = "bracelet"   # браслет
    KAFFY = "kaffy"         # кафф (сидит на ушной раковине, а не на мочке)
    SET = "set"             # набор из нескольких отдельных украшений


CATEGORY_TITLES = {
    Category.EARRINGS: "серьги",
    Category.PENDANT: "кулон",
    Category.RING: "кольцо",
    Category.BEADS: "бусы",
    Category.DIADEM: "диадема",
    Category.HAIRPIN: "заколка",
    Category.BROOCH: "брошь",
    Category.BRACELET: "браслет",
    Category.KAFFY: "кафф",
    Category.SET: "набор",
}


def kaffy_photo_instruction(side: str) -> str:
    ear, position = ("правое", "справа") if side == "right" else ("левое", "слева")
    return (
        f"Для примерки откройте {ear} по кадру ухо — оно должно быть {position} "
        "на отправляемом фото. Уберите волосы от этого уха. "
        "Пришлите фото в три четверти: голова повёрнута примерно на 45°, "
        "лицо хорошо видно (не чистый профиль), хорошее освещение."
    )


# Что именно просим прислать пользователя для каждой категории украшений.
PHOTO_INSTRUCTIONS = {
    Category.EARRINGS: (
        "Пришлите чёткое селфи в фас (лицо прямо в камеру), уши открыты "
        "(волосы убраны назад), хорошее равномерное освещение."
    ),
    Category.PENDANT: (
        "Пришлите фото в фас по плечи — должны быть видны шея и зона декольте."
    ),
    Category.RING: (
        "Пришлите фото кисти крупным планом ТЫЛЬНОЙ стороной к камере "
        "(так, как видно кольцо на руке), пальцы слегка разведены, "
        "украшения с этой руки лучше снять."
    ),
    Category.BEADS: (
        "Пришлите фото в фас по плечи — шея и оба плеча должны быть в кадре."
    ),
    Category.DIADEM: (
        "Пришлите селфи в фас, лоб открыт (волосы убраны со лба), голова прямо."
    ),
    Category.HAIRPIN: (
        "Пришлите селфи в фас так, чтобы в кадр целиком попала макушка — "
        "заколка садится в волосы над лбом."
    ),
    Category.BROOCH: (
        "Пришлите фото в фас по грудь — должны быть видны оба плеча "
        "и верх груди, куда крепится брошь."
    ),
    Category.BRACELET: (
        "Пришлите фото руки крупным планом так, чтобы в кадр попали "
        "и кисть, и запястье."
    ),
    Category.KAFFY: kaffy_photo_instruction("left"),
    Category.SET: (
        "Пришлите фото в фас: голова прямо, уши и лоб открыты, "
        "хорошее равномерное освещение. Для набора с кулоном или бусами "
        "в кадре должны быть видны шея, плечи и зона декольте."
    ),
}


@dataclass
class JewelryItem:
    id: str
    name: str
    category: Category
    image: str              # имя файла PNG (RGBA, прозрачный фон) в bot/jewelry/gallery/
    anchor_scale: float = 1.0     # доп. коэффициент масштаба именно для этой картинки
    offset_x: float = 0.0         # доп. смещение по X, в долях ширины лица/руки/плеч
    offset_y: float = 0.0         # доп. смещение по Y, в тех же долях
    rotation_offset: float = 0.0  # доп. поворот в градусах (калибровка под конкретный арт)
    # Точка крепления внутри PNG, в долях его ширины и высоты.
    # None сохраняет стандартную точку категории для старых изображений.
    overlay_anchor: tuple[float, float] | None = None
    # Только для category=EARRINGS: True, если на картинке уже ОБА украшения
    # пары (как обычно и фотографируют серьги на продажу) — тогда бот вставляет
    # картинку целиком один раз между ушами, не отражая и не дублируя её.
    # False (по умолчанию) — на картинке одна серьга, бот сам отразит и
    # разместит по одной на каждое ухо.
    pair_image: bool = False
    # Для неравных серёг: отдельные крепления внутри каждой детали после
    # split_pair (левая и правая по PNG), без координат фотографии человека.
    pair_overlay_anchors: tuple[tuple[float, float], tuple[float, float]] | None = None
    # Только для category=EARRINGS и pair_image=False: True для несимметричных
    # моно-серёг (продаётся и носится одна серьга на одно ухо) — тогда бот
    # ставит её только на одно ухо, а не зеркалит на оба.
    single_ear: bool = False
    # Только для category=BROOCH: на какой стороне кадра носить брошь —
    # "left" или "right" (по умолчанию слева в кадре, то есть на правой
    # стороне груди человека, если фото не зеркальное).
    brooch_side: str = "left"
    # Только для category=PENDANT: каким цветом металла подрисовать цепочку
    # на шее под кулоном — "silver", "gold" или "none" (совсем без цепочки,
    # например если на самой картинке кулона уже достаточно видно подвес).
    chain_color: str = "silver"
    # Только для category=KAFFY: кафф — не пара, носится на одном ухе;
    # "left" или "right" — сторона кадра (по умолчанию слева на фото).
    # В зеркальном селфи анатомическая сторона может отличаться.
    kaffy_side: str = "left"
    # Только для category=KAFFY: доля высоты картинки (сверху), где на НЕЙ
    # самой находится гроздь бусин — та точка садится на мочку. По
    # умолчанию 0.8 подходит каффам без длинных подвесов (гроздь занимает
    # весь низ картинки); у каффов с цепочками-подвесами гроздь заканчивается
    # раньше — а на мочку должна сесть именно гроздь, а не кончик подвеса.
    kaffy_anchor_y: float = 0.8
    # Только для category=HAIRPIN: как носится эта конкретная заколка —
    # "updo" (по умолчанию) — вертикально, торчит из пучка на макушке;
    # "side" — горизонтально, воткнута сбоку, над ухом.
    hairpin_style: str = "updo"
    # Только для category=HAIRPIN при hairpin_style="side": на какую сторону
    # головы сажать — "left" или "right" (по умолчанию левая, по анатомии
    # человека, а не по стороне кадра).
    hairpin_side: str = "left"
    # Для bun: конец декоративной головки / начало скрываемого стержня,
    # в долях высоты исходного PNG. Координата относится к изделию, не к фото.
    hairpin_head_fraction: float | None = None
    # Последовательный набор примеряется по частям на отдельных фотографиях.
    tryon_mode: str = "combined"
    # Для category=SET: отдельные изделия со своими изображениями и
    # калибровкой. Общая картинка набора используется только в каталоге.
    components: list["JewelryItem"] = field(default_factory=list)


def item_photo_instruction(item: JewelryItem) -> str:
    if item.category == Category.KAFFY:
        return kaffy_photo_instruction(item.kaffy_side)
    if item.category == Category.HAIRPIN and item.hairpin_style == "bun":
        return (
            "Пришлите фото в три четверти с хорошо видимым боковым пучком. "
            "В кадре должны быть лицо и вся причёска; фон должен отличаться "
            "от волос. Шпилька вставляется в пучок, а стержень скрывается в волосах."
        )
    if item.category == Category.HAIRPIN and item.hairpin_style == "side":
        return (
            "Пришлите фото в три четверти: лицо, висок и волосы над ухом "
            "должны быть хорошо видны, причёска целиком в кадре."
        )
    return PHOTO_INSTRUCTIONS[item.category]


def item_from_dict(entry: dict) -> JewelryItem:
    """Загружает украшение или набор из манифеста / запроса worker."""
    data = dict(entry)
    data["category"] = Category(data["category"])
    mode = data.get("tryon_mode", "combined")
    if mode not in ("combined", "sequential"):
        raise ValueError("Неизвестный режим примерки.")
    if mode == "sequential" and data["category"] != Category.SET:
        raise ValueError("Последовательная примерка допустима только у набора.")
    anchor = data.get("overlay_anchor")
    if anchor is not None:
        if (not isinstance(anchor, (list, tuple)) or len(anchor) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) or not 0 <= v <= 1 for v in anchor)):
            raise ValueError("Точка крепления должна содержать две доли от 0 до 1.")
        data["overlay_anchor"] = tuple(float(v) for v in anchor)
    pair_anchors = data.get("pair_overlay_anchors")
    if pair_anchors is not None:
        if (data["category"] != Category.EARRINGS or not data.get("pair_image")
                or not isinstance(pair_anchors, (list, tuple)) or len(pair_anchors) != 2):
            raise ValueError("Отдельные точки крепления допустимы только для пары серёг.")
        for point in pair_anchors:
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or not 0 <= v <= 1 for v in point)):
                raise ValueError("Точки крепления пары должны быть долями от 0 до 1.")
        data["pair_overlay_anchors"] = tuple(tuple(float(v) for v in p) for p in pair_anchors)
    head = data.get("hairpin_head_fraction")
    if head is not None:
        if (isinstance(head, bool) or not isinstance(head, (int, float))
                or not math.isfinite(head) or not 0 < head < 1):
            raise ValueError("Граница головки шпильки должна быть долей между 0 и 1.")
        if data["category"] != Category.HAIRPIN:
            raise ValueError("Граница головки допустима только для заколки.")
    raw_components = data.pop("components", [])
    if not isinstance(raw_components, list):
        raise ValueError("Компоненты набора должны быть списком.")
    if data["category"] == Category.SET:
        if len(raw_components) < 2:
            raise ValueError("У набора должно быть хотя бы два украшения для примерки.")
        if any(Category(part["category"]) == Category.SET for part in raw_components):
            raise ValueError("Набор не может содержать другой набор.")
    elif raw_components:
        raise ValueError("Компоненты допустимы только у набора.")
    data["components"] = [item_from_dict(part) for part in raw_components]
    return JewelryItem(**data)
