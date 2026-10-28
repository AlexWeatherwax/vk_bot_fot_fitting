import json
import re
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
CUTOUT_DIR = HERE / "cutout"
RAW_DIR = HERE / "raw"

# scripts/imladris_import/3_assemble_into_catalog.py -> project root is two levels up
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_GALLERY = PROJECT_ROOT / "bot" / "jewelry" / "gallery"
DEST_DIR = PROJECT_GALLERY / "imladris"

FLAG_AREA_FRACTION = 0.45


def clean_title(title: str) -> str:
    t = title.replace('"', '').replace("«", "").replace("»", "")
    t = re.sub(r"\s+", " ", t).strip()
    # normalize leading category word capitalization e.g. "кулон" -> "Кулон"
    if t:
        t = t[0].upper() + t[1:]
    return t


def main():
    manifest_src = json.loads((HERE / "raw_manifest.json").read_text(encoding="utf-8"))

    catalog_entries = []
    flagged = []
    seen_ids = {}

    for entry in manifest_src:
        raw_path = HERE / entry["raw_path"]
        category = entry["category"]
        slug = raw_path.stem  # already transliterated+slugified from download.py
        cutout_path = CUTOUT_DIR / category / f"{slug}.png"
        if not cutout_path.exists():
            print("MISSING cutout for", entry["title"])
            continue

        with Image.open(raw_path) as ri:
            raw_w, raw_h = ri.size
        with Image.open(cutout_path) as ci:
            cut_w, cut_h = ci.size

        area_fraction = (cut_w * cut_h) / (raw_w * raw_h)

        # copy into project gallery
        dest_sub = DEST_DIR / category
        dest_sub.mkdir(parents=True, exist_ok=True)
        dest_file = dest_sub / f"{slug}.png"
        shutil.copy2(cutout_path, dest_file)

        base_id = f"imladris_{category}_{slug}"
        n = seen_ids.get(base_id, 0)
        seen_ids[base_id] = n + 1
        item_id = base_id if n == 0 else f"{base_id}-{n+1}"

        title_clean = clean_title(entry["title"])

        catalog_entries.append({
            "id": item_id,
            "name": title_clean,
            "category": category,
            "image": f"imladris/{category}/{slug}.png",
            "anchor_scale": 1.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "rotation_offset": 0.0,
        })

        if area_fraction > FLAG_AREA_FRACTION:
            flagged.append({
                "title": title_clean,
                "category": category,
                "image": f"imladris/{category}/{slug}.png",
                "area_fraction": round(area_fraction, 3),
            })

    # merge with existing manifest.json (demo placeholders)
    manifest_path = PROJECT_GALLERY / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    merged = existing + catalog_entries
    manifest_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Added {len(catalog_entries)} items to manifest.json (total now {len(merged)})")
    print(f"Flagged for manual review: {len(flagged)}")

    review_md = ["# Фото, которые стоит проверить/подрезать вручную\n",
                 "Автоматическое удаление фона у этих товаров, скорее всего, "
                 "оставило часть декоративного реквизита (блюдце, ваза, подставка) "
                 "рядом с украшением — сама модель не может отличить "
                 "«украшение» от «предмета, на котором его сфотографировали». "
                 "Перед боевым использованием стоит подрезать эти PNG вручную "
                 "(Photopea/GIMP/Photoshop) под сам предмет.\n"]
    for f in flagged:
        review_md.append(f"- **{f['title']}** ({f['category']}) — `{f['image']}`  (доля кадра: {f['area_fraction']})")
    (PROJECT_GALLERY / "imladris" / "NEEDS_REVIEW.md").write_text("\n".join(review_md), encoding="utf-8")

    # also dump full item list for the chat summary
    (HERE / "final_catalog_summary.json").write_text(
        json.dumps({"added": catalog_entries, "flagged": flagged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
