"""
Поиск опорных точек лица через mediapipe FaceLandmarker (Tasks API): примерное
положение ушей (для серёг и каффов), подбородка, верха лба (для диадемы) и
наклона головы.

ВАЖНО: у Face Landmarker нет отдельного landmark-а именно для мочки уха
(модель описывает овал лица, а не уши целиком) — точки 234/454 это край щеки
на уровне уха, а не сама мочка. Поэтому позиция серёг — приближение; кафф
садится на ту же точку мочки, что и серьга (самая украшенная часть каффа —
на мочку, дужка уходит вверх на раковину сама). Если на конкретной картинке
украшение ложится чуть не там, подстройте offset_x/offset_y/anchor_scale
для этого украшения в manifest.json (см. bot/jewelry/gallery/README.md).
"""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

MODEL_PATH = Path(__file__).parent / "models" / "face_landmarker.task"

# Индексы landmark-ов Face Mesh (топология с 468/478 точками не менялась
# при переходе на Tasks API — это та же модель под новым интерфейсом)
_LEFT_EAR = 234    # край щеки на уровне левого (по кадру) уха
_RIGHT_EAR = 454   # край щеки на уровне правого (по кадру) уха
_CHIN = 152
_FOREHEAD = 10     # верхняя точка лба по контуру мешки (примерно линия волос)
_EYE_L_OUTER = 33
_EYE_R_OUTER = 263

# Насколько сместить точку щеки, чтобы попасть в мочку уха: доли ширины лица,
# вниз по оси «лоб -> подбородок» и наружу от центра. Замерено по
# калибровочным фото (scripts/catalog_import/8_tryon_sheets.py).
_LOBE_DOWN = 0.19
_LOBE_OUT = 0.03

# Кафф отдельной точки не получил: по заказчику, самая украшенная часть
# каффа (гроздь бусин) должна сесть примерно на мочку — ту же точку, что и
# серьга. Дужка каффа сама уйдёт вверх на раковину, раз крепится выше
# гроздь-центра картинки (см. overlay_anchor в pipeline._apply_kaffy).
# Так надёжнее, чем отдельная точка: _LOBE_DOWN/_LOBE_OUT уже откалиброваны
# по калибровочным фото, а отдельная попытка сделать то же для каффа
# (через маску-образец заказчика, переведённую в доли face_width) на живом
# фото сажала кафф то на щёку, то выше уха, чем нужно — своя точка для
# каффа не подтвердилась и была убрана.

# Висок (для заколки, которую носят не вертикально в пучке, а горизонтально,
# сбоку, над ухом): вдоль оси «подбородок -> лоб» от точки уха, доля ширины
# лица. ПРИБЛИЖЕНИЕ, не сверено с калибровочными фото — если заколка со
# style="side" ложится не там, подстройте offset_x/offset_y в manifest.json.
_TEMPLE_UP = 0.42
_TEMPLE_OUT = 0.02


@dataclass
class FaceAnchors:
    left_ear: tuple[float, float]
    right_ear: tuple[float, float]
    # Мочки уха — то место, где реально висит серьга. Точки 234/454 лежат на
    # контуре щеки, поэтому серьга, посаженная прямо в них, оказывается на щеке.
    left_lobe: tuple[float, float]
    right_lobe: tuple[float, float]
    # Висок — точка крепления заколки, которую носят горизонтально, сбоку.
    left_temple: tuple[float, float]
    right_temple: tuple[float, float]
    chin: tuple[float, float]
    forehead_top: tuple[float, float]
    head_top: tuple[float, float]   # примерная макушка (для заколок)
    face_width: float
    tilt_angle: float  # угол наклона головы, уже в системе координат для PIL.rotate


_base_options = BaseOptions(model_asset_path=str(MODEL_PATH), delegate=BaseOptions.Delegate.CPU)
_options = vision.FaceLandmarkerOptions(
    base_options=_base_options,
    running_mode=vision.RunningMode.IMAGE,
    num_faces=1,
)
_landmarker = vision.FaceLandmarker.create_from_options(_options)


def get_face_anchors(image_bgr) -> Optional[FaceAnchors]:
    h, w = image_bgr.shape[:2]
    rgb = image_bgr[:, :, ::-1]  # mediapipe ждёт RGB
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
    result = _landmarker.detect(mp_image)
    if not result.face_landmarks:
        return None

    lm = result.face_landmarks[0]

    def pt(i: int) -> tuple[float, float]:
        return (lm[i].x * w, lm[i].y * h)

    left_ear = pt(_LEFT_EAR)
    right_ear = pt(_RIGHT_EAR)
    chin = pt(_CHIN)
    forehead = pt(_FOREHEAD)
    eye_l = pt(_EYE_L_OUTER)
    eye_r = pt(_EYE_R_OUTER)

    # Face Mesh описывает только овал лица, поэтому макушки среди landmark-ов
    # нет: продлеваем ось «подбородок -> линия волос» ещё на 22% её длины —
    # это примерно то место в волосах над лбом, куда садится заколка.
    # (35% уводило заколку в воздух над головой — проверено на калибровочных фото.)
    head_top = (
        forehead[0] + (forehead[0] - chin[0]) * 0.22,
        forehead[1] + (forehead[1] - chin[1]) * 0.22,
    )

    face_width = math.hypot(right_ear[0] - left_ear[0], right_ear[1] - left_ear[1])
    raw_tilt = math.degrees(math.atan2(eye_r[1] - eye_l[1], eye_r[0] - eye_l[0]))

    # Ось «вниз» по самому лицу, а не по кадру: при наклоне головы мочки
    # уезжают вместе с ней.
    dx, dy = chin[0] - forehead[0], chin[1] - forehead[1]
    length = math.hypot(dx, dy) or 1.0
    down = (dx / length, dy / length)

    def lobe(ear, side):
        return (
            ear[0] + down[0] * _LOBE_DOWN * face_width + side * _LOBE_OUT * face_width,
            ear[1] + down[1] * _LOBE_DOWN * face_width,
        )

    def temple(ear, side):
        return (
            ear[0] - down[0] * _TEMPLE_UP * face_width + side * _TEMPLE_OUT * face_width,
            ear[1] - down[1] * _TEMPLE_UP * face_width,
        )

    return FaceAnchors(
        left_ear=left_ear,
        right_ear=right_ear,
        left_lobe=lobe(left_ear, -1),
        right_lobe=lobe(right_ear, +1),
        left_temple=temple(left_ear, -1),
        right_temple=temple(right_ear, +1),
        chin=chin,
        forehead_top=forehead,
        head_top=head_top,
        face_width=face_width,
        tilt_angle=-raw_tilt,
    )
