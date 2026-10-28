"""
Шаг 9 — собрать PDF-задание фотографу: что переснять и как снимать.

Список позиций держится здесь, в RESHOOT: он же продублирован словами в
bot/jewelry/gallery/imladris/NEEDS_REVIEW.md. Миниатюры берутся из архива
(work/items.json) и складываются в work/brief_img/. Итоговый PDF сохраняется
в work/brief/, постоянные иллюстрации сравнения ракурсов — в examples/.

Запускать окружением .venv-import (нужны Pillow и reportlab):

    ../../../.venv-import/bin/python 9_reshoot_brief.py
"""
from __future__ import annotations

import json

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage, KeepTogether,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from paths import EXAMPLES_DIR, ITEMS_JSON, WORK_DIR

IMG_DIR = WORK_DIR / "brief_img"
OUT = WORK_DIR / "brief" / "Задание на пересъёмку.pdf"

FONTS = "/System/Library/Fonts/Supplemental/"
pdfmetrics.registerFont(TTFont("A", FONTS + "Arial.ttf"))
pdfmetrics.registerFont(TTFont("A-B", FONTS + "Arial Bold.ttf"))
pdfmetrics.registerFont(TTFont("A-I", FONTS + "Arial Italic.ttf"))
pdfmetrics.registerFontFamily("A", normal="A", bold="A-B", italic="A-I")

INK = colors.HexColor("#1A1C1B")
SOFT = colors.HexColor("#5A605A")
LINE = colors.HexColor("#C9CFC7")
ACC = colors.HexColor("#2E6A87")
BAD = colors.HexColor("#A6473C")
BAND = colors.HexColor("#EFF1ED")


def st(name, size, leading, font="A", color=INK, space_after=0, space_before=0):
    return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
                          textColor=color, spaceAfter=space_after,
                          spaceBefore=space_before, alignment=TA_LEFT)


H1 = st("H1", 24, 28, "A-B", space_after=6)
LEDE = st("LEDE", 11, 16, color=SOFT, space_after=4)
H2 = st("H2", 15, 19, "A-B", space_after=3, space_before=16)
H2SUB = st("H2SUB", 9.5, 13.5, color=SOFT, space_after=9)
BODY = st("BODY", 10, 14.5, space_after=6)
NAME = st("NAME", 10.5, 14, "A-B")
CELL = st("CELL", 9.2, 12.6)
CELLS = st("CELLS", 9.2, 12.6, color=SOFT)
CELLB = st("CELLB", 9.2, 12.6, color=BAD)
CAP = st("CAP", 8.6, 11.6, color=SOFT)
EYE = st("EYE", 8, 11, "A-B", color=ACC)
FOOT = st("FOOT", 8, 11, color=SOFT)

# ВСЁ НИЖЕ (ANGLE/PROP/CUFF) ВЫПОЛНЕНО пересъёмкой 6.09.2026 — заказчик
# прислал все запрошенные кадры (см. bot/jewelry/gallery/imladris/NEEDS_REVIEW.md,
# раздел «Решено пересъёмкой 6.09.2026»). Списки оставлены заполненными как
# образец формата на случай новой пересъёмки; main() ниже отказывается
# генерировать PDF, пока ALL_RESOLVED = True. Для нового задания нужно
# обновить списки и тексты, затем снять флаг — иначе легко повторно
# отправить фотографу задание на то, что уже переснято.
ALL_RESOLVED = True

