"""
Сквозной тест конвейера примерки на настоящем mediapipe (а не на моках):
проверяет, что для каждой категории код доходит до вызова соответствующего
Landmarker'а и не падает, а корректно поднимает TryOnError, если на фото
не нашлось лицо/рука/плечи (здесь используется случайный шум вместо фото —
лицо/руку там найти и не должно, важно, что это не крашит процесс).

Требует mediapipe и файлы моделей в bot/tryon/models/ — то есть весь
requirements.txt, а не только Pillow/numpy как в остальных тестах.
Если mediapipe не установлен, тест аккуратно пропускается.

На macOS без явного BaseOptions(delegate=BaseOptions.Delegate.CPU) mediapipe
Tasks API падает с `Check failed: service_ Service is unavailable` при
попытке использовать GPU/Metal-путь — этот тест ловит регрессию, если кто-то
уберёт delegate=CPU из bot/tryon/landmarks_*.py.
"""
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("mediapipe")

from bot.jewelry.catalog import catalog
from bot.tryon.pipeline import TryOnError, apply_tryon


def _noise_photo_bytes(w=450, h=600) -> bytes:
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.parametrize(
    "category",
    ["earrings", "ring", "pendant", "beads", "diadem", "hairpin", "brooch", "bracelet"],
)
def test_apply_tryon_handles_no_match_gracefully(category):
    item = next((i for i in catalog.items if i.category.value == category), None)
    assert item is not None, f"в каталоге нет ни одного товара категории {category}"

    photo_bytes = _noise_photo_bytes()
    with pytest.raises(TryOnError):
        apply_tryon(item, catalog.image_path(item), photo_bytes)
