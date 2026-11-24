"""Rebuild the Winter berries set assets from the unchanged source photos.

Run from the repository root with Pillow, NumPy and OpenCV installed:
    .venv-mp/bin/python vk_jewelry_bot/scripts/catalog_import/prepare_winter_berries.py

No generated jewelry, model downloads or external services are used. Source
coordinates describe the actual short leaf earring, excluding the long pendant
chains attached to the crown. The existing calibrated crown cutout is reused.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[3]
GALLERY = ROOT / "vk_jewelry_bot/bot/jewelry/gallery"
OUTPUT = GALLERY / "imladris/sets"
SOURCE = ROOT / "Украшения /Диадемы/Зимние ягоды диадема+серьги/IMG_0475.JPG"


def prepare_earring() -> Image.Image:
    source = ImageOps.exif_transpose(Image.open(SOURCE)).convert("RGB")
    rgb = np.array(source.crop((1420, 760, 1840, 2010)))
    brightness = rgb.max(axis=2)
    mask = (brightness > 28).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Remove neighboring crown pendant and mannequin specks.
    mask[:600, :145] = 0
    mask[:600, 300:] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    significant = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 70]
    alpha = np.isin(labels, significant).astype(np.uint8) * 255
    # The garnet sphere is opaque even where its dark surface matches the
    # mannequin. Copy its photographed pixels inside the measured silhouette.
    cv2.ellipse(alpha, (231, 541), (69, 64), 0, 0, 360, 255, -1)
    # The original hook turns away from the light; retain its dark wire.
    hook = np.zeros_like(alpha)
    cv2.fillPoly(hook, [np.array([
        (218, 65), (227, 105), (237, 175), (247, 250), (250, 289),
        (237, 289), (229, 220), (219, 180), (215, 120),
    ])], 255)
    alpha = np.maximum(alpha, ((brightness > 12).astype(np.uint8) * 255) & hook)
    # Clean tiny mask holes in the upper crystal without filling the open leaf.
    crystal = (alpha[650:950] > 0).astype(np.uint8)
    crystal = cv2.morphologyEx(crystal, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1 - crystal)
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < 35:
            crystal[labels == i] = 1
    alpha[650:950] = crystal * 255
    image = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    image = image.crop(image.getbbox())
    image.thumbnail((900, 900), Image.Resampling.LANCZOS)
    return image


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    earring = prepare_earring()
    earring.save(OUTPUT / "zimnie-yagody-earring.png")
    crown = Image.open(
        GALLERY / "imladris/diadem/venets-diadema-zimnie-yagody-i-sergi.png"
    ).convert("RGBA")
    # Catalog overview only: try-on uses individually anchored components.
    overview = Image.new("RGBA", (1000, 750))
    overview.alpha_composite(crown, (50, 20))
    earring.thumbnail((140, 360), Image.Resampling.LANCZOS)
    overview.alpha_composite(earring, (135, 340))
    overview.alpha_composite(ImageOps.mirror(earring), (765, 340))
    overview.save(OUTPUT / "zimnie-yagody.png")


if __name__ == "__main__":
    main()
