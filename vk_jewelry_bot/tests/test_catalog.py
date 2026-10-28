"""Регрессии каталога на временных manifest-файлах.

Не требуют VK-токена, MediaPipe и изображений украшений.
Запуск: python -m unittest tests.test_catalog
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from bot.jewelry.catalog import Catalog
from bot.jewelry.models import Category


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.manifest = Path(self.temporary_directory.name) / "manifest.json"
        self.entries = [
            {
                "id": "ring-moon",
                "name": "Кольцо Луна",
                "category": "ring",
                "image": "rings/moon.png",
            },
            {
                "id": "earrings-berries",
                "name": "Серьги Ягодные",
                "category": "earrings",
                "image": "earrings/berries.png",
            },
            {
                "id": "brooch-leaf",
                "name": "Брошь Лист",
                "category": "brooch",
                "image": "brooches/leaf.png",
                "brooch_side": "right",
            },
        ]
        self.write_manifest()
        self.catalog = Catalog(self.manifest)

    def write_manifest(self, path=None):
        (path or self.manifest).write_text(
            json.dumps(self.entries, ensure_ascii=False), encoding="utf-8"
        )

    def test_loads_catalog_and_optional_calibration(self):
        self.assertEqual(len(self.catalog.items), 3)
        self.assertEqual(self.catalog.items[0].category, Category.RING)
        self.assertEqual(self.catalog.items[0].anchor_scale, 1.0)
        self.assertEqual(self.catalog.items[0].brooch_side, "left")
        self.assertEqual(self.catalog.items[2].brooch_side, "right")

    def test_exact_match(self):
        item, suggestions = self.catalog.find("Серьги Ягодные")
        self.assertEqual(item.id, "earrings-berries")
        self.assertEqual(suggestions, [])

    def test_case_insensitive_and_partial(self):
        item, suggestions = self.catalog.find("  ЯГОДНЫЕ  ")
        self.assertEqual(item.id, "earrings-berries")
        self.assertEqual(suggestions, [])

    def test_typo_tolerant_search(self):
        item, suggestions = self.catalog.find("Серьги Ягдные")
        ids = [entry.id for entry in suggestions]
        if item is not None:
            ids.append(item.id)
        self.assertIn("earrings-berries", ids)

    def test_unknown_item_returns_no_match(self):
        item, suggestions = self.catalog.find("зжшдлфыва")
        self.assertIsNone(item)
        self.assertEqual(suggestions, [])

    def test_image_path_is_relative_to_the_loaded_manifest(self):
        self.assertEqual(
            self.catalog.image_path(self.catalog.items[0]),
            self.manifest.parent / "rings" / "moon.png",
        )

    def test_unchanged_manifest_is_not_reloaded(self):
        current_items = self.catalog.items
        self.assertFalse(self.catalog.reload_if_changed())
        self.assertIs(self.catalog.items, current_items)

    def test_find_sees_editor_changes_without_restart(self):
        self.entries[0]["name"] = "Кольцо Полная Луна"
        self.entries[0]["anchor_scale"] = 1.3
        self.write_manifest()

        item, suggestions = self.catalog.find("Полная Луна")
        self.assertEqual(item.id, "ring-moon")
        self.assertEqual(item.anchor_scale, 1.3)
        self.assertEqual(suggestions, [])

    def test_mtime_change_reloads_same_size_manifest(self):
        original_stat = self.manifest.stat()
        self.entries[0]["name"] = "Кольцо Небо"
        self.write_manifest()
        os.utime(
            self.manifest,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000),
        )
        self.assertEqual(self.manifest.stat().st_size, original_stat.st_size)

        self.assertTrue(self.catalog.reload_if_changed())
        self.assertEqual(self.catalog.items[0].name, "Кольцо Небо")

    def test_size_change_reloads_when_mtime_is_preserved(self):
        original_stat = self.manifest.stat()
        self.entries[0]["name"] = "Кольцо Полная Луна"
        self.write_manifest()
        os.utime(
            self.manifest,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )

        self.assertTrue(self.catalog.reload_if_changed())
        self.assertEqual(self.catalog.items[0].name, "Кольцо Полная Луна")

    def test_atomic_replacement_reloads_even_with_same_mtime_and_size(self):
        original_stat = self.manifest.stat()
        self.entries[0]["name"] = "Кольцо Небо"
        replacement = self.manifest.with_suffix(".new")
        self.write_manifest(replacement)
        os.utime(
            replacement,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        self.assertEqual(replacement.stat().st_size, original_stat.st_size)
        os.replace(replacement, self.manifest)

        self.assertTrue(self.catalog.reload_if_changed())
        self.assertEqual(self.catalog.items[0].name, "Кольцо Небо")

    def test_failed_reload_keeps_last_valid_catalog_and_can_be_retried(self):
        current_items = self.catalog.items
        self.manifest.write_text("[invalid", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self.catalog.reload_if_changed()
        self.assertIs(self.catalog.items, current_items)

        self.entries[0]["name"] = "Кольцо Полная Луна"
        self.write_manifest()
        self.assertTrue(self.catalog.reload_if_changed())
        self.assertEqual(self.catalog.items[0].name, "Кольцо Полная Луна")


if __name__ == "__main__":
    unittest.main()
