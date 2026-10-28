"""
Шаг 2b — найти на исходных фото руки и лица (mediapipe).

Нужно потому, что «цвет кожи» как признак руки врёт: тёплая позолота, медь,
янтарь и ракушки попадают ровно в тот же диапазон. Настоящий детектор
отличает кадр «украшение в руке» (его брать нельзя — модель вырежет руку
вместе с украшением) от кадра «золотые серьги на сером фоне».

Лицо ищем по той же причине: часть украшений снята на манекен-голову или
бюст, и это тоже реквизит, который попадёт в вырез.

Запускать отдельным окружением (.venv-mp): mediapipe требует numpy<2,
а rembg на шаге 2 — numpy>=2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

HERE = Path(__file__).resolve().parent
MODELS = HERE.parent.parent / "bot" / "tryon" / "models"
WORK = HERE / "work"
DETECT_JSON = WORK / "detect.json"
MAX_SIDE = 1024

hand = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=str(MODELS / "hand_landmarker.task"), delegate=BaseOptions.Delegate.CPU),
    running_mode=vision.RunningMode.IMAGE,
    num_hands=2,
    min_hand_detection_confidence=0.3,
))
face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=str(MODELS / "face_landmarker.task"), delegate=BaseOptions.Delegate.CPU),
    running_mode=vision.RunningMode.IMAGE,
    num_faces=1,
))


def bbox_frac(points, w, h) -> float:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    return max(0.0, (max(xs) - min(xs))) * max(0.0, (max(ys) - min(ys)))


def main() -> None:
    items = json.loads((WORK / "items.json").read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    total = sum(len(i["photos"]) for i in items)
    done = 0
    for item in items:
        rows = []
        for idx, path in enumerate(item["photos"]):
            img = cv2.imread(path)
            if img is None:
                rows.append({"index": idx, "hands": 0, "hand_frac": 0.0, "faces": 0})
                done += 1
                continue
            h0, w0 = img.shape[:2]
            scale = MAX_SIDE / max(h0, w0)
            if scale < 1:
                img = cv2.resize(img, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))

            hres = hand.detect(mp_img)
            hands = len(hres.hand_landmarks)
            hfrac = max((bbox_frac(lm, *rgb.shape[1::-1]) for lm in hres.hand_landmarks), default=0.0)

            fres = face.detect(mp_img)
            faces = len(fres.face_landmarks)

            rows.append({"index": idx, "hands": hands, "hand_frac": round(float(hfrac), 4),
                         "faces": faces})
            done += 1
            if done % 25 == 0:
                print(f"[{done}/{total}]", flush=True)
        out[item["key"]] = rows
    DETECT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Готово:", DETECT_JSON)


if __name__ == "__main__":
    sys.exit(main())
