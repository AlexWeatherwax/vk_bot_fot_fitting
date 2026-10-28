"""
Шаг 4 — сделать из выбранного кадра итоговый PNG с прозрачным фоном.

Отличия от старого скрипта импорта (scripts/imladris_import/2_remove_background.py):
- модель birefnet-general вместо u2net: заметно аккуратнее с тонкой
  проволокой и цепочками, и не тащит за собой манекен;
- перед вырезанием кадр можно предварительно обрезать (options.json) —
  это единственный надёжный способ убрать реквизит, который стоит вплотную
  к украшению (кружка, подставка, книга под серьгами);
- после вырезания выбрасываются мелкие ошмётки маски, но сохраняются
  крупные — у пары серёг это две отдельные детали;
- есть точечные приёмы для сложных случаев: вычитание кожи (кольцо на
  пальце), обрезание длинной цепочки, удаление отражения снизу.

Все точечные настройки — в options.json, по ключу товара.
"""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove

from imgproc import keep_significant_components
from paths import CUTOUT_DIR, PICKS_JSON, WORK_DIR

OPTIONS_JSON = WORK_DIR.parent / "options.json"
DEFAULT_MODEL = "birefnet-general"
WORK_SIZE = 1600          # к этому размеру ужимаем кадр перед вырезанием
MAX_OUTPUT = 1400         # максимальная сторона итогового PNG
ALPHA_LO, ALPHA_HI = 40, 190   # растяжка альфы: убирает полупрозрачную «дымку»

_sessions: dict[str, object] = {}


def session_for(name: str):
    if name not in _sessions:
        _sessions[name] = new_session(name)
    return _sessions[name]


def apply_crop(img: Image.Image, crop) -> Image.Image:
    """crop = [left, top, right, bottom] в долях размера кадра."""
    if not crop:
        return img
    w, h = img.size
    l, t, r, b = crop
    box = (int(l * w), int(t * h), int(r * w), int(b * h))
    return img.crop(box)


def stretch_alpha(alpha: np.ndarray) -> np.ndarray:
    """
    Растягивает альфу так, чтобы почти-прозрачный «туман» стал нулём,
    а почти-непрозрачное — 255. Бот всё равно обнуляет альфу ниже 160
    (bot/tryon/pipeline.py), так что мягкий полупрозрачный край для него
    бесполезен, а вот дымка по всему кадру — вредна.
    """
    a = alpha.astype(np.float32)
    a = (a - ALPHA_LO) * (255.0 / (ALPHA_HI - ALPHA_LO))
    return np.clip(a, 0, 255).astype(np.uint8)


