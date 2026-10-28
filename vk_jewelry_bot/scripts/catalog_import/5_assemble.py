"""
Шаг 5 — разложить готовые PNG по галерее бота и обновить manifest.json.

Что делает:
- для товаров, которые уже есть в каталоге (см. mapping.REPLACES), заменяет
  только картинку: id и название остаются прежними, чтобы у пользователей
  не сломался поиск по названию;
- для новых товаров дописывает записи в manifest.json;
- для наборов (комплект из нескольких предметов — единой точки крепления
  нет, категории примерки для них в боте не будет) складывает готовые PNG
  в gallery/imladris/_ready_no_category/ — они не попадают в каталог, но и
  не теряются; каффы с недавних пор такую точку крепления получили (см.
  bot/tryon/pipeline.py) и идут в каталог наравне с остальными категориями;
- перед изменениями делает копию всей галереи в work/gallery_backup/.

ВАЖНО про подстройку: у заменённых записей поля anchor_scale/offset_x/
offset_y/rotation_offset сбрасываются к значениям по умолчанию для
категории. Старые значения подбирались под старую картинку (например,
anchor_scale 0.4 у серёг — потому что на старом вырезе половину кадра
занимала кружка); на новом, чистом вырезе они дали бы неверный масштаб.
"""
from __future__ import annotations

import json
import shutil

from mapping import ENTRY_OVERRIDES, REPLACES, display_name
from paths import CUTOUT_DIR, GALLERY_DIR, MANIFEST_PATH, PICKS_JSON, WORK_DIR

# Значения по умолчанию для категории — сюда сбрасывается подстройка,
# потому что вместе с картинкой поменялась и кадрировка.
TUNING = {
    "earrings": {"anchor_scale": 1.0, "pair_image": True},
    "pendant": {"anchor_scale": 1.0},
    "ring": {"anchor_scale": 1.0},
    "beads": {"anchor_scale": 1.0},
    "diadem": {"anchor_scale": 1.0},
    "hairpin": {"anchor_scale": 1.0},
    "brooch": {"anchor_scale": 1.0},
    "bracelet": {"anchor_scale": 1.0},
    "kaffy": {"anchor_scale": 1.0},
}
NO_CATEGORY_DIR = "_ready_no_category"


def base_entry(category: str) -> dict:
    entry = {
        "anchor_scale": 1.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "rotation_offset": 0.0,
    }
    entry.update(TUNING.get(category, {}))
    return entry


def main() -> None:
    picks = {p["key"]: p for p in json.loads(PICKS_JSON.read_text(encoding="utf-8"))}
    report = json.loads((WORK_DIR / "cutout_report.json").read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in manifest}

    backup = WORK_DIR / "gallery_backup"
    if not backup.exists():
        shutil.copytree(GALLERY_DIR, backup)
        print("Копия старой галереи:", backup)

    replaced, added, parked, failed = [], [], [], []

    for row in report:
        if not row.get("ok"):
            failed.append((row["title"], row.get("reason")))
            continue
        pick = picks[row["key"]]
        src = CUTOUT_DIR / (pick["category"] or "_без_категории") / f"{pick['slug']}.png"
        category = pick["category"]

        if category is None:
            dst = GALLERY_DIR / "imladris" / NO_CATEGORY_DIR / _section_slug(pick["section"]) / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            parked.append(pick["title"])
            continue

        old_id = REPLACES.get((pick["section"], pick["title"]))
        if old_id:
            entry = by_id[old_id]
            dst = GALLERY_DIR / entry["image"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            entry.update(base_entry(entry["category"]))
            entry.update(ENTRY_OVERRIDES.get(pick["key"], {}))
            replaced.append(f'{entry["name"]} -> {entry["image"]}')
        else:
            image_rel = f"imladris/{category}/{pick['slug']}.png"
            new_id = f"imladris_{category}_{pick['slug']}"
            dst = GALLERY_DIR / image_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            entry = {
                "id": new_id,
                "name": display_name(category, pick["title"]),
                "category": category,
                "image": image_rel,
                **base_entry(category),
                **ENTRY_OVERRIDES.get(pick["key"], {}),
            }
            if new_id in by_id:
                # Повторный прогон: запись уже есть — обновляем её на месте,
                # чтобы в manifest.json не появился дубль.
                by_id[new_id].update(entry)
                replaced.append(f'{entry["name"]} -> {image_rel} (обновлено)')
            else:
                manifest.append(entry)
                by_id[new_id] = entry
                added.append(f'{entry["name"]} -> {image_rel}')

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\nЗаменено картинок у существующих записей: {len(replaced)}")
    for r in replaced:
        print("   ", r)
    print(f"\nДобавлено новых записей: {len(added)}")
    for a in added:
        print("   ", a)
    print(f"\nОтложено (нет категории примерки): {len(parked)}")
    print("   ", ", ".join(parked))
    if failed:
        print(f"\nНе удалось: {len(failed)}")
        for t, why in failed:
            print("   ", t, "—", why)
    print(f"\nВсего записей в каталоге: {len(manifest)}")


def _section_slug(section: str) -> str:
    # Каффы теперь получают точку крепления и id в manifest.json (см.
    # common.CATEGORY_BY_FOLDER) — этой веткой (category is None) из всех
    # разделов дальше доходят только «Наборы».
    return {"Наборы": "nabory"}.get(section, "prochee")


if __name__ == "__main__":
    main()
