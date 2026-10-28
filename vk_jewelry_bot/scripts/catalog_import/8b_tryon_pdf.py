"""
Шаг 8b — сложить листы примерки (шаг 8) в один PDF для просмотра.

Листы получаются высокими: в PDF каждый режется по высоте на страницы A4
с сохранением масштаба по ширине.

Запускать окружением .venv-import (нужны только Pillow и reportlab):

    ../../../.venv-import/bin/python 8b_tryon_pdf.py
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

SHEETS_DIR = Path(__file__).resolve().parent / "work" / "tryon_sheets"
OUT = SHEETS_DIR / "Примерка каталога.pdf"

# Порядок разделов в PDF — от самых многочисленных к остальным.
ORDER = ["earrings", "pendant", "kaffy", "beads", "ring", "bracelet", "diadem", "hairpin", "brooch"]
MARGIN = 8 * mm


def slice_reader(image: Image.Image) -> ImageReader:
    """
    Отдаёт кусок листа как ImageReader поверх буфера в памяти.

    Через временный файл нельзя: reportlab кеширует картинки по имени файла,
    и если перезаписывать один и тот же путь, все страницы получают первый
    кусок (проверено — страницы дублировались).
    """
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=88, optimize=True)
    buf.seek(0)
    return ImageReader(buf)


def main() -> None:
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(str(OUT), pagesize=landscape(A4), pageCompression=1)
    pages = 0

    for name in ORDER:
        path = SHEETS_DIR / f"tryon_{name}.jpg"
        if not path.exists():
            continue
        sheet = Image.open(path)
        scale = (page_w - 2 * MARGIN) / sheet.width
        slice_height = int((page_h - 2 * MARGIN) / scale)

        top = 0
        while top < sheet.height:
            part = sheet.crop((0, top, sheet.width, min(sheet.height, top + slice_height)))
            drawn_h = part.height * scale
            c.drawImage(slice_reader(part), MARGIN, page_h - MARGIN - drawn_h,
                        width=part.width * scale, height=drawn_h)
            c.showPage()
            pages += 1
            top += slice_height
        print(f"{name:9s} лист {sheet.width}x{sheet.height} -> страниц: "
              f"{-(-sheet.height // slice_height)}")

    c.save()
    size = OUT.stat().st_size / 1024 / 1024
    print(f"\nготово: {OUT}  ({size:.1f} МБ, страниц {pages})")


if __name__ == "__main__":
    main()
