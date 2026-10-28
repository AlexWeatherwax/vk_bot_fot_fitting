"""
Шаг 7 — прогнать примерку по калибровочным фото и собрать лист для просмотра.

Нужен после замены картинок в каталоге: вместе с картинкой меняется и то,
какую часть кадра занимает украшение, поэтому поля anchor_scale/offset_*
приходится подбирать заново. Этот скрипт показывает, что получилось.

Запускать окружением с mediapipe (.venv-mp), из корня проекта:

    ../../../.venv-mp/bin/python scripts/catalog_import/7_calibrate_preview.py earrings pendant
    ../../../.venv-mp/bin/python scripts/catalog_import/7_calibrate_preview.py --id imladris_ring_koltso-svet-luny

Без аргументов берёт по одному товару каждой категории.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.jewelry.catalog import catalog                     # noqa: E402
from bot.jewelry.models import Category                     # noqa: E402
from bot.tryon.pipeline import TryOnError, apply_tryon      # noqa: E402

PHOTO_DIR = PROJECT_ROOT / "фото для калибровки"
OUT_DIR = Path(__file__).resolve().parent / "work" / "calibrate"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

# Какое калибровочное фото осмысленно для какой категории.
PHOTO_FOR = {
    Category.EARRINGS: ["1000013929.jpg", "1000013931.jpg"],
    Category.DIADEM: ["1000013931.jpg", "1000013932.jpg"],
    Category.HAIRPIN: ["1000013931.jpg", "1000013932.jpg"],
    Category.PENDANT: ["1000013928.jpg", "1000013930.jpg"],
    Category.BEADS: ["1000013928.jpg", "1000013930.jpg"],
    Category.BROOCH: ["1000013928.jpg", "1000013930.jpg"],
    Category.RING: ["1000013933.jpg", "1000013934.jpg"],
    Category.BRACELET: ["1000013933.jpg", "1000013934.jpg"],
    # Кафф сидит на ушной раковине — анфас его не видно, нужен профиль/3-4.
    Category.KAFFY: ["1000013935_profil_ukho_kaffy.jpg"],
}
TH = 420


def pick_items(args: list[str]):
    if args and args[0] == "--id":
        ids = set(args[1:])
        return [i for i in catalog.items if i.id in ids]
    if args:
        wanted = set(args)
        return [i for i in catalog.items if i.category.value in wanted]
    seen, out = set(), []
    for item in catalog.items:
        if item.category not in seen:
            seen.add(item.category)
            out.append(item)
    return out


def main() -> int:
    items = pick_items(sys.argv[1:])
    if not items:
        print("Не нашла таких товаров в каталоге.")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Префикс имени файла из аргументов запуска: без него разные прогоны
    # (--id ... или список категорий) пишут в одни и те же tryon_01/02/03.jpg
    # и затирают друг друга.
    run_slug = "-".join(a.lstrip("-") for a in sys.argv[1:]) or "default"
    font = ImageFont.truetype(FONT_PATH, 18)

    rows = []
    for item in items:
        photos = PHOTO_FOR.get(item.category, [])
        shots = []
        for name in photos:
            path = PHOTO_DIR / name
            if not path.exists():
                continue
            try:
                result = apply_tryon(item, catalog.image_path(item), path.read_bytes())
                shots.append(("ok", result))
            except TryOnError as exc:
                shots.append(("err", str(exc)))
            except Exception as exc:                      # noqa: BLE001
                shots.append(("err", f"{type(exc).__name__}: {exc}"))
        rows.append((item, shots))
        print(item.name, "->", [s[0] for s in shots], flush=True)

    per_page = 3
    page = 0
    import io
    for start in range(0, len(rows), per_page):
        chunk = rows[start:start + per_page]
        width = 320 + max(len(s) for _, s in chunk) * (TH + 8) + 8
        sheet = Image.new("RGB", (width, len(chunk) * (TH + 8) + 8), (240, 240, 240))
        d = ImageDraw.Draw(sheet)
        for i, (item, shots) in enumerate(chunk):
            y = 8 + i * (TH + 8)
            d.line([0, y - 4, sheet.width, y - 4], fill=(190, 190, 190), width=2)
            d.text((8, y + 4), item.category.value, font=font, fill=(120, 120, 130))
            name = item.name
            for k, line in enumerate([name[j:j + 26] for j in range(0, len(name), 26)][:3]):
                d.text((8, y + 28 + k * 22), line, font=font, fill=(0, 0, 0))
            d.text((8, y + 110), f"scale {item.anchor_scale}", font=font, fill=(120, 60, 60))
            for j, (kind, payload) in enumerate(shots):
                x = 320 + j * (TH + 8)
                if kind == "ok":
                    img = Image.open(io.BytesIO(payload)).convert("RGB")
                    img.thumbnail((TH, TH), Image.LANCZOS)
                    sheet.paste(img, (x + (TH - img.width) // 2, y + (TH - img.height) // 2))
                else:
                    d.text((x + 10, y + TH // 2), payload[:60], font=font, fill=(190, 0, 0))
        page += 1
        out = OUT_DIR / f"tryon_{run_slug}_{page:02d}.jpg"
        sheet.save(out, quality=86)
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
