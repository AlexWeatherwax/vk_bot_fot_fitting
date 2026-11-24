"""Publish the accepted product cutouts without resetting later calibration.

Default: review the plan. Use --apply to publish it, or --apply --prune-duplicates
to remove replaced runtime copies whose exact bytes are retained in masters.
Source photos, generated art and calibration files are never modified.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile

from PIL import Image

PROJECT = Path(__file__).resolve().parents[2]
REPORT = "data/audit/curated-catalog-integration.json"
MEASUREMENTS = "data/audit/curated-reference-measurements.json"
HAIRPINS = "data/audit/hairpin-runtime-calibration.json"
WINTER_ID = "imladris_diadem_venets-diadema-zimnie-yagody-i-sergi"
SET_NAMES = {
    "alye-kapli-lesa": "Алые капли леса",
    "ledyanoe-ozero": "Ледяное озеро",
    "lesnoe-volshebstvo": "Лесное волшебство",
    "otgoloski-leta": "Отголоски лета",
    "pervye-luchi-solntsa": "Первые лучи солнца",
    "rannee-utro": "Раннее утро",
    "zimnie-yagody": "Зимние ягоды",
}
SET_COMPONENTS = {
    "alye-kapli-lesa": ["alye-kapli-lesa-earring", "alye-kapli-lesa-pendant"],
    "ledyanoe-ozero": ["ledyanoe-ozero-earrings-pair", "ledyanoe-ozero-bracelet"],
    "lesnoe-volshebstvo": ["lesnoe-volshebstvo-earring", "lesnoe-volshebstvo-pendant"],
    "otgoloski-leta": ["otgoloski-leta-earring", "otgoloski-leta-necklace"],
    "pervye-luchi-solntsa": ["pervye-luchi-solntsa-earring", "pervye-luchi-solntsa-pendant"],
    "rannee-utro": ["rannee-utro-earring", "rannee-utro-pendant"],
    "zimnie-yagody": ["zimnie-yagody-diadem-with-chains", "zimnie-yagody-earring"],
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_atomic(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".curated-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
    temporary.replace(path)
    return True


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def padded_anchor(meta: dict, size, padding=(16, 16)) -> list[float]:
    """Metadata anchors are normalized inside the clean art bbox, not a photo."""
    x0, y0, x1, y1 = meta["raw_bbox"]
    ax, ay = meta["anchor"]
    return [(padding[0] + ax * (x1 - x0)) / size[0],
            (padding[1] + ay * (y1 - y0)) / size[1]]


def offsets(target, base, unit: float, side=1) -> dict:
    return {"offset_x": (target[0] - base[0]) / unit / side,
            "offset_y": (target[1] - base[1]) / unit}


def merge_accepted(current: dict, desired: dict, previous: dict | None = None) -> dict:
    """Three-way merge: fields edited since the last import belong to the user.

    Initial publication installs accepted calibration. Subsequent publications
    change a known field only while its value still equals our prior baseline.
    Unknown fields, existing IDs/names and nested component metadata survive.
    """
    result = copy.deepcopy(current)
    for key, value in desired.items():
        if key in ("id", "name") and key in current:
            continue
        if key == "components":
            current_parts = {part["id"]: part for part in current.get(key, [])}
            previous_parts = {part["id"]: part for part in (previous or {}).get(key, [])}
            result[key] = [merge_accepted(current_parts.get(part["id"], {}), part,
                                          previous_parts.get(part["id"])) for part in value]
            desired_ids = {part["id"] for part in value}
            result[key].extend(copy.deepcopy(part) for part in current.get(key, [])
                               if part["id"] not in desired_ids)
        elif previous is None or key not in current or current[key] == previous.get(key):
            result[key] = copy.deepcopy(value)
    return result


def build_plan(project: Path = PROJECT) -> dict:
    calibration = project / "фото для калибровки"
    measurements = read_json(project / MEASUREMENTS)
    refs = measurements["references"]
    hp = read_json(project / HAIRPINS)["items"]
    entries, assets = [], []

    def publish(source: Path, category: str) -> str:
        relative = f"imladris/{category}/curated-{source.name}"
        target = "bot/jewelry/gallery/" + relative
        if not any(asset["target"] == target for asset in assets):
            data = source.read_bytes()
            with Image.open(io.BytesIO(data)) as image:
                if image.mode != "RGBA" or image.getextrema()[3][0] != 0:
                    raise ValueError(f"Нужен прозрачный RGBA PNG: {source}")
                size = list(image.size)
            assets.append({"source": source.relative_to(project).as_posix(),
                           "target": target, "source_sha256": digest(data),
                           "output_sha256": digest(data), "size": size, "transform": "byte_copy"})
        return relative

    def add(entry, source_dir, provenance):
        entries.append({"id": entry["id"], "source_dir": source_dir,
                        "accepted_entry": entry, "calibration_provenance": provenance})

    # All thirty pendants, including the already complete Forest Rain necklace.
    pendants = read_json(calibration / "кулоны/placement.json")
    neck = refs["pendants"]["anchors"]
    sw = neck["shoulder_width"]
    for record in pendants["items"]:
        source = calibration / "кулоны" / record["asset"]
        size = image_size(source)
        x0, y0, x1, y1 = record["raw_bbox"]
        necklace = record["category"] == "beads"
        target = [560, 750] if necklace else record["placement"]["bail_target"]
        base = neck["neck_point"]
        if not necklace:
            base = [base[i] + neck["down"][i] * sw * .30 for i in (0, 1)]
        entry = {"id": record["catalog_id"], "category": record["category"],
                 "image": publish(source, record["category"]),
                 "overlay_anchor": ([.5, 16 / size[1]] if necklace else padded_anchor(record, size)),
                 "anchor_scale": (410 * size[0] / (x1-x0) / (neck["neck_width"] * 1.15)
                                  if necklace else record["pendant_length_px"] * max(size) /
                                  max(x1-x0, y1-y0) / (sw * .24)),
                 "rotation_offset": -neck["tilt_angle"], **offsets(target, base, sw)}
        if not necklace:
            entry["chain_color"] = "curated_" + record["chain_material"].replace("-", "_")
        add(entry, Path(record["source_dir"]).relative_to(project.parent).as_posix(),
            {"metadata": "фото для калибровки/кулоны/placement.json", "reference": "pendants",
             "anchor_method": "clean-bbox normalized bail plus 16px padding",
             "scale_method": "accepted product length / runtime shoulder fraction, with padding correction"})

    # The seven v2 cuffs have their squeeze and angle baked into product art.
    cuffs = read_json(calibration / "каффы/placement.json")["items"]
    v3 = {record["slug"]: record for record in
          read_json(calibration / "каффы/placement-v3.json")["changes"]}
    face = refs["cuffs"]["anchors"]
    fw = face["face_width"]
    for record in cuffs:
        slug = record["slug"]
        updated = v3.get(slug)
        source = calibration / "каффы" / (updated["asset"] if updated else f"assets/{slug}-tryon-v2.png")
        size = image_size(source)
        if updated:
            placement = updated["placement"]
            target = updated["body"]["target"]
            anchor = [(target[0] - placement["left"]) / placement["width"],
                      (target[1] - placement["top"]) / placement["height"]]
            reference_length = max(size) / 5
            anchor_method = "body attachment in compact composite coordinate frame (placement origin cancels)"
        else:
            x0, y0, x1, y1 = record["raw_bbox"]
            width, height = round((x1-x0)*record["horizontal_factor"]), y1-y0
            dx = (record["anchor"][0]-x0)*width/(x1-x0)-width/2
            dy = record["anchor"][1]-y0-height/2
            angle = math.radians(record["angle"])
            anchor = [(size[0]/2+dx*math.cos(angle)-dy*math.sin(angle))/size[0],
                      (size[1]/2+dx*math.sin(angle)+dy*math.cos(angle))/size[1]]
            target = record["reference_target"]
            reference_length = max(size)*record["scale"]
            anchor_method = "raw art attachment transformed by crop, horizontal squeeze and baked rotation"
        # The accepted reference exposes the image-right ear. Select its
        # detector side rather than compensating a wrong ear by a face-wide
        # horizontal offset, which would fail on a different photograph.
        side = min(("left", "right"), key=lambda name:
                   math.hypot(target[0]-face[name+"_lobe"][0], target[1]-face[name+"_lobe"][1]))
        entry = {"id": f"imladris_kaffy_{slug}", "category": "kaffy",
                 "image": publish(source, "kaffy"), "overlay_anchor": anchor,
                 "anchor_scale": reference_length/(fw*.32), "kaffy_side": side,
                 "rotation_offset": -face["tilt_angle"],
                 **offsets(target, face[side+"_lobe"], fw, side=-1 if side == "left" else 1)}
        add(entry, f"Украшения /Каффы/{record['folder']}",
            {"metadata": "фото для калибровки/каффы/placement-v3.json" if updated else
             "фото для калибровки/каффы/placement.json", "reference": "cuffs",
             "anchor_method": anchor_method, "rotation_baked_into_art": True})

    neck = refs["brooches"]["anchors"]
    sw = neck["shoulder_width"]
    for record in read_json(calibration / "броши/placement.json")["items"]:
        source = calibration / "броши" / record["asset"]
        size = image_size(source)
        x0, y0, x1, y1 = record["raw_bbox"]
        entry = {"id": f"imladris_brooch_{record['slug']}", "category": "brooch",
                 "image": publish(source, "brooch"), "overlay_anchor": padded_anchor(record, size),
                 "anchor_scale": record["longest"]*max(size)/max(x1-x0,y1-y0)/(sw*.20),
                 "brooch_side": "right", "rotation_offset": -record["angle"]-neck["tilt_angle"],
                 **offsets(record["target"], neck["brooch_points"]["right"], sw)}
        add(entry, f"Украшения /Броши/{record['folder']}",
            {"metadata": "фото для калибровки/броши/placement.json", "reference": "brooches",
             "anchor_method": "clean-bbox normalized attachment plus 16px padding"})

    for record in read_json(calibration / "заколки/placement.json")["items"]:
        slug = record["slug"]
        tuning = copy.deepcopy(hp[slug])
        source = project / tuning.pop("asset", f"фото для калибровки/заколки/{record['asset']}")
        entry = {"id": f"imladris_hairpin_{slug}", "category": "hairpin",
                 "image": publish(source, "hairpin"), **tuning}
        add(entry, Path(record["source_dir"]).relative_to(project.parent).as_posix(),
            {"metadata": HAIRPINS, "anchor_method": "runtime hairpin calibration in product canvas coordinates"})

    front = calibration / "анфас-v3"
    diadems = {record["slug"]: record for record in read_json(front / "diadem-assets.json")}
    for slug, identifier in [("rannyaya-osen", "imladris_diadem_venets-diadema-rannyaya-osen"),
                             ("techenie", "imladris_diadem_venets-techenie")]:
        record = diadems[slug]
        size = record["asset_size"]
        entry = {"id": identifier, "category": "diadem", "image": publish(front/record["asset"], "diadem"),
                 "overlay_anchor": [record["central_tip_asset_px"][i]/size[i] for i in (0, 1)],
                 "anchor_scale": 1.3, "offset_x": 0, "offset_y": .2, "rotation_offset": 0}
        add(entry, f"Украшения /Диадемы/{record['name']}",
            {"metadata": "фото для калибровки/анфас-v3/diadem-assets.json",
             "anchor_method": "measured central diadem tip / padded canvas"})

    front_items = read_json(front / "pipeline-items.json")["items"]
    front_records = {record["slug"]: record for record in read_json(front / "front-assets.json")}
    for slug, keys in SET_COMPONENTS.items():
        parts = []
        for key in keys:
            part = copy.deepcopy(front_items[key])
            if slug == "zimnie-yagody":
                part["id"] = ("imladris_set_zimnie-yagody_diadem" if part["category"] == "diadem"
                              else "imladris_set_zimnie-yagody_earrings")
            else:
                part["id"] = "imladris_set_component_" + key
            source = front / part["image"]
            part["image"] = publish(source, "sets")
            if key == "zimnie-yagody-diadem-with-chains":
                part.update(overlay_anchor=[.5, 301/900], offset_y=.2)
            elif key == "ledyanoe-ozero-earrings-pair":
                # Intrinsic hooks after the runtime's tight split: green is
                # 374x1400, pastel 370x1400. The pair canvas is 804x1432.
                part["overlay_anchor"] = [.5, .015]
                part["pair_overlay_anchors"] = [[.36, .015], [.72, .015]]
            else:
                record = front_records[key]
                size = record["size"]
                if record["type"] == "earring":
                    part["overlay_anchor"] = [record["art_anchor_in_canvas"][i]/size[i] for i in (0, 1)]
                    part["offset_y"] = 0
                elif record["type"] == "necklace":
                    part["overlay_anchor"] = [.5, record["padding"]["top"]/size[1]]
                else:
                    meta = read_json(front / "metadata" / f"{key}.json")
                    part["overlay_anchor"] = padded_anchor(
                        {**meta, "raw_bbox": record["raw_bbox"]}, size,
                        (record["padding"]["left"], record["padding"]["top"]))
            if "chain_color" in part:
                part["chain_color"] = "curated_copper" if slug == "alye-kapli-lesa" else "curated_silver"
            parts.append(part)
        identifier = WINTER_ID if slug == "zimnie-yagody" else f"imladris_set_{slug}"
        entry = {"id": identifier, "name": "Набор " + SET_NAMES[slug], "category": "set",
                 "image": parts[0]["image"], "tryon_mode": "sequential" if slug == "ledyanoe-ozero" else "combined",
                 "components": parts}
        add(entry, "Украшения /Наборы/" + ("Зимние ягоды диадема+серьги" if slug == "zimnie-yagody" else SET_NAMES[slug]),
            {"metadata": "фото для калибровки/анфас-v3/pipeline-items.json",
             "anchor_method": "component art anchors corrected for clean crop and transparent padding"})

    # All original metal hues, using the photographed open-front chain shape.
    for metal in ("silver", "gold", "brass", "copper", "dark-silver"):
        source = calibration / "кулоны/chains" / f"{metal}.png"
        with Image.open(source) as image:
            image = image.convert("RGBA")
            box = image.getchannel("A").point(lambda a: 255 if a >= 160 else 0).getbbox()
            if box is None:
                raise ValueError(f"Пустая цепочка: {source}")
            clean = image.crop(box)
            size = [clean.width, round(clean.width*.51/.32)]
        assets.append({"source": source.relative_to(project).as_posix(),
                       "target": f"bot/tryon/assets/chain_curated_{metal.replace('-', '_')}.png",
                       "source_sha256": digest(source.read_bytes()), "size": size,
                       "transform": "alpha160_crop_resize", "crop": list(box)})
    metadata_files = {row["calibration_provenance"]["metadata"] for row in entries}
    metadata_files.update({MEASUREMENTS, HAIRPINS,
                           "фото для калибровки/анфас-v3/front-assets.json",
                           "фото для калибровки/анфас-v3/diadem-assets.json"})
    metadata_files.update(path.relative_to(project).as_posix() for path in (front/"metadata").glob("*.json"))
    return {"schema_version": 1, "entries": entries, "assets": assets,
            "calibration_inputs": {name: digest((project/name).read_bytes()) for name in sorted(metadata_files)},
            "measurements_sha256": digest((project/MEASUREMENTS).read_bytes()),
            "hairpin_calibration_sha256": digest((project/HAIRPINS).read_bytes())}


def apply_plan(plan: dict, project: Path = PROJECT, *, prune_duplicates=False) -> dict:
    manifest_path = project / "bot/jewelry/gallery/manifest.json"
    original_bytes = manifest_path.read_bytes()
    manifest = read_json(manifest_path)
    existing = {entry["id"]: entry for entry in manifest}
    old_report = read_json(project/REPORT) if (project/REPORT).exists() else {}
    prior = {entry["id"]: entry["accepted_entry"] for entry in old_report.get("entries", [])}
    before = old_report.get("original_entries", {row["id"]: copy.deepcopy(existing[row["id"]])
                                                for row in plan["entries"] if row["id"] in existing})
    added = old_report.get("added_ids", [row["id"] for row in plan["entries"] if row["id"] not in existing])
    for row in plan["entries"]:
        desired = row["accepted_entry"]
        identifier = row["id"]
        merged = merge_accepted(existing.get(identifier, {}), desired, prior.get(identifier))
        if identifier in existing:
            manifest[manifest.index(existing[identifier])] = merged
        else:
            manifest.append(merged)
        existing[identifier] = merged
    if len(existing) != len(manifest):
        raise ValueError("Повторяющиеся ID в каталоге")

    outputs = []
    for asset in plan["assets"]:
        source = project / asset["source"]
        data = source.read_bytes()
        if digest(data) != asset["source_sha256"]:
            raise ValueError(f"Источник изменился после планирования: {source}")
        if asset["transform"] == "alpha160_crop_resize":
            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGBA")
                image.putalpha(image.getchannel("A").point(lambda a: a if a >= 160 else 0))
                image = image.crop(tuple(asset["crop"])).resize(tuple(asset["size"]), Image.Resampling.LANCZOS)
                stream = io.BytesIO()
                image.save(stream, "PNG")
                data = stream.getvalue()
        outputs.append((project/asset["target"], data))
        asset["output_sha256"] = digest(data)
    # Assets are staged first, manifest is switched with a single atomic rename.
    for target, data in outputs:
        write_atomic(target, data)
    write_atomic(manifest_path, json_bytes(manifest))
    removed = old_report.get("removed_duplicate_gallery_pngs", [])
    archived = old_report.get("archived_unique_gallery_pngs", [])
    if prune_duplicates:
        protected = {asset["target"].removeprefix("bot/jewelry/gallery/") for asset in plan["assets"]
                     if asset["target"].startswith("bot/jewelry/gallery/")}
        removed += prune_gallery_duplicates(project, manifest, protected_images=protected)
        archived += archive_unique_gallery_pngs(project, manifest, protected_images=protected)
    gallery = project/"bot/jewelry/gallery"
    references = referenced_images(manifest)
    all_pngs = {path.relative_to(gallery).as_posix() for path in gallery.rglob("*.png")}
    source_mapping = []
    baseline_path = project/"data/audit/catalog-coverage.json"
    if baseline_path.exists():
        slugs_by_name = {name: slug for slug, name in SET_NAMES.items()}
        for row in read_json(baseline_path)["source_model_mapping"]:
            identifier = row.get("manifest_id") or "imladris_set_" + slugs_by_name[row["name"]]
            source_mapping.append({"source_dir": row["source_dir"], "section": row["section"],
                                   "name": row["name"], "manifest_id": identifier,
                                   "selectable": identifier in existing})
    report = {
        **plan, "mode": "applied", "baseline_audit": "data/audit/catalog-coverage.json",
        "original_manifest_sha256": old_report.get("original_manifest_sha256", digest(original_bytes)),
        "manifest_sha256": digest(manifest_path.read_bytes()), "original_entries": before,
        "added_ids": added, "removed_duplicate_gallery_pngs": removed,
        "archived_unique_gallery_pngs": archived, "source_model_mapping": source_mapping,
        "summary": {"selectable_entries": len(manifest), "integrated_entries": len(plan["entries"]),
                    "upgraded_existing_entries": len(before), "added_sets": len(added),
                    "active_sets": sum(entry["category"] == "set" for entry in manifest),
                    "sequential_sets": sum(entry.get("tryon_mode") == "sequential" for entry in manifest),
                    "curated_product_pngs": sum(asset["target"].startswith("bot/jewelry/gallery/") for asset in plan["assets"]),
                    "curated_chain_pngs": sum(asset["target"].startswith("bot/tryon/assets/") for asset in plan["assets"]),
                    "source_folders": len(source_mapping), "mapped_source_folders": sum(row["selectable"] for row in source_mapping),
                    "linked_unique_gallery_pngs": len(references), "missing_linked_pngs": len(references-all_pngs),
                    "unreferenced_gallery_pngs": len(all_pngs-references),
                    "removed_duplicate_gallery_pngs": len(removed), "archived_unique_gallery_pngs": len(archived)},
        "active_entries": {row["id"]: existing[row["id"]] for row in plan["entries"]},
        "policy": "Accepted baseline merged by ID; later edits and unknown fields preserved. No source photograph or calibration artifact is rewritten.",
    }
    write_atomic(project/REPORT, json_bytes(report))
    return report


def referenced_images(manifest: list[dict]) -> set[str]:
    result = set()
    for entry in manifest:
        result.add(entry["image"])
        result.update(referenced_images(entry.get("components", [])))
    return result


def prune_gallery_duplicates(project: Path, manifest: list[dict], *, protected_images=()) -> list[dict]:
    """Only unlink obsolete runtime PNGs whose identical masters are retained."""
    gallery = project/"bot/jewelry/gallery"
    active = referenced_images(manifest) | set(protected_images)
    candidates = [path for path in gallery.rglob("*.png") if path.relative_to(gallery).as_posix() not in active]
    if not candidates:
        return []
    wanted = {digest(path.read_bytes()) for path in candidates}
    masters = {}
    for folder in (project/"scripts/catalog_import/work/cutout", project/"scripts/catalog_import/work/gallery_backup"):
        for path in sorted(folder.rglob("*.png")):
            sha = digest(path.read_bytes())
            if sha in wanted:
                masters.setdefault(sha, path)
    removed = []
    for path in sorted(candidates):
        sha = digest(path.read_bytes())
        if sha in masters:
            removed.append({"removed": path.relative_to(project).as_posix(), "sha256": sha,
                            "retained_identical_master": masters[sha].relative_to(project).as_posix()})
            path.unlink()
    return removed


def archive_unique_gallery_pngs(project: Path, manifest: list[dict], *, protected_images=()) -> list[dict]:
    """Retain unique retired art outside the deployable runtime gallery."""
    gallery = project/"bot/jewelry/gallery"
    active = referenced_images(manifest) | set(protected_images)
    archived = []
    for path in sorted(gallery.rglob("*.png")):
        relative = path.relative_to(gallery)
        if relative.as_posix() in active:
            continue
        data = path.read_bytes()
        sha = digest(data)
        target = project/"scripts/catalog_import/work/curated_replaced_unique"/relative
        if target.exists() and digest(target.read_bytes()) != sha:
            target = target.with_name(target.stem + "-" + sha[:12] + target.suffix)
        write_atomic(target, data)
        if digest(target.read_bytes()) != sha:
            raise ValueError(f"Не удалось сохранить уникальное старое изображение: {path}")
        archived.append({"source": path.relative_to(project).as_posix(),
                         "target": target.relative_to(project).as_posix(), "sha256": sha})
        path.unlink()
    return archived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Publish the accepted product assets and manifest")
    parser.add_argument("--prune-duplicates", action="store_true", help="Remove obsolete gallery copies only when an identical master is retained")
    args = parser.parse_args()
    plan = build_plan()
    if args.apply:
        report = apply_plan(plan, prune_duplicates=args.prune_duplicates)
        print(json.dumps(report["summary"], ensure_ascii=False))
        print(PROJECT/REPORT)
    else:
        print(json.dumps({"entries": len(plan["entries"]), "assets": len(plan["assets"]),
                          "ids": [row["id"] for row in plan["entries"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