def subtract_skin(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    Убирает из маски кожу — так из кадра «кольцо на пальце» остаётся само
    кольцо. Работает именно здесь, потому что фон уже отрезан моделью:
    внутри маски только рука и украшение.
    """
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycrcb[..., 0], ycrcb[..., 1], ycrcb[..., 2]
    skin = (y > 60) & (cr >= 135) & (cr <= 180) & (cb >= 77) & (cb <= 130)
    skin = cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    skin = cv2.dilate(skin, np.ones((5, 5), np.uint8))
    return mask & (skin == 0)


def auto_trim_radius(mask: np.ndarray) -> int:
    """
    Радиус эрозии для отрезания цепочки, подобранный под конкретную картинку.

    Берём преобразование расстояний: у тела кулона максимум большой (это
    «полутолщина» самой толстой части), у цепочки — маленький. Радиус в
    треть от максимума гарантированно съедает цепочку и не съедает тело.
    """
    dist = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return int(max(5, min(25, dist.max() * 0.33)))


def trim_thin(mask: np.ndarray, radius: int, grow: float = 2.0) -> np.ndarray:
    """
    Отрезает тонкие «хвосты» — длинную цепочку у кулона, оставляя сам кулон
    и короткий кусочек подвеса. Нужно потому, что цепочку на шее бот рисует
    сам (поле chain_color), и вторая цепочка, уходящая с картинки вбок,
    ломает и композицию, и точку крепления (она считается от верха картинки).

    Как это работает: эрозия радиусом radius полностью съедает всё тоньше
    2*radius (цепочку), но оставляет тело кулона. Дальше тело наращивается
    обратно строго внутри исходной маски (геодезическая дилатация) — так
    возвращаются тонкие завитки самой проволоки, приросшие к телу, а
    цепочка успевает отрасти лишь на radius*grow пикселей.
    """
    m = mask.astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    core = cv2.erode(m, k)
    if core.sum() == 0:
        return mask
    core = keep_significant_components(core.astype(bool), 0.25).astype(np.uint8)
    step = np.ones((3, 3), np.uint8)
    grown = core
    for _ in range(int(radius * grow)):
        grown = cv2.dilate(grown, step) & m
    return grown.astype(bool)


def drop_dark(rgb: np.ndarray, mask: np.ndarray, luma_min: int) -> np.ndarray:
    """
    Выбрасывает из маски всё темнее порога.

    Спасает кадры, снятые на чёрном манекене или чёрном камне: модель считает
    манекен частью объекта (украшение лежит прямо на нём), но само украшение —
    светлый металл, а манекен почти чёрный, так что по яркости они делятся
    чисто. Морфологическое замыкание после порога сшивает проволоку обратно
    в единую линию там, где по ней прошла тень.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    m = (gray >= luma_min) & mask
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return m.astype(bool)


def poly_mask(shape, polys) -> np.ndarray:
    """Растровая маска по списку многоугольников, заданных в долях кадра."""
    h, w = shape
    out = np.zeros((h, w), np.uint8)
    for poly in polys:
        pts = np.array([[int(x * w), int(y * h)] for x, y in poly], np.int32)
        cv2.fillPoly(out, [pts], 1)
    return out.astype(bool)


def drop_reflection(mask: np.ndarray, split: float) -> np.ndarray:
    """Отрезает всё ниже доли split по высоте bbox — так убирается отражение
    предмета в глянцевой поверхности стола."""
    ys, _ = np.where(mask)
    if len(ys) == 0:
        return mask
    y0, y1 = ys.min(), ys.max()
    cut = int(y0 + (y1 - y0) * split)
    out = mask.copy()
    out[cut:, :] = False
    return out


def process(pick: dict, opts: dict) -> dict:
    src = Image.open(pick["photo"])
    try:
        from PIL import ImageOps
        src = ImageOps.exif_transpose(src)
    except Exception:
        pass
    src = src.convert("RGB")
    src = apply_crop(src, opts.get("crop"))
    src.thumbnail((WORK_SIZE, WORK_SIZE), Image.LANCZOS)

    cut = remove(src, session=session_for(opts.get("model", DEFAULT_MODEL)))
    arr = np.array(cut)
    arr[:, :, 3] = stretch_alpha(arr[:, :, 3])
    rgb = np.array(src)

    mask = arr[:, :, 3] >= 128
    if not mask.any():
        return {"ok": False, "reason": "модель не нашла объект"}

    if opts.get("remove_skin"):
        mask = subtract_skin(rgb, mask)
    if opts.get("luma_min"):
        mask = drop_dark(rgb, mask, int(opts["luma_min"]))
    if opts.get("keep_polys"):
        mask = mask & poly_mask(mask.shape, opts["keep_polys"])
    if opts.get("erase_polys"):
        mask = mask & ~poly_mask(mask.shape, opts["erase_polys"])
    trim = opts.get("trim_chain")
    if trim:
        mask = trim_thin(mask, auto_trim_radius(mask) if trim is True else int(trim))
    if opts.get("reflection_split"):
        mask = drop_reflection(mask, float(opts["reflection_split"]))

    mask = keep_significant_components(mask, float(opts.get("min_component", 0.12)))
    if not mask.any():
        return {"ok": False, "reason": "после чистки маска опустела"}

    arr[:, :, 3] = np.where(mask, arr[:, :, 3], 0)
    out = Image.fromarray(arr, "RGBA")

    bbox = out.split()[-1].getbbox()
    x0, y0, x1, y1 = bbox
    pad_x = max(2, int((x1 - x0) * 0.02))
    pad_y = max(2, int((y1 - y0) * 0.02))
    out = out.crop((max(0, x0 - pad_x), max(0, y0 - pad_y),
                    min(out.width, x1 + pad_x), min(out.height, y1 + pad_y)))

    if max(out.size) > MAX_OUTPUT:
        s = MAX_OUTPUT / max(out.size)
        out = out.resize((max(1, int(out.width * s)), max(1, int(out.height * s))), Image.LANCZOS)

    subdir = pick["category"] or "_без_категории"
    path = CUTOUT_DIR / subdir / f"{pick['slug']}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)

    area = float(mask.sum())
    return {"ok": True, "path": str(path), "size": list(out.size),
            "fill": round(area / max(1, (x1 - x0) * (y1 - y0)), 3)}


def main() -> None:
    picks = json.loads(PICKS_JSON.read_text(encoding="utf-8"))
    options = json.loads(OPTIONS_JSON.read_text(encoding="utf-8")) if OPTIONS_JSON.exists() else {}
    only = set(sys.argv[1:])

    report = []
    todo = [p for p in picks if not only or p["key"] in only]
    for n, pick in enumerate(todo, 1):
        info = process(pick, options.get(pick["key"], {}))
        info.update({k: pick[k] for k in ("key", "section", "title", "category", "chosen")})
        report.append(info)
        print(f"[{n}/{len(todo)}] {pick['section']}/{pick['title']} #{pick['chosen']} -> "
              f"{info.get('size') or info.get('reason')}", flush=True)

    out_path = WORK_DIR / "cutout_report.json"
    if only and out_path.exists():   # частичный прогон — дополняем прошлый отчёт
        prev = {r["key"]: r for r in json.loads(out_path.read_text(encoding="utf-8"))}
        prev.update({r["key"]: r for r in report})
        report = list(prev.values())
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Готово:", out_path)


if __name__ == "__main__":
    main()
