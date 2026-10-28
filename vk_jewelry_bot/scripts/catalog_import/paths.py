"""Пути, общие для всех шагов импорта."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent            # vk_jewelry_bot/
REPO_ROOT = PROJECT_ROOT.parent              # папка, где лежат и бот, и «Украшения»

# Исходная папка с фотографиями (имя с висящим пробелом — так её создали).
SOURCE_DIR = next(
    p for p in sorted(REPO_ROOT.iterdir())
    if p.is_dir() and p.name.strip().lower() == "украшения"
)

WORK_DIR = HERE / "work"
ITEMS_JSON = WORK_DIR / "items.json"
SCREEN_JSON = WORK_DIR / "screen.json"
PICKS_JSON = WORK_DIR / "picks.json"
OVERRIDES_JSON = HERE / "overrides.json"      # ручные правки выбора кадра
PREVIEW_DIR = WORK_DIR / "preview"            # мелкие превью вырезов для отчётов
CUTOUT_DIR = WORK_DIR / "cutout"              # итоговые PNG до попадания в галерею
REPORT_DIR = WORK_DIR / "report"

GALLERY_DIR = PROJECT_ROOT / "bot" / "jewelry" / "gallery"
MANIFEST_PATH = GALLERY_DIR / "manifest.json"
