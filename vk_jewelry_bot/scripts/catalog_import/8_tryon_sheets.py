"""
Шаг 8 — примерить ВЕСЬ каталог на пробные фото и собрать сводные листы.

Нужен, чтобы оценить калибровку глазами: масштаб и посадку по каждому товару
видно только на живом фото. Для каждой категории берётся одно пробное фото,
кадр автоматически приближается к нужной части тела (лицо / шея и плечи /
кисть) — иначе украшение на общем плане не разглядеть.

Под каждой примеркой подписаны текущие поля подстройки из manifest.json:
scale — anchor_scale, dx/dy — offset_x/offset_y, rot — rotation_offset.
Править их нужно там же, в manifest.json.

Запускать окружением с mediapipe, из корня проекта:

    ../.venv-mp/bin/python scripts/catalog_import/8_tryon_sheets.py
    ../.venv-mp/bin/python scripts/catalog_import/8_tryon_sheets.py earrings ring
"""
from __future__ import annotations

import io
import math
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from paths import CALIBRATION_DIR, PROJECT_ROOT, WORK_DIR

sys.path.insert(0, str(PROJECT_ROOT))

from bot.jewelry.catalog import catalog                      # noqa: E402
from bot.jewelry.models import CATEGORY_TITLES, Category     # noqa: E402
from bot.tryon import landmarks_face as face_mod             # noqa: E402
from bot.tryon import landmarks_hand as hand_mod             # noqa: E402
from bot.tryon import landmarks_pose as pose_mod             # noqa: E402
from bot.tryon.pipeline import TryOnError, apply_tryon       # noqa: E402

PHOTO_DIR = CALIBRATION_DIR
OUT_DIR = WORK_DIR / "tryon_sheets"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"

# Какое пробное фото и какую часть тела показывать для каждой категории.
# "face" — лицо целиком, "torso" — шея и плечи, "hand" — кисть, "ear" — ухо крупным планом.
SETUP = {
    Category.EARRINGS: ("1000013931.jpg", "face"),
    Category.DIADEM:   ("1000013931.jpg", "face"),
    Category.HAIRPIN:  ("1000013931.jpg", "face"),
    Category.PENDANT:  ("1000013928.jpg", "torso"),
    Category.BEADS:    ("1000013928.jpg", "torso"),
    Category.BROOCH:   ("1000013928.jpg", "torso"),
    Category.RING:     ("1000013934.jpg", "hand"),
    Category.BRACELET: ("1000013934.jpg", "hand"),
    Category.KAFFY:    ("1000013935_profil_ukho_kaffy.jpg", "ear"),
}

TH = 330          # сторона миниатюры на листе
COLS = 4
PAD = 8
LABEL_H = 34


