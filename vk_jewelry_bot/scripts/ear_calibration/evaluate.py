"""Evaluate geometry and optional ONNX parser on deduplicated, annotated fixtures.

Run from any directory. --model uses locally supplied, appropriately licensed weights.
The report covers fixture agreement, not generalization to unseen subjects.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def evaluate(model_path=None):
    import cv2
    from bot.tryon.landmarks_face import get_face_anchors
    from bot.tryon.ear_segmentation import EarParser
    parser = EarParser(model_path) if model_path else None
    annotations = json.loads(Path(__file__).with_name('annotations.json').read_text(encoding='utf-8'))
    seen = set()
    rows = []
    for sample in annotations['samples']:
        path = ROOT / 'фото для калибровки' / sample['image']
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != sample['sha256']:
            raise ValueError(f'Calibration image changed: {sample["image"]}; review annotations')
        if digest in seen:
            raise ValueError('Duplicate image in annotated evaluation set')
        seen.add(digest)
        import numpy as np
        bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        anchors = get_face_anchors(bgr, lobe_down=.05)
        if anchors is None:
            raise RuntimeError(f'Face missing in calibration fixture: {path.name}')
        start = time.perf_counter()
        predicted = parser.predict(bgr, anchors) if parser else {}
        elapsed = time.perf_counter()-start
        for side, annotation in sample['points'].items():
            baseline = getattr(anchors, side+'_lobe')
            point = predicted.get(side)
            row = dict(image=sample['image'], side=side, visible=annotation['visible'],
                       baseline_xy=list(baseline), parser_xy=list(point.point) if point else None,
                       score=point.score if point else None, parser_seconds=round(elapsed,3))
            if annotation['visible']:
                truth = annotation['xy']
                row.update(reference_xy=truth, uncertainty_px=annotation['uncertainty_px'],
                           baseline_error_px=math.dist(baseline,truth),
                           parser_error_px=math.dist(point.point,truth) if point else None)
            rows.append(row)
    visible = [r for r in rows if r['visible']]
    found = [r for r in visible if r['parser_xy'] is not None]
    def mean(key, items):
        return sum(r[key] for r in items)/len(items) if items else None
    return dict(scope='Two synthetic views of one subject; developer-estimated contacts, not piercing labels',
                unique_images=len(seen), visible_ears=len(visible),
                baseline_mean_error_px=mean('baseline_error_px',visible),
                parser_detected_visible_ears=len(found) if parser else None,
                parser_mean_error_px=mean('parser_error_px',found),
                parser_hidden_ear_false_positives=sum(not r['visible'] and r['parser_xy'] is not None for r in rows) if parser else None,
                rows=rows)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    report = evaluate(args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))