# (ключ товара, индекс кадра для миниатюры, название, что сейчас, что снять)
ANGLE = [
    ("kulony-2__zimniy-les", 2, "Кулон «Зимний Лес»",
     "все четыре кадра сняты лёжа на боку на чёрном камне; в вырезе кулон читается узкой "
     "пластиной, а камень отделить не удалось — и оправа, и камень тёмные",
     "кулон висит на цепочке анфас, на светлом или сером фоне"),
    ("sergi__yagodnye", 0, "Серьги «Ягодные»",
     "в папке ровно одно фото, серьги лежат плашмя на ткани — на ухе будут видны «сверху»",
     "пара висит на подставке, крючками вверх, с просветом"),
    ("sergi__noch", 2, "Серьги «Ночь»",
     "ни один кадр не годится целиком: там, где серьги видны полностью, их перья сливаются "
     "в одно пятно и пару не разделить на две серьги; на выбранном кадре пара делится, но "
     "перья обрезаны краем фотографии",
     "пара висит на подставке, крючками вверх, с просветом между серьгами и целиком в кадре"),
]

PROP = [
    ("zakolki__shpilka-s-imitatsiey-biryuzy", 0, "Шпилька с имитацией бирюзы",
     "все три кадра — на керамическом блюде, шпилька лежит на нём по всей длине; "
     "в вырезе вдоль стержня осталась полоска блюда",
     "шпилька сбоку, целиком со стержнем, на однотонном фоне без блюда"),
    ("kulony-2__tumannost", 0, "Кулон «Туманность»",
     "лежит вплотную к чёрному камню-подставке; сверху выреза остался тёмный клин",
     "кулон висит на цепочке анфас, на светлом фоне"),
    ("kulony-2__teplyy-yantar", 1, "Кулон «Тёплый янтарь»",
     "снят на глянце, отражение приросло к оправе снизу; след остался и после подрезки",
     "тот же ракурс, но на матовой поверхности"),
]

CUFF = [
    ("kaffy__yagody-i-listya", 1, "Каффы — 9 штук",
     "сняты лежащими на столе и на болванке; примерить их сейчас некуда — "
     "бот сажает серьгу на мочку, а кафф носится на ушной раковине",
     "каждый кафф надет на ухо (можно на макет уха), вид сбоку — "
     "тогда каффы можно будет добавить в примерочную"),
]

CATS = [
    ("Серьги", "Пара висит на подставке, крючками вверх, анфас, с просветом между серьгами",
     "Лежат плашмя на столе"),
    ("Кулон, колье", "Висит на шнуре или цепочке, подвесом вверх, анфас", "Лежит на боку или на камне"),
    ("Кольцо", "Надето на палец, тыльная сторона кисти к камере", "Лежит на блюдце, снято сверху"),
    ("Браслет", "Надет на запястье, тыльная сторона кисти к камере", "Разложен прямой линией"),
    ("Брошь", "Приколота к однотонной ткани, анфас", "Снята ребром"),
    ("Диадема, венец", "Анфас на болванке", "Сбоку или в три четверти"),
    ("Заколка, шпилька", "Сбоку, целиком со стержнем", "Только головка, без стержня"),
    ("Кафф", "Надет на ухо или на макет уха", "Лежит на столе"),
]

CHECK = [
    ("Ракурс — как носят", "сверьтесь с таблицей. Единственный пункт, который потом не исправить"),
    ("Фон контрастен по яркости", "светлое украшение на тёмном фоне, тёмное — на светлом или сером"),
    ("Поверхность матовая", "с глянца отражение прирастает к украшению"),
    ("Реквизит не касается украшения", "подставку сзади можно обрезать, кружку под украшением — нет"),
    ("Между серьгами в паре — просвет", "иначе пару не разобрать на две серьги"),
    ("Украшение целиком в кадре", "обрезанное краем фотографии обрезанным и останется"),
    ("Цепочка короткая", "2–3 см подвеса в кадре, длинную всё равно отрезаем"),
    ("Украшение крупно", "хотя бы треть кадра по длинной стороне"),
    ("Без пальцев на украшении", "руки в кадре вырезаются вместе с ним"),
    ("Не поворачивать в редакторе", "наклон выправится сам"),
]


