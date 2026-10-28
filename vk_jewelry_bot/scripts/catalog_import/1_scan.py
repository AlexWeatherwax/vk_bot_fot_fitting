"""
Шаг 1 — собрать список товаров из assets/source_photos/ или JEWELRY_SOURCE_DIR.

Каждая подпапка нижнего уровня = один товар, внутри — несколько фото
одного и того же украшения. Результат — work/items.json.
"""
from __future__ import annotations

import json
from common import CATEGORY_BY_FOLDER, category_for, demojibake, slugify
from paths import ITEMS_JSON, SOURCE_DIR, WORK_DIR

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(
            f"Не найдена папка исходных фотографий: {SOURCE_DIR}\n"
            "Поместите архив в assets/source_photos/ в корне репозитория "
            "или задайте путь переменной JEWELRY_SOURCE_DIR."
        )
    items = []
    skipped_empty = []
    for folder in sorted(SOURCE_DIR.iterdir()):
        if not folder.is_dir():
            continue
        section = demojibake(folder.name)
        for sub in sorted(folder.iterdir()):
            if not sub.is_dir():
                continue
            title = demojibake(sub.name)
            category = category_for(section, title)
            photos = sorted(
                p for p in sub.iterdir()
                if p.suffix.lower() in IMAGE_EXT and not p.name.startswith(".")
            )
            if not photos:
                skipped_empty.append(f"{section}/{title}")
                continue
            items.append({
                "key": f"{slugify(section)}__{slugify(title)}",
                "section": section,
                "title": title,
                "category": category,
                "slug": slugify(title),
                "dir": str(sub),
                "photos": [str(p) for p in photos],
            })

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ITEMS_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    by_section: dict[str, int] = {}
    for it in items:
        by_section[it["section"]] = by_section.get(it["section"], 0) + 1
    print(f"Товаров: {len(items)}, фотографий: {sum(len(i['photos']) for i in items)}")
    for s, n in by_section.items():
        cat = CATEGORY_BY_FOLDER.get(s)
        print(f"  {s:12s} {n:3d}  -> категория бота: {cat or 'нет'}")
    if skipped_empty:
        print("Пустые папки (пропущены):", ", ".join(skipped_empty))


if __name__ == "__main__":
    main()
