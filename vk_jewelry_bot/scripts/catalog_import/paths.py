"""Пути, общие для всех шагов импорта."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent            # vk_jewelry_bot/
REPO_ROOT = PROJECT_ROOT.parent

# Архив нужен только для подготовки каталога, а не для запуска бота.
# Проверять его наличие следует в шаге 1, а не при импорте этого модуля.
SOURCE_DIR = Path(
    os.environ.get("JEWELRY_SOURCE_DIR") or REPO_ROOT / "assets" / "source_photos"
).expanduser().resolve()
CALIBRATION_DIR = REPO_ROOT / "assets" / "calibration_photos"
EXAMPLES_DIR = HERE / "examples"

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
