"""
Тест на то, что точка крепления украшения не "уезжает" при повороте —
критично для правдоподобной примерки при наклоне головы/руки.

Запуск: pytest tests/test_compose.py
"""
import numpy as np
from PIL import Image, ImageDraw

from bot.tryon.compose import overlay_image


def _find_marker(img: Image.Image):
    # Ищем "красноватые" непрозрачные пиксели с допуском — после ресайза/поворота
    # края маркера смешиваются с прозрачностью, а не остаются чистым (255,0,0,255).
    arr = np.array(img.convert("RGBA")).astype(int)
    red_ish = (arr[:, :, 0] > 180) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 80) & (arr[:, :, 3] > 180)
    ys, xs = np.where(red_ish)
    assert len(xs) > 0, "маркер не найден на итоговом изображении"
    return (xs.mean(), ys.mean())


def _overlay_with_marker(size=(40, 100), anchor_frac=(0.5, 0.15), radius=6):
    w, h = size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = anchor_frac[0] * w, anchor_frac[1] * h
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 0, 0, 255))
    return overlay


def test_anchor_point_stays_fixed_across_rotation():
    base = Image.new("RGBA", (400, 400), (200, 200, 200, 255))
    anchor_frac = (0.5, 0.15)
    overlay = _overlay_with_marker(anchor_frac=anchor_frac)
    target_anchor = (150.0, 220.0)

    for angle in (0, 15, -15, 45, -90, 178):
        result = overlay_image(
            base.copy(),
            overlay,
            target_anchor,
            target_width=40,
            rotation_deg=angle,
            overlay_anchor=anchor_frac,
        )
        found = _find_marker(result)
        assert abs(found[0] - target_anchor[0]) < 2.5, angle
        assert abs(found[1] - target_anchor[1]) < 2.5, angle


def test_scaling_changes_size_but_not_anchor():
    base = Image.new("RGBA", (300, 300), (200, 200, 200, 255))
    overlay = _overlay_with_marker(anchor_frac=(0.5, 0.5))
    anchor = (100.0, 100.0)

    for width in (20, 60, 120):
        result = overlay_image(
            base.copy(),
            overlay,
            anchor,
            target_width=width,
            rotation_deg=0,
            overlay_anchor=(0.5, 0.5),
        )
        found = _find_marker(result)
        assert abs(found[0] - anchor[0]) < 2.0
        assert abs(found[1] - anchor[1]) < 2.0
