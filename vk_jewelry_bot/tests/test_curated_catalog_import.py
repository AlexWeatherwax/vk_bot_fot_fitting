"""Publishing accepted art must not undo later user calibration or lose metadata."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "scripts/catalog_import/8_integrate_curated.py"
spec = importlib.util.spec_from_file_location("curated_import", SCRIPT)
curated = importlib.util.module_from_spec(spec)
spec.loader.exec_module(curated)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture_plan(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (40, 60), (180, 100, 20, 0)).save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    old = {"id": "old", "name": "Старое имя", "category": "pendant", "image": "old.png",
           "anchor_scale": .4, "offset_y": .2, "private_metadata": {"keep": True}}
    write_json(tmp_path / "bot/jewelry/gallery/manifest.json", [old])
    plan = {
        "schema_version": 1,
        "entries": [
            {"id": "old", "accepted_entry": {"id": "old", "name": "Новое имя",
             "category": "pendant", "image": "curated.png", "anchor_scale": 1.2,
             "offset_y": 0, "overlay_anchor": [.5, .03]}},
            {"id": "new", "accepted_entry": {"id": "new", "name": "Набор", "category": "set",
             "image": "curated.png", "tryon_mode": "sequential", "components": [
                 {"id": "a", "category": "earrings", "name": "Серьги", "image": "curated.png", "anchor_scale": 1},
                 {"id": "b", "category": "bracelet", "name": "Браслет", "image": "curated.png", "anchor_scale": .8}]}}
        ],
        "assets": [{"source": "source.png", "target": "bot/jewelry/gallery/curated.png",
                    "source_sha256": sha, "transform": "byte_copy", "size": [40, 60]}],
    }
    return plan


def test_publish_preserves_identity_and_is_byte_idempotent(tmp_path):
    plan = fixture_plan(tmp_path)
    report = curated.apply_plan(plan, tmp_path)
    manifest = tmp_path / "bot/jewelry/gallery/manifest.json"
    entries = curated.read_json(manifest)
    assert len(entries) == 2
    assert entries[0]["name"] == "Старое имя"
    assert entries[0]["private_metadata"] == {"keep": True}
    assert entries[0]["anchor_scale"] == 1.2
    assert entries[0]["overlay_anchor"] == [.5, .03]
    paths = [manifest, tmp_path/curated.REPORT, tmp_path/plan["assets"][0]["target"]]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    curated.apply_plan(plan, tmp_path)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == value for p, value in before.items())
    assert report["original_entries"]["old"]["anchor_scale"] == .4


def test_reimport_keeps_later_calibration_and_nested_unknown_fields(tmp_path):
    plan = fixture_plan(tmp_path)
    curated.apply_plan(plan, tmp_path)
    path = tmp_path / "bot/jewelry/gallery/manifest.json"
    manifest = curated.read_json(path)
    manifest[0].update(anchor_scale=1.7, offset_y=.09, custom="manual")
    manifest[1]["components"][0].update(anchor_scale=1.8, custom={"notes": "keep"})
    write_json(path, manifest)
    updated = copy.deepcopy(plan)
    updated["entries"][0]["accepted_entry"].update(anchor_scale=1.3, offset_y=-.1, rotation_offset=7)
    updated["entries"][1]["accepted_entry"]["components"][0]["anchor_scale"] = 1.1
    curated.apply_plan(updated, tmp_path)
    result = curated.read_json(path)
    assert result[0]["anchor_scale"] == 1.7
    assert result[0]["offset_y"] == .09
    assert result[0]["rotation_offset"] == 7
    assert result[0]["custom"] == "manual"
    assert result[1]["components"][0]["anchor_scale"] == 1.8
    assert result[1]["components"][0]["custom"] == {"notes": "keep"}


def test_changed_source_rejected_before_any_publish(tmp_path):
    plan = fixture_plan(tmp_path)
    manifest = tmp_path / "bot/jewelry/gallery/manifest.json"
    before = manifest.read_bytes()
    (tmp_path / "source.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Источник изменился"):
        curated.apply_plan(plan, tmp_path)
    assert manifest.read_bytes() == before
    assert not (tmp_path / "bot/jewelry/gallery/curated.png").exists()


def test_pruning_only_removes_identical_retained_masters(tmp_path):
    gallery = tmp_path / "bot/jewelry/gallery"
    master = tmp_path / "scripts/catalog_import/work/cutout/a.png"
    master.parent.mkdir(parents=True)
    gallery.mkdir(parents=True)
    master.write_bytes(b"retained exact bytes")
    (gallery / "duplicate.png").write_bytes(master.read_bytes())
    (gallery / "unique.png").write_bytes(b"unique old art")
    (gallery / "active.png").write_bytes(master.read_bytes())
    removed = curated.prune_gallery_duplicates(tmp_path, [{"image": "active.png"}])
    assert len(removed) == 1
    assert removed[0]["removed"].endswith("duplicate.png")
    assert master.exists() and (gallery / "unique.png").exists() and (gallery / "active.png").exists()


def test_unique_retired_art_is_archived_without_overwriting_a_master(tmp_path):
    gallery = tmp_path / "bot/jewelry/gallery"
    gallery.mkdir(parents=True)
    (gallery / "unique.png").write_bytes(b"unique old art")
    old_archive = tmp_path / "scripts/catalog_import/work/curated_replaced_unique/unique.png"
    old_archive.parent.mkdir(parents=True)
    old_archive.write_bytes(b"earlier unique version")
    archived = curated.archive_unique_gallery_pngs(tmp_path, [])
    assert len(archived) == 1
    assert (tmp_path / archived[0]["target"]).read_bytes() == b"unique old art"
    assert old_archive.read_bytes() == b"earlier unique version"
    assert not (gallery / "unique.png").exists()


def test_legacy_assemble_requires_explicit_dangerous_flag():
    manifest = PROJECT / "bot/jewelry/gallery/manifest.json"
    before = manifest.read_bytes()
    result = subprocess.run([sys.executable, str(PROJECT/"scripts/catalog_import/5_assemble.py")],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "8_integrate_curated.py --apply" in result.stderr
    assert manifest.read_bytes() == before


def test_published_catalog_contains_all_products_and_complete_runtime_assets():
    """A clean release is self-contained without import reports or source photos."""
    manifest = curated.read_json(PROJECT / "bot/jewelry/gallery/manifest.json")
    by_id = {item["id"]: item for item in manifest}
    assert len(manifest) == len(by_id) == 88
    gallery = PROJECT / "bot/jewelry/gallery"
    linked_images = curated.referenced_images(manifest)
    assert len(linked_images) == 95
    published_images = {
        path.relative_to(gallery).as_posix() for path in gallery.rglob("*.png")
        if not any(part.startswith(".") for part in path.relative_to(gallery).parts)
    }
    assert published_images == linked_images
    assert len([item for item in manifest if item["category"] == "set"]) == 7
    assert by_id["imladris_set_ledyanoe-ozero"]["tryon_mode"] == "sequential"
    assert [part["category"] for part in by_id["imladris_set_ledyanoe-ozero"]["components"]] == ["earrings", "bracelet"]
    assert by_id["imladris_set_ledyanoe-ozero"]["components"][0]["pair_overlay_anchors"] == [[.36, .015], [.72, .015]]
    assert {part["category"] for part in by_id["imladris_set_otgoloski-leta"]["components"]} == {"earrings", "beads"}
    for image in linked_images:
        relative = Path(image)
        assert not relative.is_absolute() and ".." not in relative.parts
        with Image.open(gallery / relative) as png:
            assert png.mode == "RGBA"
            assert png.getchannel("A").getextrema()[0] == 0
    winter = next(part for part in by_id[curated.WINTER_ID]["components"] if part["category"] == "diadem")
    assert winter["overlay_anchor"] == [.5, 301/900]
    assert winter["offset_y"] == .2 and winter["anchor_scale"] == 1.3
    colors = {item["chain_color"] for item in manifest if item["category"] == "pendant"}
    assert colors == {"curated_silver", "curated_gold", "curated_brass", "curated_copper", "curated_dark_silver"}
    for color in colors:
        with Image.open(PROJECT / "bot/tryon/assets" / f"chain_{color}.png") as chain:
            assert chain.mode == "RGBA"
            assert chain.getchannel("A").getextrema()[0] == 0
    cuffs = [item for item in manifest if item["category"] == "kaffy"]
    assert len(cuffs) == 9 and all(item["kaffy_side"] == "right" for item in cuffs)
    assert all(abs(item["offset_x"]) < .1 for item in cuffs)
