"""
Основной конвейер примерки: по категории украшения выбирает нужный детектор
(лицо / плечи / рука), считает точку крепления, масштаб и поворот, и
накладывает картинку украшения через compose.overlay_image.
"""
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..jewelry.models import Category, JewelryItem
from . import landmarks_face as face_mod
from . import landmarks_hand as hand_mod
from . import landmarks_pose as pose_mod
from .compose import overlay_image


class TryOnError(Exception):
    """Ожидаемая ошибка примерки (например, не найдено лицо/рука) — текст
    этого исключения можно безопасно показать пользователю."""


ALPHA_CLEAN_THRESHOLD = 160  # ниже этого считаем "фон", а не мягкий край объекта

# Размеры украшений заданы долей от характерного размера тела и подобраны по
# калибровочным фото (scripts/catalog_import/7_calibrate_preview.py).
# Считаем по ДЛИННОЙ стороне картинки, а не по ширине: украшение на фото может
# лежать и вдоль, и поперёк кадра, а его настоящий размер от этого не меняется.
EARRING_LENGTH_FRACTION = 0.34   # длина серьги / расстояние между ушами
# Во сколько раз крупнее одной серьги ставить нерасщепимую пару: на картинке
# их две рядом, поэтому по длинной стороне она примерно вдвое больше.
PAIR_FALLBACK_FACTOR = 1.9
HAIRPIN_LENGTH_FRACTION = 0.55   # длина заколки / расстояние между ушами
# Было 0.40 — по просьбе заказчика уменьшено вдвое (брошь читалась крупнее,
# чем должна).
BROOCH_LENGTH_FRACTION = 0.20    # длина броши / ширина плеч
# Было 0.13 — на пробных фото кулон читался как точка на груди, почти не
# виден. Увеличено вдвое по просьбе заказчика; не проверено на калибровочных
# фото — прогоните 7_calibrate_preview.py pendant и поправьте при необходимости.
PENDANT_LENGTH_FRACTION = 0.24   # длина подвеса / ширина плеч
# Насколько ниже точки шеи висит кулон (доли ширины плеч): на цепочке он
# лежит на груди, а не под подбородком. Замерено по калибровочным фото.
PENDANT_DROP = 0.30
CHAIN_WIDTH_FRACTION = 0.32      # ширина цепочки / ширина плеч ≈ ширина шеи
# Колье масштабируется по ширине шеи, а не плеч: тогда его концы приходятся
# на края шеи и читаются как уходящие за неё.
BEADS_NECK_OVERSHOOT = 1.15
# Ширина картинки кольца приравнивается к ширине пальца. Смысл именно такой:
# кольцо снято надетым на палец, и дужка на кадре обрывается ровно там, где
# уходит за палец. Если ширину картинки совместить с шириной пальца клиента,
# обрывы дужки лягут на края пальца — и кольцо читается как надетое, а не
# как наклейка поверх руки.
RING_WIDTH_FRACTION = 1.0        # ширина картинки кольца / ширина пальца
BRACELET_LENGTH_FRACTION = 1.15  # длина браслета / ширина запястья
# Длина каффа (от завитка вверху раковины до низа подвеса) / ширина лица.
# Проверено на живом калибровочном фото (7_calibrate_preview.py kaffy) —
# смотрится правдоподобно на всех 9, но не проверено на разных типах ушей/
# причёсок за пределами одного калибровочного фото.
KAFFY_LENGTH_FRACTION = 0.32


def _width_for_length(overlay: Image.Image, target_length: float) -> float:
    """
    Переводит «нужная длина украшения» в «нужная ширина картинки» — то, что
    принимает overlay_image. Длинная сторона картинки становится равна
    target_length, пропорции сохраняются.
    """
    longest = max(overlay.width, overlay.height)
    if longest == 0:
        return target_length
    return target_length * overlay.width / longest


