"""Native model probe on existing photos, with diagnostics and real runtime renders.

Run from the project directory, e.g. python scripts/probe_hairpin_runtime.py.
No network calls or manual photo anchor coordinates are used.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from bot.jewelry.models import Category, JewelryItem
from bot.tryon import pipeline
from bot.tryon import hair_placement as hair
from bot.tryon.errors import TryOnError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT/"data/audit/hairpin-runtime-probe")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    tuning = json.loads((PROJECT/"data/audit/hairpin-runtime-calibration.json").read_text())["items"]
    refs = {"bun": PROJECT/"фото для калибровки/заколки/reference-updo.png",
            "front": PROJECT/"фото для калибровки/анфас-v3/reference-front.jpg"}
    report = {"model_sha256": hashlib.sha256(hair.MODEL_PATH.read_bytes()).hexdigest(),
              "model_bytes": hair.MODEL_PATH.stat().st_size, "references": {}}
    for name, path in refs.items():
        base = Image.open(path).convert("RGB")
        bgr = cv2.cvtColor(np.asarray(base), cv2.COLOR_RGB2BGR)
        anchors = pipeline.face_mod.get_face_anchors(bgr)
        entry = {"source": path.relative_to(PROJECT).as_posix(), "size": list(base.size),
                 "anchors": asdict(anchors) if anchors else None}
        report["references"][name] = entry
        features = hair.segment_features(bgr)
        confidence = features["hair"]
        np.save(args.output/f"{name}-hair-confidence.npy", confidence)
        np.save(args.output/f"{name}-face-confidence.npy", features["face"])
        Image.fromarray(np.rint(255*features["face"]).astype(np.uint8)).save(args.output/f"{name}-face-confidence.png")
        Image.fromarray(np.rint(255*confidence).astype(np.uint8)).save(args.output/f"{name}-hair-confidence.png")
        # A side barrette uses the existing temple workflow, independently of
        # the bun gate. Check it on the front reference as well.
        if anchors is not None:
            entry["side_renders"] = {}
            for slug, params in tuning.items():
                if params["hairpin_style"] != "side":
                    continue
                params = dict(params)
                asset = PROJECT/params.pop("asset")
                item = JewelryItem(slug, slug, Category.HAIRPIN, asset.name, **params)
                try:
                    result = pipeline._apply_hairpin(base, pipeline._load_rgba(asset), bgr, item)
                    result.convert("RGB").save(args.output/f"{name}-{slug}.jpg", quality=92)
                    entry["side_renders"][slug] = "ok"
                except TryOnError as exc:
                    entry["side_renders"][slug] = str(exc)
        try:
            if anchors is None:
                anchors = hair.face_frame_from_mask(features["face"])
                entry["segmented_face_frame"] = asdict(anchors)
            placement = hair.locate_visible_bun(confidence, anchors)
            entry["placement"] = {key: getattr(placement, key) for key in ("center", "radius", "point", "angle")}
            debug = base.copy()
            draw = ImageDraw.Draw(debug)
            x, y = placement.center; r = placement.radius
            draw.ellipse((x-r, y-r, x+r, y+r), outline="cyan", width=4)
            x, y = placement.point
            draw.ellipse((x-6, y-6, x+6, y+6), fill="red")
            debug.save(args.output/f"{name}-detected-bun.jpg")
            mirrored = type(anchors)(**{**asdict(anchors),
                **{key: (base.width-1-value[0], value[1]) for key, value in asdict(anchors).items()
                   if isinstance(value, tuple)}, "tilt_angle": -anchors.tilt_angle})
            mirror_placement = hair.locate_visible_bun(confidence[:, ::-1].copy(), mirrored)
            entry["mirrored_placement"] = {key: getattr(mirror_placement, key) for key in ("center", "radius", "point", "angle")}
            entry["renders"] = {}
            # Reuse the same local model inference for this immutable source photo.
            original_detect = hair.detect_bun
            hair.detect_bun = lambda image, face: placement
            try:
                for slug, params in tuning.items():
                    params = dict(params)
                    asset = PROJECT/params.pop("asset")
                    item = JewelryItem(slug, slug, Category.HAIRPIN, asset.name, **params)
                    try:
                        result = pipeline._apply_hairpin(base, pipeline._load_rgba(asset), bgr, item)
                        result.convert("RGB").save(args.output/f"{name}-{slug}.jpg", quality=92)
                        entry["renders"][slug] = "ok"
                    except TryOnError as exc:
                        entry["renders"][slug] = str(exc)
            finally:
                hair.detect_bun = original_detect
        except TryOnError as exc:
            entry["error"] = str(exc)
        print(name, entry.get("placement", entry.get("error")), flush=True)
        (args.output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    (args.output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")


if __name__ == "__main__":
    main()
