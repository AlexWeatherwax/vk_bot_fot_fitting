#!/usr/bin/env python3
"""
Генерирует простые PNG-заглушки украшений (прозрачный фон) для каждой
категории — только чтобы можно было сразу проверить всю цепочку бота
(поиск -> запрос фото -> примерка -> отправка), не имея под рукой реальных
фотографий украшений.

Для боевого каталога замените файлы в bot/jewelry/gallery/ на настоящие
фото украшений (см. bot/jewelry/gallery/README.md) — качество примерки
напрямую зависит от качества исходных картинок украшений.

Запуск:
    python scripts/generate_placeholder_gallery.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

GALLERY_DIR = Path(__file__).resolve().parent.parent / "bot" / "jewelry" / "gallery"
SS = 4  # коэффициент суперсэмплинга для сглаживания краёв фигур

GOLD = (198, 156, 74, 255)
GOLD_DARK = (150, 112, 45, 255)
PEARL = (245, 240, 230, 255)
RED = (176, 42, 55, 255)
WHITE = (255, 255, 255, 255)


def _canvas(w, h):
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _finish(img, w, h) -> Image.Image:
    return img.resize((w, h), Image.LANCZOS)


def make_earring(path: Path):
    w, h = 160, 260
    img, d = _canvas(w, h)
    s = SS
    # петелька крючка
    d.ellipse([w*s*0.42, h*s*0.03, w*s*0.58, h*s*0.14], outline=GOLD_DARK, width=int(3*s))
    # каплевидная подвеска (примерная форма "луны")
    d.ellipse([w*s*0.20, h*s*0.20, w*s*0.80, h*s*0.85], fill=GOLD)
    d.ellipse([w*s*0.34, h*s*0.20, w*s*0.90, h*s*0.85], fill=(0, 0, 0, 0))
    d.ellipse([w*s*0.40, h*s*0.22, w*s*0.88, h*s*0.80], fill=(0, 0, 0, 0))
    # вырез, создающий полумесяц
    mask_cut = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dm = ImageDraw.Draw(mask_cut)
    dm.ellipse([w*s*0.38, h*s*0.18, w*s*1.05, h*s*0.87], fill=(0, 0, 0, 255))
    img_arr = img
    # применяем вырез через альфа-композицию "стирания"
    import numpy as np
    base_np = np.array(img_arr)
    cut_np = np.array(mask_cut)
    erase = cut_np[:, :, 3] > 0
    base_np[erase] = (0, 0, 0, 0)
    img_arr = Image.fromarray(base_np)
    # маленький камешек снизу
    d2 = ImageDraw.Draw(img_arr)
    d2.ellipse([w*s*0.44, h*s*0.68, w*s*0.56, h*s*0.80], fill=RED)
    _finish(img_arr, w, h).save(path)


def make_pendant(path: Path):
    w, h = 220, 260
    img, d = _canvas(w, h)
    s = SS
    d.ellipse([w*s*0.44, h*s*0.02, w*s*0.56, h*s*0.10], outline=GOLD_DARK, width=int(3*s))
    d.line([w*s*0.5, h*s*0.10, w*s*0.5, h*s*0.22], fill=GOLD_DARK, width=int(3*s))
    cx, cy, r = w*s*0.5, h*s*0.52, w*s*0.34
    d.pieslice([cx-r, cy-r*0.9, cx, cy+r*0.5], 135, 315, fill=RED)
    d.pieslice([cx, cy-r*0.9, cx+r, cy+r*0.5], 225, 45, fill=RED)
    d.polygon([(cx-r, cy-r*0.15), (cx+r, cy-r*0.15), (cx, cy+r*0.95)], fill=RED)
    _finish(img, w, h).save(path)


def make_ring(path: Path):
    w = h = 240
    img, d = _canvas(w, h)
    s = SS
    band_r = w*s*0.42
    cx, cy = w*s*0.5, h*s*0.58
    d.ellipse([cx-band_r, cy-band_r, cx+band_r, cy+band_r], outline=GOLD, width=int(band_r*0.28))
    gem = w*s*0.16
    d.ellipse([cx-gem, cy-band_r-gem*0.6, cx+gem, cy-band_r-gem*0.6+gem*2], fill=RED)
    d.ellipse([cx-gem*0.4, cy-band_r-gem*0.2, cx+gem*0.4, cy-band_r-gem*0.2+gem], fill=WHITE)
    _finish(img, w, h).save(path)


def make_beads(path: Path):
    w, h = 520, 220
    img, d = _canvas(w, h)
    s = SS
    n = 17
    r = w*s*0.018
    for i in range(n):
        t = i / (n - 1)
        x = w*s*(0.08 + 0.84*t)
        # U-образная форма бус: высоко у краёв (шея), провисает по центру (грудь)
        y = h*s*0.15 + (h*s*0.55) * (1 - abs(2*t - 1))
        d.ellipse([x-r, y-r, x+r, y+r], fill=PEARL, outline=(210, 200, 180, 255), width=max(1, int(s*0.5)))
    _finish(img, w, h).save(path)


def make_diadem(path: Path):
    w, h = 420, 180
    img, d = _canvas(w, h)
    s = SS
    base_y = h*s*0.85
    d.arc([w*s*0.02, h*s*0.15, w*s*0.98, h*s*1.55], 200, 340, fill=GOLD, width=int(6*s))
    peaks = [0.15, 0.30, 0.5, 0.70, 0.85]
    heights = [0.55, 0.35, 0.05, 0.35, 0.55]
    for px, ph in zip(peaks, heights):
        x = w*s*px
        top_y = h*s*ph
        d.polygon(
            [(x - w*s*0.03, base_y), (x, top_y), (x + w*s*0.03, base_y)],
            fill=GOLD,
        )
    gem = w*s*0.035
    cx = w*s*0.5
    cy = h*s*0.18
    d.ellipse([cx-gem, cy-gem, cx+gem, cy+gem], fill=(120, 190, 220, 255))
    _finish(img, w, h).save(path)


def main():
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    make_earring(GALLERY_DIR / "earrings_moon.png")
    make_pendant(GALLERY_DIR / "pendant_heart.png")
    make_ring(GALLERY_DIR / "ring_rose.png")
    make_beads(GALLERY_DIR / "beads_pearl.png")
    make_diadem(GALLERY_DIR / "diadem_snow.png")
    print(f"Заглушки украшений сохранены в {GALLERY_DIR}")


if __name__ == "__main__":
    main()
