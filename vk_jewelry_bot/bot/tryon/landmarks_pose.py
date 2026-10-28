"""
Поиск плеч через mediapipe PoseLandmarker (Tasks API) — используется для
позиционирования кулона и бус: они крепятся не к лицу, а к линии шеи/плеч,
которую Face Landmarker не видит.
"""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

MODEL_PATH = Path(__file__).parent / "models" / "pose_landmarker.task"

# Индексы точек BlazePose (стабильная нумерация модели, не зависит от API)
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12


@dataclass
class NeckAnchors:
    neck_point: tuple[float, float]
    shoulder_width: float
    # Примерная ширина шеи — по ней масштабируется колье, чтобы его концы
    # уходили за шею, а не висели в воздухе. Замерено по калибровочным фото.
    neck_width: float
    # Единичный вектор «вниз по телу» (перпендикуляр к линии плеч): по нему
    # кулон опускается на грудь с учётом наклона корпуса.
    down: tuple[float, float]
    tilt_angle: float
    # Точки под ключицами — куда крепится брошь. Ключи "left"/"right" —
    # по сторонам кадра, а не по анатомии человека.
    brooch_points: dict[str, tuple[float, float]]


_base_options = BaseOptions(model_asset_path=str(MODEL_PATH), delegate=BaseOptions.Delegate.CPU)
_options = vision.PoseLandmarkerOptions(
    base_options=_base_options,
    running_mode=vision.RunningMode.IMAGE,
    num_poses=1,
)
_landmarker = vision.PoseLandmarker.create_from_options(_options)


def get_neck_anchor(image_bgr) -> Optional[NeckAnchors]:
    h, w = image_bgr.shape[:2]
    rgb = image_bgr[:, :, ::-1]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
    result = _landmarker.detect(mp_image)
    if not result.pose_landmarks:
        return None

    lm = result.pose_landmarks[0]
    a = (lm[_LEFT_SHOULDER].x * w, lm[_LEFT_SHOULDER].y * h)
    b = (lm[_RIGHT_SHOULDER].x * w, lm[_RIGHT_SHOULDER].y * h)
    # BlazePose нумерует плечи по анатomическому лево/право самого человека,
    # а не по сторонам кадра — на несельфи-фото (без зеркалирования) это
    # означает, что "левое" плечо модели физически оказывается справа в
    # кадре. Для угла наклона нам нужна именно сторона кадра, поэтому
    # сортируем точки по X, а не доверяем ярлыкам left/right модели.
    img_left, img_right = (a, b) if a[0] <= b[0] else (b, a)
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    shoulder_width = math.hypot(b[0] - a[0], b[1] - a[1])

    # Базовая точка шеи — чуть выше середины линии плеч (на уровне ключиц).
    # Коэффициент подобран по калибровочным фото: при 0.35 кулон оказывался
    # на подбородке, потому что середина линии плеч у BlazePose и так примерно
    # на уровне яремной ямки.
    neck_point = (mid[0], mid[1] - shoulder_width * 0.12)
    raw_tilt = math.degrees(math.atan2(img_right[1] - img_left[1], img_right[0] - img_left[0]))
    # Перпендикуляр к линии плеч, направленный вниз по корпусу.
    rad = math.radians(raw_tilt)
    down = (-math.sin(rad), math.cos(rad))

    # Брошь носят под ключицей, между плечом и серединой груди: сдвигаемся
    # от плеча к середине на 40% и вниз на 18% ширины плеч (проверено на
    # калибровочных фото: при 25% брошь уезжала на линию выреза платья).
    def brooch_point(shoulder):
        return (
            shoulder[0] + (mid[0] - shoulder[0]) * 0.40,
            shoulder[1] + (mid[1] - shoulder[1]) * 0.40 + shoulder_width * 0.18,
        )

    return NeckAnchors(
        brooch_points={"left": brooch_point(img_left), "right": brooch_point(img_right)},
        neck_point=neck_point,
        shoulder_width=shoulder_width,
        neck_width=shoulder_width * 0.28,
        down=down,
        tilt_angle=-raw_tilt,
    )
