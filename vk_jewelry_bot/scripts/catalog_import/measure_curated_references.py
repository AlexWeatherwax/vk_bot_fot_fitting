"""Read body dimensions with the same detectors used by the try-on pipeline.

This does not run the bot, contact VK, or change calibration photographs.
Run with the project's supported MediaPipe environment. The generated audit
record lets the curated importer convert accepted pixel sizes into body units.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))


def measure() -> dict:
    import cv2
    import mediapipe
    from bot.tryon.landmarks_face import get_face_anchors
    from bot.tryon.landmarks_pose import get_neck_anchor

    references = {
        "pendants": ("кулоны/reference.jpg", get_neck_anchor),
        "brooches": ("броши/reference-blouse.png", get_neck_anchor),
        "cuffs": ("1000013935_profil_ukho_kaffy.jpg", get_face_anchors),
    }
    results = {}
    for key, (relative, detector) in references.items():
        path = PROJECT / "фото для калибровки" / relative
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Не удалось прочитать {path}")
        anchors = detector(image)
        if anchors is None:
            raise ValueError(f"Детектор не нашёл опорные точки: {path}")
        results[key] = {
            "reference": path.relative_to(PROJECT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "image_size": [image.shape[1], image.shape[0]],
            "anchors": asdict(anchors),
        }
    return {
        "schema_version": 1,
        "method": "native runtime detectors, unchanged reference photos",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "mediapipe": mediapipe.__version__,
        "detector_sha256": {
            name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
            for name in ("bot/tryon/landmarks_face.py", "bot/tryon/landmarks_pose.py")
        },
        "references": results,
    }


if __name__ == "__main__":
    output = PROJECT / "data/audit/curated-reference-measurements.json"
    record = measure()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    for key, entry in record["references"].items():
        anchors = entry["anchors"]
        print(key, {k: anchors[k] for k in ("face_width", "shoulder_width", "neck_width") if k in anchors})
