"""
Поиск положения безымянного пальца через mediapipe HandLandmarker (Tasks API)
— для примерки колец.
"""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"

# Индексы точек кисти (стабильная нумерация модели, не зависит от API):
# 0 = запястье, 9 = основание среднего пальца,
# 13 = основание безымянного пальца, 14 = его первый сустав.
_WRIST = 0
_INDEX_MCP = 5
_MIDDLE_MCP = 9
_RING_MCP = 13
_RING_PIP = 14
_PINKY_MCP = 17


@dataclass
class RingAnchor:
    point: tuple[float, float]
    finger_width: float
    angle: float


@dataclass
class WristAnchor:
    point: tuple[float, float]
    wrist_width: float
    angle: float


_base_options = BaseOptions(model_asset_path=str(MODEL_PATH), delegate=BaseOptions.Delegate.CPU)
_options = vision.HandLandmarkerOptions(
    base_options=_base_options,
    running_mode=vision.RunningMode.IMAGE,
    num_hands=1,
)
_landmarker = vision.HandLandmarker.create_from_options(_options)


def get_ring_anchor(image_bgr) -> Optional[RingAnchor]:
    h, w = image_bgr.shape[:2]
    rgb = image_bgr[:, :, ::-1]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
    result = _landmarker.detect(mp_image)
    if not result.hand_landmarks:
        return None

    lm = result.hand_landmarks[0]

    def pt(i: int) -> tuple[float, float]:
        return (lm[i].x * w, lm[i].y * h)

    mcp = pt(_RING_MCP)     # основание безымянного пальца
    pip = pt(_RING_PIP)     # первый сустав
    wrist = pt(_WRIST)
    middle_mcp = pt(_MIDDLE_MCP)

    # Кольцо носят на проксимальной фаланге, но не ровно посередине между
    # костяшкой и первым суставом, а ближе к суставу — иначе на фото оно
    # садится на костяшку. Коэффициент подобран по калибровочным фото.
    RING_ALONG_PHALANX = 0.65
    point = (
        mcp[0] + (pip[0] - mcp[0]) * RING_ALONG_PHALANX,
        mcp[1] + (pip[1] - mcp[1]) * RING_ALONG_PHALANX,
    )

    # Масштаб ладони — расстояние от запястья до основания среднего пальца,
    # от него оценивается толщина пальца (эмпирический коэффициент 0.22).
    hand_scale = math.hypot(middle_mcp[0] - wrist[0], middle_mcp[1] - wrist[1])
    finger_width = hand_scale * 0.22

    raw_angle = math.degrees(math.atan2(pip[1] - mcp[1], pip[0] - mcp[0])) - 90

    return RingAnchor(point=point, finger_width=finger_width, angle=-raw_angle)


def get_wrist_anchor(image_bgr) -> Optional[WristAnchor]:
    """
    Точка на запястье для примерки браслета.

    У модели кисти нет landmark-ов предплечья: сама точка 0 — это сгиб
    запястья, то есть край кисти. Браслет носят чуть дальше по руке, поэтому
    отступаем от точки 0 в сторону, противоположную пальцам, на треть ширины
    ладони. Ширину запястья оцениваем как 0.75 ширины ладони (расстояние
    между основаниями указательного и мизинца) — запястье уже ладони.
    """
    h, w = image_bgr.shape[:2]
    rgb = image_bgr[:, :, ::-1]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
    result = _landmarker.detect(mp_image)
    if not result.hand_landmarks:
        return None

    lm = result.hand_landmarks[0]

    def pt(i: int) -> tuple[float, float]:
        return (lm[i].x * w, lm[i].y * h)

    wrist = pt(_WRIST)
    middle_mcp = pt(_MIDDLE_MCP)
    palm_width = math.hypot(pt(_INDEX_MCP)[0] - pt(_PINKY_MCP)[0],
                            pt(_INDEX_MCP)[1] - pt(_PINKY_MCP)[1])

    # Единичный вектор «от пальцев к предплечью».
    dx, dy = wrist[0] - middle_mcp[0], wrist[1] - middle_mcp[1]
    length = math.hypot(dx, dy) or 1.0
    dx, dy = dx / length, dy / length

    # 0.33 уводило точку в предплечье; на сгибе рука ещё не расширяется.
    WRIST_ALONG = 0.18
    point = (wrist[0] + dx * palm_width * WRIST_ALONG,
             wrist[1] + dy * palm_width * WRIST_ALONG)

    # Браслет опоясывает руку поперёк, поэтому его наклон — это наклон
    # перпендикуляра к оси предплечья.
    raw_angle = math.degrees(math.atan2(dy, dx)) - 90

    # 0.75 давало полосу заметно уже руки, и концы браслета висели внутри
    # силуэта. Видимая ширина руки на этом уровне ближе к 1.25 ширины ладони
    # (перспектива: предплечье к камере ближе кисти) — замерено по
    # калибровочным фото.
    return WristAnchor(point=point, wrist_width=palm_width * 1.25, angle=-raw_angle)
