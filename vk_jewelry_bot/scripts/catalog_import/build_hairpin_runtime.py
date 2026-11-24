"""Build product-only hairpin insertion metadata; never encodes photo positions."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "фото для калибровки/заколки"


def build():
    output = {}
    for metadata in sorted((SOURCE / "metadata").glob("*.json")):
        meta = json.loads(metadata.read_text())
        slug = meta["slug"]
        asset = SOURCE / "assets" / f"{slug}-full-tryon-v1.png"
        image = Image.open(asset).convert("RGBA")
        x0, y0, x1, y1 = image.getchannel("A").getbbox()
        bw, bh = x1-x0, y1-y0
        anchor = [(x0+meta["junction"][0]*bw)/image.width,
                  (y0+meta["junction"][1]*bh)/image.height]
        tuning = {"asset": asset.relative_to(PROJECT).as_posix(),
                  "hairpin_style": "bun", "overlay_anchor": anchor,
                  "hairpin_head_fraction": (y0+meta["head_bbox"][3]*bh)/image.height,
                  "anchor_scale": meta["head_longest_px"]/165,
                  "offset_x": 0, "offset_y": 0, "rotation_offset": 0}
        if meta["type"] == "barrette":
            tuning.update(hairpin_style="side", hairpin_side="right",
                          hairpin_head_fraction=None, anchor_scale=1.0)
        elif slug == "shpilka-fibula-vesna":
            # Coordinates describe intrinsic mechanical parts of this product.
            # They do not describe the position of a person or a hairstyle.
            recipe = json.loads((SOURCE / "fibula-occlusion.json").read_text())
            mask = Image.new("L", image.size)
            draw = ImageDraw.Draw(mask)
            for key in ("main_polygon", "small_polygon", "entry_polygon"):
                draw.polygon([(x0+p[0]*bw, y0+p[1]*bh) for p in recipe[key]], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(3.5))
            rgba = np.asarray(image).copy()
            rgba[:, :, 3] = np.rint(rgba[:, :, 3].astype(float)*np.asarray(mask)/255).astype(np.uint8)
            visible = Image.fromarray(rgba)
            target = SOURCE / "runtime-assets" / "shpilka-fibula-vesna-heads-only-v1.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            visible.save(target)
            bounds = visible.getchannel("A").getbbox()
            longest = max(bounds[2]-bounds[0], bounds[3]-bounds[1])
            hb = meta["head_bbox"]
            main_longest = max((hb[2]-hb[0])*bw, (hb[3]-hb[1])*bh)
            tuning.update(asset=target.relative_to(PROJECT).as_posix(),
                          hairpin_head_fraction=None,
                          anchor_scale=meta["head_longest_px"]/165*longest/main_longest,
                          rotation_offset=18)
        output[slug] = tuning
    target = PROJECT / "data/audit/hairpin-runtime-calibration.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"items": output}, ensure_ascii=False, indent=2)+"\n")
    print(target)


if __name__ == "__main__":
    build()
