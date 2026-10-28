"""
Каталог украшений: загрузка из manifest.json + нечёткий поиск по названию,
чтобы пользователь мог написать украшение с опечаткой или не целиком.
"""
import json
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

from .models import Category, JewelryItem

GALLERY_DIR = Path(__file__).parent / "gallery"
MANIFEST_PATH = GALLERY_DIR / "manifest.json"


class Catalog:
    def __init__(self, manifest_path: Path = MANIFEST_PATH):
        self.manifest_path = manifest_path
        self.items: list[JewelryItem] = []
        self.reload()

    def reload(self) -> None:
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.items = [
            JewelryItem(
                id=entry["id"],
                name=entry["name"],
                category=Category(entry["category"]),
                image=entry["image"],
                anchor_scale=entry.get("anchor_scale", 1.0),
                offset_x=entry.get("offset_x", 0.0),
                offset_y=entry.get("offset_y", 0.0),
                rotation_offset=entry.get("rotation_offset", 0.0),
                pair_image=entry.get("pair_image", False),
                single_ear=entry.get("single_ear", False),
                chain_color=entry.get("chain_color", "silver"),
                kaffy_side=entry.get("kaffy_side", "left"),
                kaffy_anchor_y=entry.get("kaffy_anchor_y", 0.8),
                hairpin_style=entry.get("hairpin_style", "updo"),
                hairpin_side=entry.get("hairpin_side", "left"),
            )
            for entry in raw
        ]

    def image_path(self, item: JewelryItem) -> Path:
        return GALLERY_DIR / item.image

    def _substring_matches(self, query: str) -> list[JewelryItem]:
        q = query.strip().lower()
        if not q:
            return []
        return [it for it in self.items if q in it.name.lower()]

    def find(
        self, query: str, n: int = 3, cutoff: float = 0.5
    ) -> tuple[Optional[JewelryItem], list[JewelryItem]]:
        """
        Ищет украшение по названию.

        Возвращает (item, []) при однозначном совпадении, либо
        (None, [варианты]) если совпадений несколько или нет точного —
        тогда варианты можно предложить пользователю.
        """
        substr = self._substring_matches(query)
        if len(substr) == 1:
            return substr[0], []
        if len(substr) > 1:
            return None, substr[:n]

        names = [it.name for it in self.items]
        close = get_close_matches(query.strip(), names, n=n, cutoff=cutoff)
        candidates = [it for name in close for it in self.items if it.name == name]
        if len(candidates) == 1:
            return candidates[0], []
        return None, candidates


catalog = Catalog()
