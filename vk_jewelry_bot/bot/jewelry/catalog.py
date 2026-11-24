"""
Каталог украшений: загрузка из manifest.json + нечёткий поиск по названию,
чтобы пользователь мог написать украшение с опечаткой или не целиком.
"""
import json
import logging
import os
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

from .models import JewelryItem, item_from_dict

GALLERY_DIR = Path(__file__).parent / "gallery"
MANIFEST_PATH = GALLERY_DIR / "manifest.json"
logger = logging.getLogger(__name__)


class Catalog:
    def __init__(self, manifest_path: Path = MANIFEST_PATH):
        self.manifest_path = Path(manifest_path)
        self.items: list[JewelryItem] = []
        self._signature: tuple[int, int] | None = None
        self._failed_signature: tuple[int, int] | None = None
        self.reload()

    def reload(self) -> None:
        # Build the replacement completely before publishing it. A partial
        # editor write must never empty the running bot's last good catalogue.
        with self.manifest_path.open(encoding="utf-8") as stream:
            before = os.fstat(stream.fileno())
            raw = json.load(stream)
            after = os.fstat(stream.fileno())
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError("Каталог изменился во время чтения")
        if not isinstance(raw, list):
            raise ValueError("Каталог должен содержать список украшений")
        if not all(isinstance(entry, dict) for entry in raw):
            raise ValueError("Каждое украшение в каталоге должно быть объектом")
        items = [item_from_dict(entry) for entry in raw]
        if len({item.id for item in items}) != len(items):
            raise ValueError("В каталоге повторяются ID украшений")
        self.items = items
        self._signature = (after.st_mtime_ns, after.st_size)
        self._failed_signature = None

    def reload_if_changed(self) -> bool:
        """Refresh editor changes; retain the last working catalogue on error."""
        try:
            stat = self.manifest_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = (0, 0)
        if signature in (self._signature, self._failed_signature):
            return False
        try:
            self.reload()
        except (OSError, ValueError, TypeError, KeyError):
            self._failed_signature = signature
            logger.exception("Не удалось обновить каталог; используется последняя рабочая версия")
            return False
        return True

    def image_path(self, item: JewelryItem) -> Path:
        return GALLERY_DIR / item.image

    def _substring_matches(self, query: str) -> list[JewelryItem]:
        q = query.strip().casefold()
        if not q:
            return []
        return [it for it in self.items if q in it.name.casefold()]

    def find(
        self, query: str, n: int = 3, cutoff: float = 0.5
    ) -> tuple[Optional[JewelryItem], list[JewelryItem]]:
        """
        Ищет украшение по названию.

        Возвращает (item, []) при однозначном совпадении, либо
        (None, [варианты]) если совпадений несколько или нет точного —
        тогда варианты можно предложить пользователю.
        """
        self.reload_if_changed()
        q = query.strip().casefold()
        exact = [item for item in self.items if item.name.casefold() == q]
        if len(exact) == 1:
            return exact[0], []
        if exact:
            return None, exact[:n]
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
