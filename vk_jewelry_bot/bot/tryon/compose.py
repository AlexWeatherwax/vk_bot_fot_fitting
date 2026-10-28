"""
Наложение картинки украшения (RGBA) на фото пользователя.

Ключевая сложность: после Image.rotate(angle, expand=True) размер и центр
картинки меняются, поэтому "точку крепления" украшения (например, верх
серьги-крючка, или низ диадемы) нужно пересчитать в новых координатах,
повернув её вектор от центра на тот же угол — иначе при повороте под наклон
головы украшение будет "уезжать" в сторону.

Формула поворота точки ниже подобрана и проверена эмпирически (маленьким
скриптом, который рисует маркер, крутит его через PIL и сравнивает
предсказанную/фактическую позицию), чтобы точно соответствовать тому,
как именно PIL.Image.rotate поворачивает пиксели.
"""
import math

from PIL import Image


def _rotate_point_around_center(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    # Внимание: знак минус здесь важен и подобран эмпирически под PIL.Image.rotate.
    # Если у вас в проекте вдруг картинка "уезжает" при повороте — прежде чем менять
    # знак, перепроверьте на тестовом изображении (см. tests/test_compose.py).
    rad = -math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def overlay_image(
    base: Image.Image,
    overlay: Image.Image,
    anchor_xy: tuple[float, float],
    target_width: float,
    rotation_deg: float = 0.0,
    overlay_anchor: tuple[float, float] = (0.5, 0.5),
) -> Image.Image:
    """
    Вставляет overlay (RGBA-картинку украшения) в base так, чтобы точка
    overlay_anchor (доли ширины/высоты overlay, например (0.5, 0.0) — верхняя
    середина) оказалась ровно в точке anchor_xy на base.

    :param base: фото пользователя (будет сконвертировано в RGBA)
    :param overlay: PNG украшения с альфа-каналом
    :param anchor_xy: точка на base (в пикселях), куда должна попасть anchor-точка overlay
    :param target_width: целевая ширина украшения на итоговом фото, в пикселях
    :param rotation_deg: поворот украшения в градусах
    :param overlay_anchor: точка крепления на самой картинке украшения (доли 0..1)
    :return: новое изображение RGBA с наложенным украшением
    """
    if target_width <= 0 or overlay.width == 0:
        return base.convert("RGBA")

    base = base.convert("RGBA")

    scale = target_width / overlay.width
    new_w = max(1, round(overlay.width * scale))
    new_h = max(1, round(overlay.height * scale))
    resized = overlay.resize((new_w, new_h), Image.LANCZOS)

    # anchor-точка относительно центра resized (до поворота)
    ax = overlay_anchor[0] * new_w - new_w / 2
    ay = overlay_anchor[1] * new_h - new_h / 2

    rotated = resized.rotate(rotation_deg, expand=True, resample=Image.BICUBIC)
    rw, rh = rotated.size

    rax, ray = _rotate_point_around_center(ax, ay, rotation_deg)
    anchor_in_rotated = (rw / 2 + rax, rh / 2 + ray)

    paste_x = round(anchor_xy[0] - anchor_in_rotated[0])
    paste_y = round(anchor_xy[1] - anchor_in_rotated[1])

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(rotated, (paste_x, paste_y), rotated)
    return Image.alpha_composite(base, layer)