def crop_box(photo_bytes: bytes, kind: str) -> tuple[int, int, int, int]:
    """
    Рамка кадрирования вокруг нужной части тела — считается по тем же
    landmark-ам, которыми бот определяет точку крепления. Так лист показывает
    именно ту область, куда украшение и садится, без ручных координат.
    """
    arr = np.frombuffer(photo_bytes, np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    h, w = bgr.shape[:2]

    if kind == "face":
        a = face_mod.get_face_anchors(bgr)
        if a is None:
            return 0, 0, w, h
        cx = (a.left_ear[0] + a.right_ear[0]) / 2
        cy = (a.forehead_top[1] + a.chin[1]) / 2
        half = a.face_width * 1.15
    elif kind == "ear":
        a = face_mod.get_face_anchors(bgr)
        if a is None:
            return 0, 0, w, h
        # Каффы в каталоге пока только на левое (по анатомии) ухо —
        # см. JewelryItem.kaffy_side. Кафф крепится на мочку (см.
        # pipeline._apply_kaffy), поэтому и лист приближаем к ней же.
        cx, cy = a.left_lobe
        half = a.face_width * 0.4
    elif kind == "torso":
        a = pose_mod.get_neck_anchor(bgr)
        if a is None:
            return 0, 0, w, h
        cx, cy = a.neck_point[0], a.neck_point[1] + a.shoulder_width * 0.28
        half = a.shoulder_width * 0.75
    else:  # hand
        a = hand_mod.get_wrist_anchor(bgr)
        b = hand_mod.get_ring_anchor(bgr)
        if a is None or b is None:
            return 0, 0, w, h
        cx = (a.point[0] + b.point[0]) / 2
        cy = (a.point[1] + b.point[1]) / 2
        half = math.hypot(a.point[0] - b.point[0], a.point[1] - b.point[1]) * 1.5 + a.wrist_width

    x0 = int(max(0, cx - half)); x1 = int(min(w, cx + half))
    y0 = int(max(0, cy - half)); y1 = int(min(h, cy + half))
    return x0, y0, x1, y1


def tuning_label(item) -> str:
    bits = [f"scale {item.anchor_scale:g}"]
    if item.offset_x:
        bits.append(f"dx {item.offset_x:+g}")
    if item.offset_y:
        bits.append(f"dy {item.offset_y:+g}")
    if item.rotation_offset:
        bits.append(f"rot {item.rotation_offset:+g}")
    return "   ".join(bits)


def build_sheet(cells, title, out_path):
    font = ImageFont.truetype(FONT_PATH, 16)
    small = ImageFont.truetype(FONT_PATH, 14)
    head = ImageFont.truetype(FONT_PATH, 22)

    rows = (len(cells) + COLS - 1) // COLS
    width = COLS * (TH + PAD) + PAD
    height = 44 + rows * (TH + LABEL_H + PAD) + PAD
    sheet = Image.new("RGB", (width, height), (245, 245, 244))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 12), title, font=head, fill=(20, 22, 21))

    for i, (name, tuning, img) in enumerate(cells):
        r, c = divmod(i, COLS)
        x = PAD + c * (TH + PAD)
        y = 44 + r * (TH + LABEL_H + PAD)
        if img is not None:
            sheet.paste(img, (x, y))
        else:
            d.rectangle([x, y, x + TH, y + TH], outline=(200, 120, 120), width=2)
            d.text((x + 10, y + TH // 2), "не примерилось", font=font, fill=(170, 60, 50))
        d.text((x, y + TH + 4), name[:34], font=font, fill=(20, 22, 21))
        d.text((x, y + TH + 20), tuning, font=small, fill=(140, 100, 60))

    sheet.save(out_path, quality=88)
    return out_path


def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = []

    for category, (photo_name, kind) in SETUP.items():
        if wanted and category.value not in wanted:
            continue
        items = [i for i in catalog.items if i.category == category]
        if not items:
            continue
        path = PHOTO_DIR / photo_name
        if not path.exists():
            print(f"нет пробного фото {photo_name}, пропуск {category.value}")
            continue
        photo_bytes = path.read_bytes()
        box = crop_box(photo_bytes, kind)

        cells = []
        for item in items:
            try:
                result = apply_tryon(item, catalog.image_path(item), photo_bytes)
                img = Image.open(io.BytesIO(result)).convert("RGB").crop(box)
                img = img.resize((TH, TH), Image.LANCZOS)
            except (TryOnError, Exception) as exc:              # noqa: BLE001
                print(f"  {item.name}: {type(exc).__name__}: {exc}")
                img = None
            cells.append((item.name, tuning_label(item), img))
            print(f"  {category.value:9s} {item.name}", flush=True)

        title = f"{CATEGORY_TITLES[category]} — {len(items)} шт · пробное фото {photo_name}"
        out = OUT_DIR / f"tryon_{category.value}.jpg"
        made.append(build_sheet(cells, title, out))
        print(f"-> {out}")

    print("\nлистов собрано:", len(made))
    for m in made:
        print("  ", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
