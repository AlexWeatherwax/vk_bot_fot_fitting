"""
Шаг 3 — выбрать из нескольких фото одного украшения тот кадр, который лучше
всего подходит для примерки.

Что считаем плохим кадром:
- в кадре рука (модель вырежет её вместе с украшением) — признак skin_frac;
- украшение снято на реквизите, который вырезается заодно (стеклянное блюдце,
  кружка, манекен-голова, камень-подставка) — признак fill: у сплошного
  предмета силуэт заполняет свой bbox почти целиком, у украшения — нет;
- объект упирается в край кадра (обрезан, или реквизит на весь кадр) —
  признак border_frac;
- украшение слишком мелкое в кадре — потеряются детали.

Выбор можно переопределить вручную в overrides.json:
    {"sergi__priboy": 3}   # ключ товара -> индекс фото
"""
from __future__ import annotations

import json

from paths import ITEMS_JSON, OVERRIDES_JSON, PICKS_JSON, SCREEN_JSON


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_photo(info: dict, item: dict, max_sharp: float) -> tuple[float, list[str]]:
    if info.get("empty"):
        return -99.0, ["пустая маска"]

    notes: list[str] = []
    score = 0.0

    # Рука в кадре: до 0.03 — это блики/тёплый металл, дальше уже кожа.
    skin = info["skin_frac"]
    if skin > 0.03:
        pen = 6.0 * clamp01((skin - 0.03) / 0.25)
        score -= pen
        if pen > 1.5:
            notes.append(f"рука в кадре ({skin:.2f})")

    # Монолитный силуэт = вырезался реквизит, а не только украшение.
    fill = info["fill"]
    if fill > 0.42:
        pen = 5.0 * clamp01((fill - 0.42) / 0.4)
        score -= pen
        if pen > 1.0:
            notes.append(f"похоже на реквизит (fill={fill:.2f})")

    # Объект упирается в край кадра.
    border = info["border_frac"]
    pen = 3.0 * clamp01(border / 0.10)
    score -= pen
    if pen > 1.0:
        notes.append(f"упирается в край ({border:.3f})")

    # Размер объекта в кадре: комфортная зона 0.08..0.45.
    area = info["area_frac"]
    if area < 0.08:
        score -= 3.0 * clamp01((0.08 - area) / 0.07)
        notes.append(f"мелко в кадре ({area:.3f})")
    elif area > 0.45:
        score -= 2.0 * clamp01((area - 0.45) / 0.3)

    # Резкость — сравниваем внутри одного товара.
    if max_sharp > 0:
        score += 1.5 * clamp01(info["sharpness"] / max_sharp)

    # Разрешение исходника: детали важнее всего при масштабировании.
    w, h = info["size"]
    score += 0.4 * clamp01((w * h) / (1024 * 1024))

    # Для серёг пара в кадре (две одинаковые детали) — то, что нужно.
    if item["category"] == "earrings" and info["n_components"] == 2:
        score += 0.5

    return score, notes


def main() -> None:
    items = json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    screen = json.loads(SCREEN_JSON.read_text(encoding="utf-8"))
    overrides = (
        json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))
        if OVERRIDES_JSON.exists() else {}
    )

    picks = []
    for item in items:
        entries = screen.get(item["key"], [])
        if not entries:
            continue
        max_sharp = max((e.get("sharpness", 0.0) for e in entries), default=0.0)
        scored = []
        for e in entries:
            s, notes = score_photo(e, item, max_sharp)
            scored.append({"index": e["index"], "score": round(s, 3), "notes": notes,
                           "path": e["path"]})
        scored.sort(key=lambda d: -d["score"])

        forced = overrides.get(item["key"])
        chosen = forced if forced is not None else scored[0]["index"]
        picks.append({
            **{k: item[k] for k in ("key", "section", "title", "category", "slug")},
            "chosen": chosen,
            "forced": forced is not None,
            "photo": item["photos"][chosen],
            "ranking": scored,
            "notes": next((d["notes"] for d in scored if d["index"] == chosen), []),
        })

    PICKS_JSON.write_text(json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8")

    flagged = [p for p in picks if p["notes"]]
    print(f"Выбрано кадров: {len(picks)}; с замечаниями: {len(flagged)}")
    for p in flagged:
        print(f"  {p['section']:10s} | {p['title']:38s} #{p['chosen']} — {', '.join(p['notes'])}")


if __name__ == "__main__":
    main()
