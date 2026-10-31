"""Grounding DINO + SAM 2.1, using the evaluated calibration constants."""
import os

import cv2
import numpy as np
from PIL import Image

from .ear_segmentation import EarPoint
from .model_manifest import verify_models


def _tensor(crop, size):
    rgb = np.asarray(crop.resize((size, size), Image.Resampling.BILINEAR), np.float32) / 255
    rgb = (rgb - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
    return rgb.transpose(2, 0, 1)[None]


def _lobe_from_mask(mask, crop_box, image_size):
    """Lower-mask contact estimate, not a detected piercing hole."""
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    top, bottom = np.quantile(ys, [.02, .98])
    level = bottom - .12 * (bottom - top)
    band = np.abs(ys - level) <= max(2, .04 * (bottom - top))
    if not np.any(band):
        return None
    x0, y0, x1, y1 = crop_box
    x = x0 + float(np.median(xs[band])) * (x1-x0) / mask.shape[1]
    y = y0 + float(np.median(ys[band])) * (y1-y0) / mask.shape[0]
    if not (0 <= x < image_size[0] and 0 <= y < image_size[1]):
        return None
    return x, y


class GroundedEarParser:
    def __init__(self, model_dir):
        verify_models(model_dir)
        os.environ['ORT_DISABLE_TELEMETRY'] = '1'
        import onnxruntime as ort
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        def session(name):
            return ort.InferenceSession(str(model_dir/name), sess_options=options,
                                        providers=['CPUExecutionProvider'])
        self.encoder = session('encoder.onnx')
        self.decoder = session('decoder.onnx')
        self.detector = session('model_quantized.onnx')
        vocab = (model_dir/'vocab.txt').read_text().splitlines()
        self.ids = np.array([[vocab.index(token) for token in ['[CLS]', 'ear', '.', '[SEP]']]], np.int64)

    def predict(self, image_bgr, anchors):
        image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        cx = (anchors.left_ear[0] + anchors.right_ear[0]) / 2
        cy = (anchors.forehead_top[1] + anchors.chin[1]) / 2
        width = anchors.face_width
        side = width * 1.65
        box = tuple(round(v) for v in (cx-side/2, cy-side/2, cx+side/2, cy+side/2))
        crop = image.crop(box)
        # Detect before encoding SAM so an image without detected ears costs less.
        outputs = self.detector.run(None, {
            'pixel_values': _tensor(crop, 800), 'input_ids': self.ids,
            'token_type_ids': np.zeros_like(self.ids),
            'attention_mask': np.ones_like(self.ids),
            'pixel_mask': np.ones((1, 800, 800), np.int64),
        })
        named = dict(zip([o.name for o in self.detector.get_outputs()], outputs))
        logits, boxes = named['logits'], named['pred_boxes']
        confidence = 1 / (1 + np.exp(-np.clip(logits[0, :, 1], -50, 50)))
        features = None
        result = {}
        for name, ear in [('left', anchors.left_ear), ('right', anchors.right_ear)]:
            candidates = []
            for k in np.where(confidence >= .25)[0]:
                x, y, w, h = boxes[0, k] * crop.width
                if not (.015*width < w < .40*width and .05*width < h < .65*width):
                    continue
                if np.linalg.norm(np.array([x+box[0], y+box[1]])-ear) > .40*width:
                    continue
                candidates.append((float(confidence[k]), x, y, w, h))
            if not candidates:
                continue
            _, x, y, w, h = max(candidates)
            if features is None:
                encoded = self.encoder.run(None, {'image': _tensor(crop, 1024)})
                features = dict(zip([o.name for o in self.encoder.get_outputs()], encoded))
            points = np.array([[x-w/2, y-h/2], [x+w/2, y+h/2], [x, y]], np.float32)
            points *= 1024/crop.width
            # This export supports one ear per decoder call, not a two-object batch.
            masks, scores = self.decoder.run(None, {
                **features, 'point_coords': points[None],
                'point_labels': np.array([[2, 3, 1]], np.float32),
                'mask_input': np.zeros((1, 1, 256, 256), np.float32),
                'has_mask_input': np.zeros(1, np.float32),
            })
            k = int(np.argmax(scores[0]))
            mask = cv2.resize(masks[0, k], (512, 512)) > 0
            point = _lobe_from_mask(mask, box, image.size)
            if point is not None:
                result[name] = EarPoint(point, float(scores[0, k]), int(mask.sum()))
        return result
