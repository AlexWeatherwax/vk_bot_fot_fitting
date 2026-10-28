import json
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove, new_session

HERE = Path(__file__).parent
RAW_DIR = HERE / "raw"
OUT_DIR = HERE / "cutout"
MAX_DIM = 1600
ALPHA_THRESHOLD = 128
FLAG_AREA_FRACTION = 0.45  # if opaque bbox is bigger than this share of frame -> likely kept background prop

session = new_session("u2net")


def process_one(raw_path: Path, out_path: Path):
    img = Image.open(raw_path).convert("RGB")
    result = remove(img, session=session)  # RGBA

    arr = np.array(result)
    alpha = arr[:, :, 3]
    mask = alpha >= ALPHA_THRESHOLD
    if not mask.any():
        return {"ok": False, "reason": "empty mask"}

    ys, xs = np.where(mask)
    y0, y1 = ys.min(), ys.max()
    x0, x1 = xs.min(), xs.max()

    h, w = alpha.shape
    pad_y = max(2, int((y1 - y0) * 0.02))
    pad_x = max(2, int((x1 - x0) * 0.02))
    y0c, y1c = max(0, y0 - pad_y), min(h, y1 + pad_y)
    x0c, x1c = max(0, x0 - pad_x), min(w, x1 + pad_x)

    cropped = result.crop((x0c, y0c, x1c, y1c))

    bbox_area_fraction = ((x1c - x0c) * (y1c - y0c)) / (w * h)

    # downscale if needed, keep aspect
    cw, ch = cropped.size
    if max(cw, ch) > MAX_DIM:
        scale = MAX_DIM / max(cw, ch)
        cropped = cropped.resize((max(1, int(cw * scale)), max(1, int(ch * scale))), Image.LANCZOS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out_path)

    return {
        "ok": True,
        "bbox_area_fraction": round(float(bbox_area_fraction), 3),
        "flagged": bool(bbox_area_fraction > FLAG_AREA_FRACTION),
        "size": [int(cropped.size[0]), int(cropped.size[1])],
    }


def main():
    manifest = json.loads((HERE / "raw_manifest.json").read_text(encoding="utf-8"))
    report = []
    for i, entry in enumerate(manifest):
        raw_path = HERE / entry["raw_path"]
        out_path = OUT_DIR / entry["category"] / raw_path.name.replace(".jpg", ".png")
        info = process_one(raw_path, out_path)
        info.update({"category": entry["category"], "title": entry["title"], "out_path": str(out_path.relative_to(HERE))})
        report.append(info)
        print(f"[{i+1}/{len(manifest)}]", entry["category"], entry["title"], "->", info.get("bbox_area_fraction"), "FLAGGED" if info.get("flagged") else "")

    (HERE / "cutout_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    flagged = [r for r in report if r.get("flagged")]
    print(f"\nTotal: {len(report)}, flagged for review: {len(flagged)}")
    for r in flagged:
        print(" -", r["category"], r["title"], r["bbox_area_fraction"])


if __name__ == "__main__":
    main()
