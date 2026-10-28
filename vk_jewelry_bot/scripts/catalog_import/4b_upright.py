"""
Шаг 4b — развернуть украшение так, как его носят: серьги и кулоны
вертикально, браслет — поперёк руки.

Зачем: часть украшений сфотографирована лежащими на столе — по диагонали или
поперёк кадра. Бот вешает картинку на ухо (или на шею) как есть, поэтому
такая серьга торчит вбок, а кулон ложится поперёк груди. Разворот вырезанного
PNG чинит это раз и навсегда — в отличие от поля rotation_offset, которое
пришлось бы подбирать вручную каждому.

Важно: это поворот в плоскости кадра. Он не выдумывает новых данных и не
меняет ракурс съёмки: если украшение снято сбоку или сверху, поворот этого
не исправит — нужен другой кадр (шаг 3, make_overrides.py).

Как считается угол:
- картинка разбирается на отдельные детали (у пары серёг их две, у кулона
  одна) — те же связные компоненты, что и в самом боте;
- у каждой детали считается главная ось (PCA по пикселям маски) — это
  направление, вдоль которого украшение вытянуто;
- берётся медиана углов по деталям, и картинка доворачивается на минимальный
  угол до вертикали.

Где верх — НЕ определяется автоматически. Пробовалось «тяжёлый конец вниз»
(у серьги внизу бусины, вверху тонкий крючок) — эвристика переворачивала
вверх ногами кулон «Золотое сердце», «Шёлковые травы» и серьги «Лесное лето»,
у которых верх как раз массивнее низа. Надёжного признака нет, поэтому
разворот на 180° задаётся вручную в UPRIGHT_OVERRIDES по результатам
просмотра контактного листа (6_review_sheet.py).

Повторный запуск безопасен: что уже развёрнуто, записано в work/upright.json
вместе со временем правки файла. Если шаг 4 пересчитал вырез заново, запись
устаревает и картинка обрабатывается снова — с чистого, неповёрнутого файла.

    ../../../.venv-import/bin/python 4b_upright.py            # серьги и кулоны
    ../../../.venv-import/bin/python 4b_upright.py --dry      # только показать углы
    ../../../.venv-import/bin/python 4b_upright.py pendant    # только кулоны
    ../../../.venv-import/bin/python 4b_upright.py --force    # заново, игнорируя журнал
"""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np
from PIL import Image

from paths import CUTOUT_DIR, PICKS_JSON, WORK_DIR

LEDGER_PATH = WORK_DIR / "upright.json"

# Куда разворачивать главную ось: 90° — вертикально (украшение висит),
# 0° — горизонтально. Браслет носится поперёк руки, поэтому его полоса
# должна лежать вдоль строки, а не вдоль столбца: бот приравнивает длинную
# сторону картинки к ширине запястья.
TARGET_ANGLE = {"earrings": 90.0, "pendant": 90.0, "beads": 90.0, "bracelet": 0.0}
UPRIGHT_CATEGORIES = tuple(TARGET_ANGLE)
MIN_ELONGATION = 1.25   # ниже этого деталь считаем «круглой»: ось не определена
MIN_ANGLE = 8.0         # меньше этого не крутим — незачем портить пиксели
# У пары серёг деталей две, у кулона одна: сколько компонент брать в расчёт оси.
PARTS_BY_CATEGORY = {"earrings": 2, "pendant": 1, "beads": 1, "bracelet": 1}

# Ручные поправки по результатам просмотра (ключ товара -> действие):
#   "skip"  — не трогать это украшение вовсе,
#   "flip"  — после выравнивания оси довернуть на 180° (украшение встало
#             вертикально, но вверх ногами),
#   число   — повернуть ровно на столько градусов вместо автоматики.
#
# hairpin НЕ входит в UPRIGHT_CATEGORIES (см. main()) и по умолчанию этим
# шагом не трогается — у широкой «головы» шпильки главная ось (PCA) часто
# горизонтальна даже когда шпилька стоит правильно: пробный прогон
# `4b_upright.py hairpin` развернул на ~88° «заколку-автомат Солнечный
# зайчик», которая и так была в порядке. Но `4b_upright.py hairpin` всё
# же можно вызвать явно (main() не проверяет категорию против списка) —
# поэтому ниже пофайлово: "skip" всем, кроме кадров, снятых явно по
# диагонали (целиком со стержнем/в кулаке, а не «уже вертикально в
# кадре») — там автоматика посчитала угол верно, проверено глазами (по
# фото фиста — направление, в котором торчит из кулака, и есть направление,
# в котором должно торчать из головы, см. чат с заказчиком).
#
# Не входят в это правило (см. вопрос заказчику): «заколка-автомат
# Солнечный зайчик» — клипса-автомат (заколка-краб), для нее вертикально/
# горизонтально — не то же самое, что для шпильки-стержня.
UPRIGHT_OVERRIDES: dict[str, object] = {
    "zakolki__zakolka-avtomat-solnechnyy-zaychik": "skip",
    "zakolki__groza": 80.0,
    "zakolki__leto": "skip",
    "zakolki__shpilka-s-imitatsiey-biryuzy": 68.8,
    "zakolki__shpilka-fibula-vesna": -74.9,
    "zakolki__solnechnye-bliki": "skip",
    "zakolki__shpilka-s-yashmoy": "skip",
    "zakolki__yagody": "skip",
}


