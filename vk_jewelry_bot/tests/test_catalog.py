"""
Тесты каталога и нечёткого поиска — не требуют ни VK-токена, ни mediapipe,
можно гонять локально сразу после `pip install -r requirements.txt`
(или даже только с Pillow, т.к. этот модуль их не использует).

Запуск: pytest tests/test_catalog.py
"""
from dataclasses import asdict
import json
import os

import pytest

from bot.jewelry.catalog import Catalog, MANIFEST_PATH
from bot.jewelry.models import Category, item_from_dict


def test_manifest_loads():
    catalog = Catalog(MANIFEST_PATH)
    assert len(catalog.items) >= 5
    categories = {item.category for item in catalog.items}
    assert categories == set(Category)


def test_exact_match():
    catalog = Catalog(MANIFEST_PATH)
    item, suggestions = catalog.find("Серьги Ягодные")
    assert item is not None
    assert item.id == "imladris_earrings_sergi-yagodnye"
    assert suggestions == []


def test_case_insensitive_and_partial():
    catalog = Catalog(MANIFEST_PATH)
    item, _ = catalog.find("ягодные")
    assert item is not None
    assert item.id == "imladris_earrings_sergi-yagodnye"


def test_typo_tolerant_search():
    catalog = Catalog(MANIFEST_PATH)
    # "Кольцо Обенное" вместо "Кольцо Особенное" — опечатка, должна остаться в кандидатах
    item, suggestions = catalog.find("Кольцо Обенное")
    assert item is not None or any(s.id == "imladris_ring_koltso-osobennoe" for s in suggestions)


def test_unknown_item_returns_no_match():
    catalog = Catalog(MANIFEST_PATH)
    item, suggestions = catalog.find("зжшдлфыва")
    assert item is None


def test_exact_title_wins_over_longer_substring_match(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps([
        {"id": "a", "name": "Серьги Лес", "category": "earrings", "image": "a.png"},
        {"id": "b", "name": "Серьги Лес и ягоды", "category": "earrings", "image": "b.png"},
    ]))
    item, suggestions = Catalog(path).find("  сЕРЬГИ лЕС  ")
    assert item.id == "a"
    assert suggestions == []


def test_winter_berries_is_a_set_with_separate_physical_components():
    catalog = Catalog(MANIFEST_PATH)
    item, suggestions = catalog.find("Зимние ягоды")
    assert suggestions == []
    assert item.id == "imladris_diadem_venets-diadema-zimnie-yagody-i-sergi"
    assert item.category == Category.SET
    assert {part.category for part in item.components} == {Category.DIADEM, Category.EARRINGS}
    assert len({part.image for part in item.components}) == 2
    assert catalog.image_path(item).is_file()
    assert all(catalog.image_path(part).is_file() for part in item.components)
    diadem = next(part for part in item.components if part.category == Category.DIADEM)
    assert diadem.offset_y == 0.2
    assert not any(
        "Зимние ягоды" in candidate.name and candidate.category == Category.DIADEM
        for candidate in catalog.items
    )


def test_nested_component_calibration_survives_load_and_worker_roundtrip():
    raw = {
        "id": "set", "name": "Набор", "category": "set", "image": "set.png",
        "components": [
            {
                "id": "earrings", "name": "Серьги", "category": "earrings", "image": "ears.png",
                "anchor_scale": 1.4, "offset_x": 0.1, "offset_y": -0.2,
                "rotation_offset": 7, "pair_image": True,
            },
            {
                "id": "brooch", "name": "Брошь", "category": "brooch", "image": "brooch.png",
                "brooch_side": "right",
            },
        ],
    }
    item = item_from_dict(raw)
    assert item.components[0].anchor_scale == 1.4
    assert item.components[0].offset_x == 0.1
    assert item.components[0].offset_y == -0.2
    assert item.components[0].rotation_offset == 7
    assert item.components[0].pair_image is True
    assert item.components[1].brooch_side == "right"
    assert item_from_dict(json.loads(json.dumps(asdict(item)))) == item


@pytest.mark.parametrize("components", [[], [
    {"id": "a", "name": "Серьги", "category": "earrings", "image": "a.png"}
]])
def test_set_requires_at_least_two_components(components):
    with pytest.raises(ValueError, match="хотя бы два"):
        item_from_dict({
            "id": "set", "name": "Набор", "category": "set", "image": "set.png",
            "components": components,
        })


def test_set_rejects_nested_sets():
    with pytest.raises(ValueError, match="другой набор"):
        item_from_dict({
            "id": "set", "name": "Набор", "category": "set", "image": "set.png",
            "components": [
                {"id": "nested", "name": "Набор", "category": "set", "image": "nested.png"},
                {"id": "ears", "name": "Серьги", "category": "earrings", "image": "ears.png"},
            ],
        })


def test_single_jewelry_rejects_components():
    with pytest.raises(ValueError, match="только у набора"):
        item_from_dict({
            "id": "ears", "name": "Серьги", "category": "earrings", "image": "ears.png",
            "components": [{"id": "a", "name": "Кулон", "category": "pendant", "image": "a.png"}],
        })


def test_find_refreshes_editor_calibration_without_restart(tmp_path):
    path = tmp_path / "manifest.json"
    raw = [{"id": "a", "name": "Серьги Лес", "category": "earrings", "image": "a.png", "anchor_scale": 1.1}]
    path.write_text(json.dumps(raw), encoding="utf-8")
    catalog = Catalog(path)
    previous = path.stat()
    raw[0]["anchor_scale"] = 1.7
    path.write_text(json.dumps(raw), encoding="utf-8")
    # Same size and same second: nanosecond resolution must still refresh.
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1))
    item, _ = catalog.find("Серьги Лес")
    assert item.anchor_scale == 1.7
    assert catalog.reload_if_changed() is False


def test_bad_editor_manifest_keeps_last_good_catalog_and_recovers(tmp_path, caplog):
    path = tmp_path / "manifest.json"
    raw = [{"id": "a", "name": "Серьги Лес", "category": "earrings", "image": "a.png"}]
    path.write_text(json.dumps(raw), encoding="utf-8")
    catalog = Catalog(path)
    old_items = catalog.items
    path.write_text('[{"id":', encoding="utf-8")
    assert catalog.reload_if_changed() is False
    assert catalog.items is old_items
    assert catalog.find("Серьги Лес")[0].id == "a"
    assert len(caplog.records) == 1
    raw[0]["name"] = "Серьги Новые"
    replacement = tmp_path / "new.json"
    replacement.write_text(json.dumps(raw), encoding="utf-8")
    replacement.replace(path)
    assert catalog.find("Серьги Новые")[0].id == "a"
    assert catalog.items is not old_items


def test_invalid_component_does_not_publish_part_of_catalog(tmp_path):
    path = tmp_path / "manifest.json"
    raw = [{"id": "a", "name": "Серьги Лес", "category": "earrings", "image": "a.png"}]
    path.write_text(json.dumps(raw), encoding="utf-8")
    catalog = Catalog(path)
    raw += [{"id": "bad", "name": "Пустой набор", "category": "set", "image": "bad.png", "components": []}]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert catalog.reload_if_changed() is False
    assert [item.id for item in catalog.items] == ["a"]
