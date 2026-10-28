"""
Разбор вырезанного изображения: связные компоненты, кожа (руки в кадре),
резкость, «монолитность» силуэта. Используется и при отборе кадра, и при
финальной чистке PNG.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

ALPHA_THRESHOLD = 128


def alpha_mask(rgba: Image.Image) -> np.ndarray:
    return np.array(rgba.split()[-1]) >= ALPHA_THRESHOLD


def components(mask: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Связные компоненты маски, отсортированные по площади (метка, площади)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    areas = [(i, int(stats[i, cv2.CC_STAT_AREA])) for i in range(1, n)]
    areas.sort(key=lambda t: -t[1])
    return labels, areas


def keep_significant_components(mask: np.ndarray, min_ratio: float = 0.12) -> np.ndarray:
    """
    Оставляет крупнейшую компоненту и все, что не меньше min_ratio от неё.

    Нужно, потому что у серёг в кадре две отдельные детали (пара), а вокруг
    часто остаётся мусор — пылинки, блик, кусок отражения.
    """
    labels, areas = components(mask)
    if not areas:
        return mask
    biggest = areas[0][1]
    keep = [i for i, a in areas if a >= biggest * min_ratio]
    out = np.isin(labels, keep)
    return out


def skin_fraction(rgb: np.ndarray, mask: np.ndarray) -> float:
    """Доля «кожи» внутри маски — так ловим кадры, где вырезалась рука."""
    if mask.sum() == 0:
        return 0.0
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycrcb[..., 0], ycrcb[..., 1], ycrcb[..., 2]
    skin = (y > 80) & (cr >= 133) & (cr <= 175) & (cb >= 77) & (cb <= 130)
    return float((skin & mask).sum() / mask.sum())


def sharpness(gray: np.ndarray, mask: np.ndarray) -> float:
    if mask.sum() < 50:
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap[mask].var())


def describe(rgba: Image.Image, rgb_img: Image.Image) -> dict:
    """Числовые признаки выреза — на их основе выбираем лучший кадр."""
    mask = alpha_mask(rgba)
    h, w = mask.shape
    total = h * w
    area = int(mask.sum())
    if area == 0:
        return {"empty": True, "area_frac": 0.0}

    ys, xs = np.where(mask)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    bbox_area = max(1, (y1 - y0 + 1) * (x1 - x0 + 1))

    border = np.zeros_like(mask)
    border[0, :] = border[-1, :] = True
    border[:, 0] = border[:, -1] = True

    rgb = np.array(rgb_img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    labels, areas = components(mask)
    biggest = areas[0][1] if areas else 0
    n_big = sum(1 for _, a in areas if a >= biggest * 0.12)

    return {
        "empty": False,
        "area_frac": area / total,                       # какую долю кадра занял объект
        "fill": area / bbox_area,                        # монолитность: у блюдца/кружки ~1, у серёг ~0.2
        "border_frac": float((mask & border).sum() / border.sum()),
        "skin_frac": skin_fraction(rgb, mask),
        "sharpness": sharpness(gray, mask),
        "n_components": n_big,
        "bbox": [x0, y0, x1, y1],
        "bbox_aspect": (x1 - x0 + 1) / max(1, (y1 - y0 + 1)),
        "size": [w, h],
    }
