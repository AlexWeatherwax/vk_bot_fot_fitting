"""Optional ear-mask refinement. No model downloads or model loading at import.

The legacy ONNX model uses face-parsing labels 8/9; grounded-sam2 uses
a text detector and a separate segmentation model.
A mask locates visible ear tissue, NOT the actual piercing hole. Lobe contact
is estimated from its lower portion. Occluded ears may have no usable mask.
"""
from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import threading

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class EarPoint:
    point: tuple[float, float]
    score: float  # backend quality score, NOT probability of correct placement
    area: int


def points_from_logits(logits, box, image_size, anchors):
    """Return image-left/right points independently; reject small/off-face masks."""
    h, w, classes = logits.shape
    if classes != 19 or not np.isfinite(logits).all():
        raise ValueError('Expected finite H x W x 19 face-parsing logits')
    prob = np.exp(logits - logits.max(axis=2, keepdims=True))
    prob /= prob.sum(axis=2, keepdims=True)
    labels = logits.argmax(axis=2)
    # Merge ear classes: model label names are anatomical, our sides are image sides.
    mask = (np.isin(labels, [8, 9]) & (prob[:, :, 8:10].sum(axis=2) >= .6)).astype(np.uint8)
    n, cc, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    result = {}
    down = np.array(anchors.chin, dtype=float) - anchors.forehead_top
    down /= max(float(np.linalg.norm(down)), 1e-6)
    sx, sy = (box[2]-box[0])/w, (box[3]-box[1])/h
    for k in range(1, n):
        ys, xs = np.where(cc == k)
        if len(xs) < max(40, h*w*.0004):
            continue
        xy = np.column_stack((box[0]+(xs+.5)*sx, box[1]+(ys+.5)*sy))
        vertical = xy @ down
        lo, hi = np.quantile(vertical, [.02, .98])
        if hi-lo < anchors.face_width*.07 or hi-lo > anchors.face_width*.65:
            continue
        level = hi - .12*(hi-lo)
        band = np.abs(vertical-level) <= max(sy*2, .04*(hi-lo))
        if not band.any():
            continue
        point = np.median(xy[band], axis=0)
        candidates = {'left':anchors.left_ear, 'right':anchors.right_ear}
        side = min(candidates, key=lambda side: np.linalg.norm(point-candidates[side]))
        if np.linalg.norm(point-candidates[side]) > anchors.face_width*.35:
            continue
        if not (0 <= point[0] < image_size[0] and 0 <= point[1] < image_size[1]):
            continue
        candidate = EarPoint(tuple(map(float, point)), float(prob[ys, xs, 8:10].sum(axis=1).mean()), len(xs))
        if side not in result or candidate.area > result[side].area:
            result[side] = candidate
    return result


class EarParser:
    def __init__(self, model_path: Path):
        # Disable 1DS before importing ORT; API opt-out alone may be too late.
        os.environ["ORT_DISABLE_TELEMETRY"] = "1"
        import onnxruntime as ort
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        self.lock = threading.Lock()

    def predict(self, image_bgr, anchors):
        image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        cx = (anchors.left_ear[0]+anchors.right_ear[0])/2
        cy = (anchors.forehead_top[1]+anchors.chin[1])/2
        side = anchors.face_width*1.65
        box = tuple(round(v) for v in (cx-side/2, cy-side/2, cx+side/2, cy+side/2))
        crop = image.crop(box).resize((512,512), Image.Resampling.BILINEAR)
        tensor = np.asarray(crop, dtype=np.float32)/255
        tensor = (tensor-np.array([.485,.456,.406], dtype=np.float32))/np.array([.229,.224,.225],dtype=np.float32)
        with self.lock:
            output = self.session.run(None, {self.session.get_inputs()[0].name:tensor.transpose(2,0,1)[None]})[0]
        if output.ndim != 4 or output.shape[0] != 1 or output.shape[1] != 19:
            raise ValueError('Unexpected ear parser output shape')
        logits = cv2.resize(output[0].transpose(1,2,0), (512,512), interpolation=cv2.INTER_LINEAR)
        return points_from_logits(logits, box, image.size, anchors)


# Deployment supplies a model with appropriate usage rights. No implicit network I/O.


@lru_cache(maxsize=1)
def _parser_for(path):
    return EarParser(Path(path))


@lru_cache(maxsize=1)
def _grounded_parser_for(path):
    from .grounded_ears import GroundedEarParser
    return GroundedEarParser(Path(path))


def earring_points(image_bgr, anchors):
    backend = os.getenv('EAR_PARSER_BACKEND', 'legacy').strip()
    if backend not in {'legacy', 'grounded-sam2'}:
        raise ValueError('Unknown EAR_PARSER_BACKEND')
    configured = os.getenv('EAR_PARSER_MODEL', '').strip()
    if backend == 'grounded-sam2' and not configured:
        raise ValueError('EAR_PARSER_MODEL must point to downloaded grounded models')
    if not configured:
        return {'left': anchors.left_lobe, 'right': anchors.right_lobe}
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    parser = _grounded_parser_for(str(path)) if backend == "grounded-sam2" else _parser_for(str(path))
    return {side: ear.point for side, ear in parser.predict(image_bgr, anchors).items()}
