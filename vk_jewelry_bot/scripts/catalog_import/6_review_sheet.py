"""
Шаг 6 — собрать контактные листы для просмотра результата глазами:
готовый вырез на «шахматке» (чтобы было видно, где прозрачно) рядом с
исходным кадром. Кладёт JPEG-страницы в work/report/.

Проверять надо именно так: числовые признаки ловят грубые промахи, но
«осталась ли половина блюдца» видно только глазом.
"""
from __future__ import annotations

import json
import sys

from PIL import Image, ImageDraw, ImageFont

from paths import CUTOUT_DIR, PICKS_JSON, REPORT_DIR, WORK_DIR

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
TH = 260
PER_PAGE = 6
PAD = 8
LABEL_W = 300


def checkerboard(img: Image.Image) -> Image.Image:
    bg = Image.new("RGB", img.size, (250, 250, 250))
    dark = Image.new("RGB", img.size, (196, 196, 200))
    m = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(m)
    step = max(6, max(img.size) // 24)
    for y in range(0, img.size[1], step):
        for x in range(0, img.size[0], step):
            if (x // step + y // step) % 2:
                d.rectangle([x, y, x + step - 1, y + step - 1], fill=255)
    bg.paste(dark, (0, 0), m)
    bg.paste(img, (0, 0), img.split()[-1])
    return bg


def main() -> None:
    picks = {p["key"]: p for p in json.loads(PICKS_JSON.read_text(encoding="utf-8"))}
    report = json.loads((WORK_DIR / "cutout_report.json").read_text(encoding="utf-8"))
    report.sort(key=lambda r: (r.get("category") or "zzz", r["title"]))
    font = ImageFont.truetype(FONT_PATH, 19)
    small = ImageFont.truetype(FONT_PATH, 16)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for f in REPORT_DIR.glob("*.jpg"):
        f.unlink()

    pages = 0
    for start in range(0, len(report), PER_PAGE):
        chunk = report[start:start + PER_PAGE]
        sheet = Image.new("RGB", (LABEL_W + 2 * (TH + PAD) + PAD, len(chunk) * (TH + PAD) + PAD),
                          (242, 242, 242))
        d = ImageDraw.Draw(sheet)
        for i, row in enumerate(chunk):
            y = PAD + i * (TH + PAD)
            d.line([0, y - 4, sheet.width, y - 4], fill=(190, 190, 190), width=2)
            pick = picks[row["key"]]
            d.text((6, y + 4), f"{pick['section']} · {pick['category'] or 'без категории'}",
                   font=small, fill=(120, 120, 130))
            title = pick["title"]
            for k, line in enumerate([title[j:j + 24] for j in range(0, len(title), 24)][:3]):
                d.text((6, y + 26 + k * 22), line, font=font, fill=(0, 0, 0))
            d.text((6, y + TH - 22), f"кадр #{pick['chosen']}", font=small, fill=(150, 60, 60))

            src = Image.open(pick["photo"]).convert("RGB")
            src.thumbnail((TH, TH), Image.LANCZOS)
            sheet.paste(src, (LABEL_W + (TH - src.width) // 2, y + (TH - src.height) // 2))

            if row.get("ok"):
                cut = Image.open(row["path"]).convert("RGBA")
                cut.thumbnail((TH, TH), Image.LANCZOS)
                view = checkerboard(cut)
                sheet.paste(view, (LABEL_W + TH + PAD + (TH - view.width) // 2,
                                   y + (TH - view.height) // 2))
            else:
                d.text((LABEL_W + TH + PAD + 10, y + TH // 2), row.get("reason", "ошибка"),
                       font=font, fill=(190, 0, 0))
        pages += 1
        out = REPORT_DIR / f"cut_{pages:02d}.jpg"
        sheet.save(out, quality=86)
        print(out)


if __name__ == "__main__":
    sys.exit(main())