def prepare_thumbs() -> dict[str, str]:
    """Кладёт миниатюры товаров в work/brief_img/ и возвращает пути по ключу."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    items = {i["key"]: i for i in json.loads(ITEMS_JSON.read_text(encoding="utf-8"))}
    paths = {}
    for group in (ANGLE, PROP, CUFF):
        for key, idx, *_ in group:
            src = items[key]["photos"][idx]
            img = Image.open(src).convert("RGB")
            img.thumbnail((300, 300), Image.LANCZOS)
            square = Image.new("RGB", (300, 300), (255, 255, 255))
            square.paste(img, ((300 - img.width) // 2, (300 - img.height) // 2))
            out = IMG_DIR / f"{key}.jpg"
            square.save(out, "JPEG", quality=88)
            paths[key] = str(out)
    return paths


def page_furniture(canvas, doc):
    canvas.saveState()
    canvas.setFont("A", 8)
    canvas.setFillColor(SOFT)
    canvas.drawString(20 * mm, 12 * mm,
                      "studio_imladris · задание на пересъёмку для бота-примерочной")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, str(canvas.getPageNumber()))
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def item_row(thumb, name, problem, need):
    right = Table([[Paragraph(name, NAME)],
                   [Paragraph("<b>Сейчас:</b> " + problem, CELLB)],
                   [Paragraph("<b>Снять:</b> " + need, CELL)]], colWidths=[118 * mm])
    right.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    row = Table([[RLImage(thumb, 30 * mm, 30 * mm), right]], colWidths=[34 * mm, 122 * mm])
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("LEFTPADDING", (1, 0), (1, 0), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
    ]))
    return KeepTogether([row, Spacer(1, 4)])


def main() -> None:
    if ALL_RESOLVED:
        print(
            "ANGLE/PROP/CUFF помечены как решённые (ALL_RESOLVED = True) — "
            "пересъёмка 6.09.2026 закрыла все текущие пункты. Если появились "
            "новые проблемные позиции: допишите их в списки и снимите флаг."
        )
        return
    thumbs = prepare_thumbs()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                          leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=18 * mm, bottomMargin=20 * mm,
                          title="Задание на пересъёмку", author="studio_imladris")
    doc.addPageTemplates([PageTemplate(id="main", onPage=page_furniture, frames=[
        Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])

    s = [Paragraph("ЗАДАНИЕ ФОТОГРАФУ", EYE), Spacer(1, 4),
         Paragraph("Пересъёмка для бота-примерочной", H1),
         Paragraph(
             "В группе работает бот-примерочная: человек присылает своё фото, и бот надевает "
             "на него украшение из каталога. Каталог собран из архива студии — 78 товаров "
             "готовы. Ниже 6 позиций, где кадр не подошёл, и каффы — по желанию.", LEDE),
         Paragraph(
             "Нужен <b>один технический кадр на товар</b>. Он может быть скучным — его никто "
             "не увидит, из него вырезается картинка для примерки. Постановочные снимки для "
             "группы это не заменяет.", LEDE),
         Spacer(1, 10)]

    total = Table([[Paragraph("<b>3</b>", st("n", 15, 17, "A-B", color=ACC)),
                    Paragraph("ракурс не тот —<br/>нужен другой кадр", FOOT),
                    Paragraph("<b>3</b>", st("n", 15, 17, "A-B", color=ACC)),
                    Paragraph("в вырезе остался<br/>реквизит", FOOT),
                    Paragraph("<b>9</b>", st("n", 15, 17, "A-B", color=ACC)),
                    Paragraph("каффы —<br/>по желанию", FOOT)]],
                  colWidths=[10 * mm, 42 * mm, 10 * mm, 38 * mm, 10 * mm, 46 * mm])
    total.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    s.append(total)

    for title, sub, group in [
        ("Ракурс не тот",
         "Кадры есть, но украшение снято не так, как носится. Повернуть картинку мало — "
         "нужен другой кадр.", ANGLE),
        ("В вырезе остался реквизит",
         "Вырез получился, но не начисто. Ракурс правильный — достаточно переснять на "
         "другом фоне.", PROP),
        ("Каффы — по желанию",
         "Не срочно: сейчас каффов в примерочной нет. Если снять их надетыми, категорию "
         "можно будет добавить.", CUFF),
    ]:
        s.append(Paragraph(title, H2))
        s.append(Paragraph(sub, H2SUB))
        for key, _idx, name, problem, need in group:
            s.append(item_row(thumbs[key], name, problem, need))

    hand = EXAMPLES_DIR / "_brief_ring_hand.jpg"
    dish = EXAMPLES_DIR / "_brief_ring_dish.jpg"
    if hand.exists() and dish.exists():
        s.append(Paragraph("Почему ракурс важнее чистого фона", H2))
        s.append(Paragraph(
            "Одно и то же кольцо «Особенное», примеренное на одну и ту же руку. Слева картинка "
            "вырезана с кадра «надето на палец», справа — с кадра на стеклянном блюдце.", H2SUB))
        pair = Table([[RLImage(str(hand), 74 * mm, 71 * mm), RLImage(str(dish), 74 * mm, 71 * mm)],
                      [Paragraph("<b>С кадра на пальце.</b> Дужка обрывается ровно по краям "
                                 "пальца — кольцо читается надетым.", CAP),
                       Paragraph("<b>С кадра на блюдце.</b> Кольцо снято сверху, дужки не видно "
                                 "вовсе — получается наклейка поверх пальца.", CAP)]],
                     colWidths=[78 * mm, 78 * mm])
        pair.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, 0), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 1), (-1, 1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        s.append(KeepTogether(pair))

    s.append(PageBreak())
    s += [Paragraph("КАК СНИМАТЬ", EYE), Spacer(1, 4),
          Paragraph("Требования к техническому кадру", H1),
          Paragraph(
              "Главное — ракурс: украшение должно быть снято так, как его носят. Это "
              "единственное, что нельзя исправить потом. Реквизит убирается, кадр подрезается, "
              "наклон выправляется поворотом — а вид спереди из вида сверху не получить ничем.",
              LEDE),
          Spacer(1, 10)]

    data = [[Paragraph("<b>Категория</b>", CELL), Paragraph("<b>Нужен кадр</b>", CELL),
             Paragraph("<b>Не подходит</b>", CELL)]]
    for c, g, b in CATS:
        data.append([Paragraph(c, CELL), Paragraph(g, CELLS), Paragraph(b, CELLB)])
    table = Table(data, colWidths=[32 * mm, 78 * mm, 46 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    s.append(table)

    s.append(Paragraph("Перед тем как снимать", H2))
    s.append(Paragraph("Каждый пункт экономит час ручной доводки.", H2SUB))
    rows = [[Paragraph(f"{i:02d}", st("cn", 9, 12.6, "A-B", color=ACC)),
             Paragraph(f"<b>{head}</b> — {tail}", CELL)]
            for i, (head, tail) in enumerate(CHECK, 1)]
    check = Table(rows, colWidths=[10 * mm, 146 * mm])
    check.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -2), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    s.append(check)

    s.append(Paragraph("Как передать файлы", H2))
    s.append(Paragraph(
        "Папка на товар, внутри — все кадры этого товара; папки разложены по разделам: "
        "«Серьги», «Кулоны», «Кольца» и так далее. Ровно так, как сделана папка assets/source_photos — "
        "эта структура читается напрямую.", BODY))
    s.append(Paragraph(
        "Если zip собирается на Windows, а распаковывается на Mac, кириллица в именах папок "
        "ломается: «Предание» превращается в «Па•§†≠®•». Это чинится, но надёжнее передать "
        "папку как есть или zip-ом, собранным на Mac.", BODY))

    doc.build(s)
    print("готово:", OUT, f"({OUT.stat().st_size / 1024:.0f} КБ)")


if __name__ == "__main__":
    main()