def piece_axis(mask: np.ndarray) -> tuple[float, float] | None:
    """Угол главной оси детали (в градусах, 90 = вертикально) и вытянутость."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return None
    pts = np.stack([xs - xs.mean(), ys - ys.mean()])
    values, vectors = np.linalg.eigh(np.cov(pts))
    major = vectors[:, np.argmax(values)]
    elongation = float(np.sqrt(max(values) / max(1e-6, min(values))))
    angle = float(np.degrees(np.arctan2(major[1], major[0])) % 180)
    return angle, elongation


def analyse(path, max_parts: int = 2) -> dict:
    img = Image.open(path).convert("RGBA")
    alpha = np.array(img.split()[-1])
    n, labels, stats, _ = cv2.connectedComponentsWithStats((alpha >= 128).astype(np.uint8), 8)
    parts = sorted(((int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, n)), reverse=True)
    if not parts:
        return {"ok": False}
    keep = [i for a, i in parts if a >= parts[0][0] * 0.30][:max_parts]

    angles, elongs = [], []
    for label in keep:
        got = piece_axis(labels == label)
        if got:
            angles.append(got[0])
            elongs.append(got[1])
    if not angles:
        return {"ok": False}

    # Углы живут по кругу (179° и 1° — почти одно и то же), поэтому усредняем
    # через удвоенный угол, а не арифметически.
    doubled = np.radians(np.array(angles) * 2)
    mean = float(np.degrees(np.arctan2(np.sin(doubled).mean(), np.cos(doubled).mean())) / 2 % 180)
    return {"ok": True, "angle": mean, "elongation": float(np.median(elongs)), "img": img}


def _save(img: Image.Image, path, dry: bool) -> Image.Image:
    bbox = img.split()[-1].getbbox()
    if bbox:
        img = img.crop(bbox)
    if not dry:
        img.save(path)
    return img


def upright(path, dry: bool = False, max_parts: int = 2, override=None,
            target: float = 90.0) -> dict:
    if override == "skip":
        return {"changed": False, "reason": "выключено вручную"}

    if isinstance(override, (int, float)):
        img = Image.open(path).convert("RGBA").rotate(float(override), expand=True,
                                                      resample=Image.BICUBIC)
        img = _save(img, path, dry)
        return {"changed": True, "turn": float(override), "size": list(img.size)}

    info = analyse(path, max_parts)
    if not info["ok"]:
        return {"changed": False, "reason": "маска пустая"}

    turn = 0.0
    if info["elongation"] < MIN_ELONGATION:
        reason = f"деталь круглая (вытянутость {info['elongation']:.2f})"
    else:
        # Знак проверен на контрольной фигуре с известным наклоном: при
        # rotate(-turn) отклонение не убиралось, а удваивалось.
        turn = info["angle"] - target
        if turn > 90:
            turn -= 180
        if turn < -90:
            turn += 180
        reason = f"ось уже на месте ({turn:+.1f}°)"
        if abs(turn) < MIN_ANGLE:
            turn = 0.0

    if override == "flip":
        turn += 180

    if turn == 0.0:
        return {"changed": False, "reason": reason}

    img = _save(info["img"].rotate(turn, expand=True, resample=Image.BICUBIC), path, dry)
    return {"changed": True, "turn": round(turn, 1), "size": list(img.size)}


def main() -> None:
    dry = "--dry" in sys.argv
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    categories = only or list(UPRIGHT_CATEGORIES)

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8")) if LEDGER_PATH.exists() else {}
    picks = json.loads(PICKS_JSON.read_text(encoding="utf-8"))

    for pick in picks:
        if pick["category"] not in categories:
            continue
        path = CUTOUT_DIR / pick["category"] / f"{pick['slug']}.png"
        if not path.exists():
            continue

        stamp = int(path.stat().st_mtime_ns)
        done = ledger.get(pick["key"])
        if done and done.get("source_mtime") == stamp and not force:
            continue

        res = upright(path, dry, PARTS_BY_CATEGORY.get(pick["category"], 1),
                      UPRIGHT_OVERRIDES.get(pick["key"]),
                      TARGET_ANGLE.get(pick["category"], 90.0))
        mark = f"поворот {res['turn']:+.1f}°" if res["changed"] else f"без поворота — {res['reason']}"
        print(f"{pick['category']:9s} {pick['title']:36s} {mark}")
        if not dry:
            ledger[pick["key"]] = {
                "source_mtime": int(path.stat().st_mtime_ns),
                "turn": res.get("turn", 0.0),
            }

    if not dry:
        LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