def _load_rgba(path: Path) -> Image.Image:
    """Загружает PNG украшения и обнуляет остаточный "туман" — слабую
    полупрозрачность (альфа 1-25), которая иногда остаётся после
    автоматического удаления фона по всей площади картинки. Один такой
    пиксель незаметен, но когда картинку растягивают на большую ширину
    (например, серьги-пара — на всё расстояние между ушами), этот туман
    растягивается вместе с ней и виден как лёгкое потемнение прямоугольником
    поверх лица."""
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    low_alpha = arr[:, :, 3] < ALPHA_CLEAN_THRESHOLD
    arr[low_alpha, 3] = 0
    return Image.fromarray(arr, "RGBA")


def _to_bgr(pil_image: Image.Image) -> np.ndarray:
    rgb = np.array(pil_image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def apply_tryon(item: JewelryItem, overlay_path: Path, base_image_bytes: bytes) -> bytes:
    """
    Накладывает украшение item (файл overlay_path) на фото пользователя
    (base_image_bytes — сырые байты JPEG/PNG). Возвращает JPEG-байты результата.

    Бросает TryOnError с понятным пользователю текстом, если нужные части
    тела не удалось найти на фото.
    """
    base = Image.open(io.BytesIO(base_image_bytes))
    # На всякий случай учитываем EXIF-ориентацию с телефонов.
    base = _apply_exif_orientation(base).convert("RGB")
    np_bgr = _to_bgr(base)
    overlay_img = _load_rgba(overlay_path)

    if item.category == Category.EARRINGS:
        base = _apply_earrings(base, overlay_img, np_bgr, item)
    elif item.category == Category.DIADEM:
        base = _apply_diadem(base, overlay_img, np_bgr, item)
    elif item.category in (Category.PENDANT, Category.BEADS):
        base = _apply_neck_item(base, overlay_img, np_bgr, item)
    elif item.category == Category.RING:
        base = _apply_ring(base, overlay_img, np_bgr, item)
    elif item.category == Category.HAIRPIN:
        base = _apply_hairpin(base, overlay_img, np_bgr, item)
    elif item.category == Category.BROOCH:
        base = _apply_brooch(base, overlay_img, np_bgr, item)
    elif item.category == Category.BRACELET:
        base = _apply_bracelet(base, overlay_img, np_bgr, item)
    elif item.category == Category.KAFFY:
        base = _apply_kaffy(base, overlay_img, np_bgr, item)
    else:  # pragma: no cover - защитная ветка на случай новой категории
        raise TryOnError("Неизвестная категория украшения.")

    out = io.BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def _apply_exif_orientation(image: Image.Image) -> Image.Image:
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(image)
    except Exception:
        return image



_PAIR_CACHE: dict[tuple[str, tuple[int, int]], tuple[Image.Image, Image.Image] | None] = {}


def split_pair(overlay: Image.Image, cache_key: str | None = None):
    """
    Режет картинку с парой серёг на две отдельные серьги (левая/правая по кадру).

    Серьги фотографируют парой, и лежат они в кадре гораздо ближе друг к
    другу и в другом масштабе, чем уши на лице: если вставить такую картинку
    целиком, серьги садятся на щёки и получаются вдвое крупнее нужного.
    Поэтому пару разбираем на две детали и каждую сажаем на своё ухо — как
    одиночную серьгу, только без зеркалирования (пара бывает несимметричной).

    Возвращает None, если двух отдельных деталей не видно (серьги на картинке
    соприкасаются) — тогда вызывающий код работает по-старому, целой картинкой.
    """
    key = (cache_key or "", overlay.size)
    if key in _PAIR_CACHE:
        return _PAIR_CACHE[key]

    result = None
    alpha = np.array(overlay.split()[-1])
    mask = alpha >= 128
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    parts = sorted(((int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)), reverse=True)
    arr = np.array(overlay)

    def crop_by(condition):
        piece = arr.copy()
        piece[:, :, 3] = np.where(condition, piece[:, :, 3], 0)
        img = Image.fromarray(piece, "RGBA")
        bbox = img.split()[-1].getbbox()
        return img.crop(bbox) if bbox else img

    # Обычный случай: две серьги — две отдельные связные области. Вторая
    # должна быть сопоставима по площади с первой, иначе это не серьга, а
    # обрывок маски.
    if len(parts) >= 2 and parts[1][0] >= parts[0][0] * 0.30:
        a, b = parts[0][1], parts[1][1]
        if centroids[a][0] > centroids[b][0]:
            a, b = b, a  # a — левая по кадру, b — правая
        result = (crop_by(labels == a), crop_by(labels == b))
    elif parts:
        # Серьги на картинке соприкасаются и слились в одну область — тогда
        # ищем «долину»: столбец пикселей, где непрозрачного меньше всего.
        # Между двумя висящими серьгами такой просвет обычно есть, даже если
        # где-то сверху их соединяет остаток крепления.
        columns = mask.sum(axis=0)
        width = overlay.width
        lo, hi = int(width * 0.30), int(width * 0.70)
        if hi > lo:
            cut = lo + int(np.argmin(columns[lo:hi]))
            filled = columns[columns > 0]
            # Долина считается настоящей, только если она заметно тоньше
            # средней колонки: иначе серьги перекрываются, и резать нельзя.
            if filled.size and columns[cut] <= filled.mean() * 0.35:
                xs = np.arange(width)[None, :]
                result = (crop_by(xs < cut), crop_by(xs >= cut))

    _PAIR_CACHE[key] = result
    return result


def _apply_earrings(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = face_mod.get_face_anchors(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла лицо на фото 🙁 Пришлите чёткое селфи анфас, "
            "с открытыми ушами и хорошим освещением."
        )

    target_length = anchors.face_width * EARRING_LENGTH_FRACTION * item.anchor_scale
    pair = split_pair(overlay_img, item.image) if item.pair_image else None

    if pair is not None:
        # На картинке обе серьги пары — каждую сажаем на своё ухо как есть,
        # без зеркалирования (пара бывает несимметричной).
        sides = ((-1, anchors.left_lobe, pair[0]), (1, anchors.right_lobe, pair[1]))
    elif item.pair_image:
        # Пара не разбирается даже по долине — серьги на картинке
        # перекрываются. Вставляем картинку целиком между ушами, но по
        # размеру одной серьги на две: иначе пара растягивается на всю
        # ширину лица и ложится поперёк носа.
        mid = (
            (anchors.left_lobe[0] + anchors.right_lobe[0]) / 2,
            (anchors.left_lobe[1] + anchors.right_lobe[1]) / 2,
        )
        return overlay_image(
            base,
            overlay_img,
            (mid[0] + anchors.face_width * item.offset_x,
             mid[1] + anchors.face_width * item.offset_y),
            _width_for_length(overlay_img, target_length * PAIR_FALLBACK_FACTOR),
            anchors.tilt_angle + item.rotation_offset,
            overlay_anchor=(0.5, 0.05),
        )
    elif item.single_ear:
        # Несимметричная моно-серьга — только одно ухо, без зеркалирования.
        sides = ((-1, anchors.left_lobe, overlay_img),)
    else:
        mirrored = overlay_img.transpose(Image.FLIP_LEFT_RIGHT)
        sides = (
            (-1, anchors.left_lobe, overlay_img),
            (1, anchors.right_lobe, mirrored),
        )

    for side, point, ov in sides:
        ox = point[0] + anchors.face_width * item.offset_x * side
        oy = point[1] + anchors.face_width * item.offset_y
        base = overlay_image(
            base,
            ov,
            (ox, oy),
            _width_for_length(ov, target_length),
            anchors.tilt_angle + item.rotation_offset,
            overlay_anchor=(0.5, 0.05),  # верх картинки — крючок серьги
        )
    return base


def _apply_kaffy(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = face_mod.get_face_anchors(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла лицо на фото 🙁 Пришлите фото в профиль или в три "
            "четверти с открытым ухом и хорошим освещением."
        )

    side = -1 if item.kaffy_side != "right" else 1
    # Самая украшенная часть каффа (гроздь бусин, низ картинки) садится на
    # мочку — ту же точку, что и серьга; дужка сама уходит вверх на
    # раковину, раз крепится выше низа картинки. Мочка уже откалибрована
    # по калибровочным фото (_LOBE_DOWN/_LOBE_OUT) — надёжнее, чем отдельная
    # точка для каффа (пробовали, см. landmarks_face.py).
    point = anchors.left_lobe if side == -1 else anchors.right_lobe
    target_length = anchors.face_width * KAFFY_LENGTH_FRACTION * item.anchor_scale

    ox = point[0] + anchors.face_width * item.offset_x * side
    oy = point[1] + anchors.face_width * item.offset_y
    return overlay_image(
        base,
        overlay_img,
        (ox, oy),
        _width_for_length(overlay_img, target_length),
        anchors.tilt_angle + item.rotation_offset,
        # Доля высоты картинки, где на этой конкретной картинке гроздь —
        # см. JewelryItem.kaffy_anchor_y. У каффов с длинными подвесами на
        # цепочках гроздь заканчивается заметно раньше низа картинки; общая
        # доля 0.8 на них садила на мочку подвеску, а не гроздь.
        overlay_anchor=(0.5, item.kaffy_anchor_y),
    )


def _apply_diadem(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = face_mod.get_face_anchors(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла лицо на фото 🙁 Пришлите селфи анфас с открытым лбом."
        )

    width = anchors.face_width * 1.05 * item.anchor_scale
    point = (
        anchors.forehead_top[0] + anchors.face_width * item.offset_x,
        anchors.forehead_top[1] + anchors.face_width * item.offset_y,
    )
    return overlay_image(
        base,
        overlay_img,
        point,
        width,
        anchors.tilt_angle + item.rotation_offset,
        overlay_anchor=(0.5, 0.9),  # низ картинки — основание диадемы
    )


def _apply_hairpin(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = face_mod.get_face_anchors(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла лицо на фото 🙁 Пришлите селфи анфас, чтобы в кадр "
            "целиком попала макушка."
        )

    target_length = anchors.face_width * HAIRPIN_LENGTH_FRACTION * item.anchor_scale

    if item.hairpin_style == "side":
        side = -1 if item.hairpin_side != "right" else 1
        temple = anchors.left_temple if side == -1 else anchors.right_temple
        point = (
            temple[0] + anchors.face_width * item.offset_x * side,
            temple[1] + anchors.face_width * item.offset_y,
        )
        # Ближний к лицу край картинки — на виске; сама заколка уходит
        # наружу, в волосы сбоку.
        overlay_anchor = (1.0, 0.5) if side == -1 else (0.0, 0.5)
    else:
        point = (
            anchors.head_top[0] + anchors.face_width * item.offset_x,
            anchors.head_top[1] + anchors.face_width * item.offset_y,
        )
        # Низ картинки — у линии волос (там, где стержень уходит в причёску),
        # сама заколка/головка торчит вверх, над макушкой. ПРИБЛИЖЕНИЕ:
        # пробовали 0.5 (садилось на лоб) и 0.85 (улетало в воздух над
        # головой на фото с гладко зачёсанными волосами). 0.6 — компромисс,
        # но он одинаков для всех картинок независимо от пропорций, а у
        # длинных тонких шпилек (почти весь кадр — стержень, головка мала)
        # даже на 0.6 стержень заметно торчит в воздух. Для них нужна
        # отдельная подстройка offset_y в manifest.json — не проверено.
        overlay_anchor = (0.5, 0.6)

    return overlay_image(
        base,
        overlay_img,
        point,
        _width_for_length(overlay_img, target_length),
        anchors.tilt_angle + item.rotation_offset,
        overlay_anchor=overlay_anchor,
    )


def _apply_brooch(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = pose_mod.get_neck_anchor(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла плечи на фото 🙁 Пришлите фото анфас по грудь, "
            "чтобы были видны оба плеча."
        )

    side = item.brooch_side if item.brooch_side in anchors.brooch_points else "left"
    anchor_point = anchors.brooch_points[side]
    point = (
        anchor_point[0] + anchors.shoulder_width * item.offset_x,
        anchor_point[1] + anchors.shoulder_width * item.offset_y,
    )
    return overlay_image(
        base,
        overlay_img,
        point,
        _width_for_length(overlay_img, anchors.shoulder_width * BROOCH_LENGTH_FRACTION * item.anchor_scale),
        anchors.tilt_angle + item.rotation_offset,
        overlay_anchor=(0.5, 0.5),
    )


def _apply_bracelet(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = hand_mod.get_wrist_anchor(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла руку на фото 🙁 Пришлите фото руки крупным планом, "
            "чтобы в кадр попали и кисть, и запястье."
        )

    width = _width_for_length(
        overlay_img, anchors.wrist_width * BRACELET_LENGTH_FRACTION * item.anchor_scale
    )
    point = (
        anchors.point[0] + anchors.wrist_width * item.offset_x,
        anchors.point[1] + anchors.wrist_width * item.offset_y,
    )
    return overlay_image(
        base,
        overlay_img,
        point,
        width,
        anchors.angle + item.rotation_offset,
        overlay_anchor=(0.5, 0.5),
    )


_CHAIN_CACHE: dict[str, Image.Image] = {}
# Ассеты цепочки нарисованы так, что самая низкая точка — у нижнего края
# картинки (scripts/generate_chain_assets.py).
_CHAIN_DIP_FRACTION = 1.0


def _load_chain(color: str) -> Image.Image | None:
    if color == "none":
        return None
    if color not in _CHAIN_CACHE:
        path = Path(__file__).parent / "assets" / f"chain_{color}.png"
        if not path.exists():
            return None
        _CHAIN_CACHE[color] = Image.open(path).convert("RGBA")
    return _CHAIN_CACHE[color]


def _apply_neck_item(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = pose_mod.get_neck_anchor(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла плечи на фото 🙁 Пришлите фото анфас по плечи, "
            "чтобы были видны шея и оба плеча."
        )

    down = anchors.down
    is_beads = item.category == Category.BEADS

    if is_beads:
        # У колье на картинке концы уже обрезаны там, где оно уходит за шею.
        # Приравниваем ширину картинки к ширине шеи — и обрывы приходятся на
        # края шеи. Точка крепления — верх картинки, то есть сами концы.
        width = anchors.neck_width * BEADS_NECK_OVERSHOOT * item.anchor_scale
        point = (
            anchors.neck_point[0] + anchors.shoulder_width * item.offset_x,
            anchors.neck_point[1] + anchors.shoulder_width * item.offset_y,
        )
        return overlay_image(
            base,
            overlay_img,
            point,
            width,
            anchors.tilt_angle + item.rotation_offset,
            overlay_anchor=(0.5, 0.0),
        )

    # Кулон висит на цепочке ниже шеи — на груди.
    drop = anchors.shoulder_width * PENDANT_DROP
    point = (
        anchors.neck_point[0] + down[0] * drop + anchors.shoulder_width * item.offset_x,
        anchors.neck_point[1] + down[1] * drop + anchors.shoulder_width * item.offset_y,
    )

    # Сначала цепочка: её низ приходится ровно в точку подвеса, концы вверху
    # расходятся на ширину шеи и уходят за неё.
    chain_img = _load_chain(item.chain_color)
    if chain_img is not None:
        base = overlay_image(
            base,
            chain_img,
            point,
            anchors.shoulder_width * CHAIN_WIDTH_FRACTION,
            anchors.tilt_angle,
            overlay_anchor=(0.5, _CHAIN_DIP_FRACTION),
        )

    return overlay_image(
        base,
        overlay_img,
        point,
        _width_for_length(overlay_img, anchors.shoulder_width * PENDANT_LENGTH_FRACTION
                          * item.anchor_scale),
        anchors.tilt_angle + item.rotation_offset,
        overlay_anchor=(0.5, 0.0),
    )


def _apply_ring(base, overlay_img, np_bgr, item: JewelryItem):
    anchors = hand_mod.get_ring_anchor(np_bgr)
    if anchors is None:
        raise TryOnError(
            "Не нашла руку на фото 🙁 Пришлите чёткое фото ладони крупным планом."
        )

    width = anchors.finger_width * RING_WIDTH_FRACTION * item.anchor_scale
    point = (
        anchors.point[0] + anchors.finger_width * item.offset_x,
        anchors.point[1] + anchors.finger_width * item.offset_y,
    )
    return overlay_image(
        base,
        overlay_img,
        point,
        width,
        anchors.angle + item.rotation_offset,
        overlay_anchor=(0.5, 0.5),
    )
