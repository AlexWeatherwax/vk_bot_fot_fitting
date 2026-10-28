"""
Шаг 2 — прогнать все фотографии через быструю модель удаления фона и
посчитать признаки каждого кадра (есть ли в кадре рука, насколько «монолитный»
силуэт — то есть не прихватило ли блюдце/кружку/манекен, резкость и т.д.).

Тяжёлую качественную модель (birefnet) на этом шаге не гоняем: она в ~15 раз
медленнее, а для сравнения кадров между собой хватает и быстрой.
"""
from __future__ import annotations

import json
import sys

from PIL import Image
from rembg import new_session, remove

from imgproc import describe
from paths import ITEMS_JSON, PREVIEW_DIR, SCREEN_JSON

SCREEN_MODEL = "isnet-general-use"
ANALYSIS_SIZE = 1024      # к этому размеру ужимаем кадр перед анализом
PREVIEW_SIZE = 320


def main() -> None:
    items = json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    session = new_session(SCREEN_MODEL)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    result = {}
    total = sum(len(i["photos"]) for i in items)
    done = 0
    for item in items:
        entries = []
        for idx, path in enumerate(item["photos"]):
            rgb = Image.open(path).convert("RGB")
            rgb.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.LANCZOS)
            cut = remove(rgb, session=session)
            info = describe(cut, rgb)
            info["index"] = idx
            info["path"] = path
            entries.append(info)

            preview = cut.copy()
            preview.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS)
            preview.save(PREVIEW_DIR / f"{item['key']}__{idx}.png")

            done += 1
            print(f"[{done}/{total}] {item['section']}/{item['title']} #{idx} "
                  f"area={info.get('area_frac', 0):.3f} fill={info.get('fill', 0):.2f} "
                  f"skin={info.get('skin_frac', 0):.2f}", flush=True)
        result[item["key"]] = entries

    SCREEN_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Готово:", SCREEN_JSON)


if __name__ == "__main__":
    sys.exit(main())
