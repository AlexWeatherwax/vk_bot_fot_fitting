"""Bounded 2.5D insertion into one exposed lateral bun.

The segmenter labels hair, not buns. We accept only a rounded lower lateral
protrusion with a neck above it, distinct from the scalp and the other side.
This deliberately rejects front views, loose/ambiguous hair and cropped buns.
It is not a general hairstyle detector or a depth reconstruction.
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .compose import overlay_image
from .errors import TryOnError

MODEL_PATH = Path(__file__).parent / "models" / "selfie_multiclass_256x256.tflite"
MODEL_SHA256 = "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0"
MODEL_BYTES = 16371837
PHOTO_REQUIREMENT = (
    "Не удалось уверенно найти боковой пучок. Пришлите фото в три четверти: "
    "лицо и весь пучок видны, волосы собраны, фон отличается от волос, "
    "освещение равномерное. Фото в фас для этой шпильки не подходит."
)
_segmenter = None


@dataclass(frozen=True)
class BunPlacement:
    center: tuple[float, float]
    radius: float
    point: tuple[float, float]
    angle: float
    hair_confidence: np.ndarray
    face_width: float


@dataclass(frozen=True)
class SegmentedFaceFrame:
    forehead_top: tuple[float, float]
    chin: tuple[float, float]
    face_width: float
    tilt_angle: float


def segment_features(image_bgr: np.ndarray) -> dict[str, np.ndarray]:
    """Run the pinned, preinstalled model. There is no download path here.

    Official model class 1 is hair (Apache 2.0). Setup/provenance is recorded
    next to the model; compatible with MediaPipe Tasks 0.10.18 and 0.10.21.
    """
    global _segmenter
    if not MODEL_PATH.is_file():
        raise TryOnError("Модель волос не установлена. Администратору нужно выполнить подготовку моделей.")
    try:
        if _segmenter is None:
            if (MODEL_PATH.stat().st_size != MODEL_BYTES
                    or hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256):
                raise TryOnError("Файл модели волос повреждён. Администратору нужно повторить подготовку моделей.")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        if _segmenter is None:
            options = vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=str(MODEL_PATH),
                                         delegate=BaseOptions.Delegate.CPU),
                running_mode=vision.RunningMode.IMAGE,
                output_category_mask=False,
                output_confidence_masks=True,
            )
            _segmenter = vision.ImageSegmenter.create_from_options(options)
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        result = _segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if result.confidence_masks is None or len(result.confidence_masks) != 6:
            raise ValueError("Unexpected hair model output")
        masks = {"background": np.asarray(result.confidence_masks[0].numpy_view()).copy(),
                 "hair": np.asarray(result.confidence_masks[1].numpy_view()).copy(),
                 "body_skin": np.asarray(result.confidence_masks[2].numpy_view()).copy(),
                 "face": np.asarray(result.confidence_masks[3].numpy_view()).copy()}
    except (RuntimeError, ValueError, OSError) as exc:
        raise TryOnError("Не удалось обработать волосы на фото. Попробуйте другой снимок с видимым пучком.") from exc
    for key, mask in masks.items():
        if mask.shape != image_bgr.shape[:2]:
            mask = cv2.resize(mask, (image_bgr.shape[1], image_bgr.shape[0]))
        masks[key] = np.clip(mask, 0, 1).astype(np.float32)
    return masks


def hair_confidence(image_bgr: np.ndarray) -> np.ndarray:
    return segment_features(image_bgr)["hair"]


def detect_bun(image_bgr, anchors) -> BunPlacement:
    features = segment_features(image_bgr)
    frame = anchors if anchors is not None else face_frame_from_mask(features["face"])
    return locate_visible_bun(features["hair"], frame)


def face_frame_from_mask(confidence: np.ndarray) -> SegmentedFaceFrame:
    """Semantic face-skin fallback for a profile rejected by FaceLandmarker.

    Neck/body skin is a separate model class and never enters this PCA. One
    confident, complete, elongated face region is required; no face is invented
    from a hair silhouette. This frame is used only for bun insertion.
    """
    confidence = np.asarray(confidence, np.float32)
    if confidence.ndim != 2 or not np.isfinite(confidence).all():
        raise TryOnError(PHOTO_REQUIREMENT)
    mask = (confidence >= .8).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    substantial = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= mask.size*.005]
    if len(substantial) != 1:
        raise TryOnError(PHOTO_REQUIREMENT)
    face = labels == substantial[0]
    yy, xx = np.where(face)
    if len(xx) < mask.size*.015 or len(xx) > mask.size*.35:
        raise TryOnError(PHOTO_REQUIREMENT)
    if min(xx) <= 2 or min(yy) <= 2 or max(xx) >= mask.shape[1]-3 or max(yy) >= mask.shape[0]-3:
        raise TryOnError(PHOTO_REQUIREMENT)
    points = np.column_stack((xx, yy)).astype(float)
    center = points.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov(points.T))
    if values[1] < values[0]*1.25:
        raise TryOnError(PHOTO_REQUIREMENT)
    down = vectors[:, 1]
    if down[1] < 0:
        down = -down
    if down[1] < .8:
        raise TryOnError(PHOTO_REQUIREMENT)
    right = np.array([down[1], -down[0]])
    vertical = (points-center) @ down
    horizontal = (points-center) @ right
    top, bottom = np.quantile(vertical, [.015, .985])
    height = bottom-top
    width = float(np.quantile(horizontal, .98)-np.quantile(horizontal, .02))
    if height < 80 or not .30 < width/height < .95:
        raise TryOnError(PHOTO_REQUIREMENT)
    forehead = center+down*top
    chin = center+down*bottom
    return SegmentedFaceFrame(tuple(forehead), tuple(chin), width,
                               math.degrees(math.atan2(down[0], down[1])))


def locate_visible_bun(confidence: np.ndarray, anchors) -> BunPlacement:
    """Find a side lobe in an upright face frame; all thresholds scale to face height.

    The lateral envelope must recede above and below the lobe. Distance to the
    hair boundary establishes a nontrivial interior and the ornament scale.
    Neither a product id nor a reference-photo coordinate enters this function.
    """
    confidence = np.asarray(confidence, dtype=np.float32)
    if confidence.ndim != 2 or not np.isfinite(confidence).all():
        raise TryOnError(PHOTO_REQUIREMENT)
    origin = np.asarray(anchors.forehead_top, dtype=float)
    down = np.asarray(anchors.chin, dtype=float) - origin
    face_height = float(np.linalg.norm(down))
    if face_height < 50:
        raise TryOnError(PHOTO_REQUIREMENT)
    down /= face_height
    right = np.array([down[1], -down[0]])
    # A compact normalized image also bounds contour work on large uploads.
    unit = 240.0
    scale = unit / face_height
    transform = np.array([[right[0]*scale, right[1]*scale, 420-np.dot(right, origin)*scale],
                          [down[0]*scale, down[1]*scale, 300-np.dot(down, origin)*scale]])
    upright = cv2.warpAffine(confidence, transform, (840, 660), flags=cv2.INTER_LINEAR)
    binary = (upright >= .75).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    components = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > unit*unit*.12]
    if len(components) != 1:
        raise TryOnError(PHOTO_REQUIREMENT)
    hair = (labels == components[0]).astype(np.uint8)
    ys, xs = np.where(hair)
    # The entire hairstyle has to fit into both original and normalized frames.
    if not len(xs) or min(xs) < 4 or max(xs) > 835 or min(ys) < 4 or max(ys) > 655:
        raise TryOnError(PHOTO_REQUIREMENT)
    original_hair = confidence >= .75
    if (original_hair[:3].any() or original_hair[-3:].any()
            or original_hair[:, :3].any() or original_hair[:, -3:].any()):
        raise TryOnError(PHOTO_REQUIREMENT)
    distance = cv2.distanceTransform(hair, cv2.DIST_L2, 5)
    candidates = []
    # A lateral lower lobe is a second bulge, below the scalp maximum.
    for side in (-1, 1):
        envelope = np.zeros(hair.shape[0], np.float32)
        for y in range(250, 570):
            row = np.flatnonzero(hair[y])
            if row.size:
                envelope[y] = max(0, (row[-1]-420) if side == 1 else (420-row[0]))
        smooth = cv2.GaussianBlur(envelope.reshape(-1, 1), (1, 0), 4).ravel()
        peaks = [y for y in range(350, 510)
                 if smooth[y] >= smooth[y-1] and smooth[y] > smooth[y+1]]
        for y in peaks:
            extent = smooth[y]
            upper = float(np.min(smooth[max(300, y-100):y-24]))
            lower = float(np.min(smooth[y+24:min(570, y+100)]))
            prominence = min(extent-upper, extent-lower)
            if extent < unit*.65 or prominence < unit*.12:
                continue
            xx, yy = np.meshgrid(np.arange(840), np.arange(660))
            lateral = side*(xx-420)
            roi = ((lateral > extent-unit*.38) & (lateral < extent)
                   & (np.abs(yy-y) < unit*.16) & (distance >= unit*.10))
            scores = np.where(roi, distance, 0)
            _, radius, _, (cx, cy) = cv2.minMaxLoc(scores)
            if not unit*.10 <= radius <= unit*.40:
                continue
            # Compact interior: a bun must have hair all around its center,
            # unlike an open-ended curtain of long hair at the search boundary.
            if not 335 < cy < 525 or abs(cx-420) < unit*.50:
                continue
            if abs(cy-y) > radius*.9:
                continue
            candidates.append((prominence*radius, side, cx, cy, radius))
    candidates.sort(reverse=True)
    # Merge neighboring maxima of the same lobe before ambiguity rejection.
    distinct = []
    for candidate in candidates:
        if not any(math.hypot(candidate[2]-other[2], candidate[3]-other[3]) < max(candidate[4], other[4])
                   for other in distinct):
            distinct.append(candidate)
    if not distinct or (len(distinct) > 1 and distinct[1][0] > distinct[0][0]*.55):
        raise TryOnError(PHOTO_REQUIREMENT)
    _, side, cx, cy, radius = distinct[0]
    center = origin + right*((cx-420)/scale) + down*((cy-300)/scale)
    radius /= scale
    point = center + right*(side*radius*.30) - down*(radius*.35)
    # Vertical source shafts lean inward towards the bun center.
    angle = math.degrees(math.atan2(-side*.30, .75)) + float(anchors.tilt_angle)
    return BunPlacement(tuple(center), radius, tuple(point), angle, confidence, float(anchors.face_width))


def ornament_length(overlay: Image.Image, head_fraction: float | None) -> float:
    alpha = np.asarray(overlay.getchannel("A"))
    if head_fraction is not None:
        alpha = alpha[:max(1, round(head_fraction*overlay.height))]
    yy, xx = np.where(alpha >= 128)
    if not len(xx):
        raise TryOnError("На изображении шпильки не найдена декоративная головка.")
    return float(max(xx.max()-xx.min()+1, yy.max()-yy.min()+1))


def insertion_layers(overlay: Image.Image, head_fraction: float | None):
    """Keep the ornament, and only the short projected stem at the entry.

    Beyond the entry the pin lies inside the bun (2.5D insertion, not an
    estimate of its hidden 3D length). The remaining entry segment is occluded
    by the actual hair confidence in occlude_entry(). Product colors are kept.
    """
    if head_fraction is None:
        return overlay, Image.new("RGBA", overlay.size)
    arr = np.asarray(overlay).copy()
    boundary = head_fraction*overlay.height
    head = ornament_length(overlay, head_fraction)
    y = np.arange(overlay.height, dtype=float)[:, None]
    projected = head*.055
    feather = max(1., head*.012)
    visible = np.clip((boundary+projected+feather-y)/feather, 0, 1)
    arr[:, :, 3] = np.rint(arr[:, :, 3]*visible).astype(np.uint8)
    shaft = np.zeros_like(arr)
    shaft[:, :, :3] = 255
    shaft[:, :, 3] = np.where(y >= boundary, arr[:, :, 3], 0)
    return Image.fromarray(arr), Image.fromarray(shaft)


def occlude_entry(base, rendered, shaft, placement, point, width, angle, anchor):
    """Restore original hair only over the stem; decorative pixels stay in front."""
    mask_image = overlay_image(Image.new("RGBA", base.size), shaft, point, width, angle, anchor)
    shaft_alpha = np.asarray(mask_image.getchannel("A"), dtype=np.float32)/255
    hair = np.clip((placement.hair_confidence-.45)/.30, 0, 1)
    restore = Image.fromarray(np.rint(255*shaft_alpha*hair).astype(np.uint8), "L")
    return Image.composite(base.convert("RGBA"), rendered.convert("RGBA"), restore)
