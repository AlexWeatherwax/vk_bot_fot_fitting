"""
Рисует ассеты цепочки для кулонов: bot/tryon/assets/chain_silver.png и
chain_gold.png.

Прежние ассеты были широкой пологой дугой — на фото они читались тонкой
светлой царапиной поперёк груди, а не цепочкой на шее. Здесь цепочка
рисуется как настоящая: цепная линия (катенария) из отдельных звеньев,
концы вверху расходятся на ширину шеи, самая низкая точка — внизу по центру,
ровно там, где висит кулон.

Бот вставляет картинку так, чтобы её низ попал в точку подвеса кулона
(_CHAIN_DIP_FRACTION = 1.0 в bot/tryon/pipeline.py), а ширина равнялась
примерно ширине шеи — тогда концы уходят за шею.

    python scripts/generate_chain_assets.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "bot" / "tryon" / "assets"

W, H = 900, 1080          # выше, чем шире: цепочка должна обнимать шею
SUPERSAMPLE = 2           # рисуем крупнее и уменьшаем — сглаживает звенья
SAG = 2.6                 # параметр катенарии: больше — резче провис
LINK_STEP = 26            # шаг между центрами звеньев, px (до уменьшения)
LINK_LONG = 30            # длина звена
LINK_SHORT = 17           # ширина звена
STROKE = 5                # толщина проволоки звена

PALETTES = {
    "silver": {
        "dark": (92, 96, 102, 255),
        "mid": (168, 174, 182, 255),
        "light": (232, 236, 240, 255),
    },
    "gold": {
        "dark": (120, 88, 34, 255),
        "mid": (196, 152, 66, 255),
        "light": (246, 222, 158, 255),
    },
}


def catenary_y(x: float, width: float, height: float) -> float:
    """
    Цепная линия: концы на y=0 по краям, самая низкая точка y=height по центру.
    Это форма, которую свободно висящая цепочка принимает физически, —
    парабола выглядит заметно «мягче» и менее похоже на металл.
    """
    t = (2.0 * x / width) - 1.0                     # -1 .. +1
    top = math.cosh(SAG / 2.0)
    return height * (top - math.cosh(SAG * t / 2.0)) / (top - 1.0)


def link_points(width: int, height: int, step: int) -> list[tuple[float, float, float]]:
    """Центры звеньев на равном расстоянии по длине кривой + угол наклона."""
    # плотная выборка кривой
    samples = []
    n = 4000
    for i in range(n + 1):
        x = width * i / n
        samples.append((x, catenary_y(x, width, height)))

    points, carried = [], 0.0
    points.append((samples[0][0], samples[0][1], 0.0))
    for (x0, y0), (x1, y1) in zip(samples, samples[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        carried += seg
        if carried >= step:
            carried = 0.0
            angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
            points.append((x1, y1, angle))
    return points


def draw_link(canvas: Image.Image, x: float, y: float, angle: float,
              palette: dict, edge_on: bool) -> None:
    """
    Одно звено. Чётные звенья рисуем «плашмя» (овал длинной осью вдоль
    цепочки), нечётные — «на ребро» (узкий овал): именно это чередование и
    читается как цепь, а не как пунктир.
    """
    long_side = LINK_LONG
    short_side = LINK_SHORT if not edge_on else max(3, LINK_SHORT // 3)
    pad = STROKE * 3
    tile = Image.new("RGBA", (long_side + pad * 2, short_side + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    box = (pad, pad, pad + long_side, pad + short_side)
    d.ellipse(box, outline=palette["dark"], width=STROKE)
    inner = (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1)
    d.ellipse(inner, outline=palette["mid"], width=max(1, STROKE - 2))
    # блик по верхней кромке — звено читается объёмным
    d.arc(box, start=190, end=350, fill=palette["light"], width=max(1, STROKE - 3))

    tile = tile.rotate(-angle, expand=True, resample=Image.BICUBIC)
    canvas.alpha_composite(tile, (int(x - tile.width / 2), int(y - tile.height / 2)))


def build(name: str) -> Path:
    palette = PALETTES[name]
    width, height = W * SUPERSAMPLE, H * SUPERSAMPLE
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    for i, (x, y, angle) in enumerate(link_points(width, height, LINK_STEP * SUPERSAMPLE)):
        draw_link(canvas, x, y, angle, palette, edge_on=bool(i % 2))

    canvas = canvas.resize((W, H), Image.LANCZOS)
    out = OUT_DIR / f"chain_{name}.png"
    canvas.save(out)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in PALETTES:
        path = build(name)
        print("готово:", path, Image.open(path).size)
    print("\nНиз картинки — точка подвеса кулона; концы вверху уходят за шею.")


if __name__ == "__main__":
    main()
