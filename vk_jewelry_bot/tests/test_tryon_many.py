"""Combined rendering keeps landmarks tied to the original photo."""
import io
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from bot.jewelry.models import Category, JewelryItem


@pytest.fixture
def pipeline(monkeypatch):
    # Exercise the actual composition code without creating native landmark
    # models. MediaPipe's macOS backend may abort on import on this machine.
    import bot.tryon
    for name in ('landmarks_face', 'landmarks_hand', 'landmarks_pose'):
        module = ModuleType('bot.tryon.' + name)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(bot.tryon, name, module, raising=False)
    source = Path(__file__).resolve().parents[1] / 'bot/tryon/pipeline.py'
    spec = importlib.util.spec_from_file_location('bot.tryon._many_test_pipeline', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _photo():
    output = io.BytesIO()
    Image.new('RGB', (96, 96), 'white').save(output, format='PNG')
    return output.getvalue()


@pytest.mark.parametrize("category,method", [
    (Category.EARRINGS, "_apply_earrings"), (Category.KAFFY, "_apply_kaffy"),
    (Category.DIADEM, "_apply_diadem"), (Category.HAIRPIN, "_apply_hairpin"),
    (Category.BROOCH, "_apply_brooch"), (Category.BRACELET, "_apply_bracelet"),
    (Category.BEADS, "_apply_neck_item"), (Category.PENDANT, "_apply_neck_item"),
    (Category.RING, "_apply_ring"),
])
def test_product_anchor_is_used_by_every_category(monkeypatch, pipeline, category, method):
    anchor = SimpleNamespace(face_width=100, forehead_top=(50, 30), head_top=(50, 20),
        left_lobe=(20, 60), right_lobe=(80, 60), left_temple=(20, 30), right_temple=(80, 30),
        tilt_angle=0, brooch_points={"left": (20, 60)}, shoulder_width=100,
        point=(50, 50), wrist_width=25, angle=0, neck_width=30,
        neck_point=(50, 50), down=(0, 1), finger_width=15)
    monkeypatch.setattr(pipeline.face_mod, "get_face_anchors", lambda *a, **kw: anchor, raising=False)
    monkeypatch.setattr(pipeline.pose_mod, "get_neck_anchor", lambda *a: anchor, raising=False)
    monkeypatch.setattr(pipeline.hand_mod, "get_wrist_anchor", lambda *a: anchor, raising=False)
    monkeypatch.setattr(pipeline.hand_mod, "get_ring_anchor", lambda *a: anchor, raising=False)
    monkeypatch.setattr(pipeline, "earring_points", lambda *a: {"left": (20, 60)})
    calls = []
    monkeypatch.setattr(pipeline, "overlay_image", lambda base, *a, **kw: calls.append(kw["overlay_anchor"]) or base)
    item = JewelryItem("anchor", "anchor", category, "product.png", overlay_anchor=(.23, .67),
                       single_ear=True, chain_color="none")
    image = Image.new("RGBA", (20, 40))
    getattr(pipeline, method)(image, image, np.zeros((40, 20, 3), np.uint8), item)
    assert calls == [(.23, .67)]


def test_bun_can_use_segmented_face_frame_when_face_landmarker_rejects_profile(monkeypatch, pipeline):
    monkeypatch.setattr(pipeline.face_mod, "get_face_anchors", lambda *a: None, raising=False)
    placement = SimpleNamespace(radius=30, face_width=120, point=(50, 60), angle=-20,
                                hair_confidence=np.ones((120, 120), np.float32))
    def detect(image, anchors):
        assert anchors is None
        return placement
    monkeypatch.setattr(pipeline.hair_placement, "detect_bun", detect)
    calls = []
    original_overlay = pipeline.overlay_image
    def record(base, overlay, point, width, angle, **kwargs):
        calls.append((point, angle, kwargs["overlay_anchor"]))
        return original_overlay(base, overlay, point, width, angle, **kwargs)
    monkeypatch.setattr(pipeline, "overlay_image", record)
    item = JewelryItem("bun", "bun", Category.HAIRPIN, "product.png", hairpin_style="bun",
        hairpin_head_fraction=.3, overlay_anchor=(.4, .3), offset_x=.1, offset_y=.1)
    product = Image.new("RGBA", (20, 100), (200, 150, 10, 255))
    base = Image.new("RGB", (120, 120), "white")
    result = pipeline._apply_hairpin(base, product, np.zeros((120, 120, 3), np.uint8), item)
    assert result.size == base.size
    assert calls == [((62, 72), -20, (.4, .3))]


@pytest.mark.parametrize('second_category,renderer', [
    (Category.PENDANT, '_apply_neck_item'),
    (Category.DIADEM, '_apply_diadem'),
])
def test_combined_render_uses_original_landmarks_and_encodes_once(monkeypatch, pipeline, second_category, renderer):
    original = _photo()
    items = [
        JewelryItem('earrings', 'Серьги', Category.EARRINGS, 'earrings.png'),
        JewelryItem('second', 'Второе украшение', second_category, 'second.png'),
    ]
    overlay = Image.new('RGBA', (5, 5), (255, 0, 0, 255))
    monkeypatch.setattr(pipeline, '_load_rgba', lambda path: overlay)
    detections = []

    def earrings(base, overlay_img, np_bgr, item):
        detections.append(np_bgr)
        assert np.all(np_bgr == 255)
        base.paste((255, 0, 0), (0, 0, 32, 32))
        return base

    def second(base, overlay_img, np_bgr, item):
        detections.append(np_bgr)
        assert np.all(np_bgr == 255)
        assert base.getpixel((5, 5)) == (255, 0, 0)
        base.paste((0, 0, 255), (64, 64, 96, 96))
        return base

    monkeypatch.setattr(pipeline, '_apply_earrings', earrings)
    monkeypatch.setattr(pipeline, renderer, second)
    save = Image.Image.save
    encodes = []

    def record_save(self, fp, *args, **kwargs):
        encodes.append(kwargs.get('format'))
        return save(self, fp, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'save', record_save)
    result = pipeline.apply_tryon_many(items, ['earrings.png', 'second.png'], original)
    rendered = Image.open(io.BytesIO(result))
    assert rendered.format == 'JPEG'
    assert rendered.getpixel((5, 5))[0] > 240
    assert rendered.getpixel((90, 90))[2] > 240
    assert detections[0] is detections[1]
    assert encodes == ['JPEG']


def test_combined_render_failure_does_not_return_partial_image(monkeypatch, pipeline):
    items = [
        JewelryItem('earrings', 'Серьги', Category.EARRINGS, 'earrings.png'),
        JewelryItem('pendant', 'Кулон', Category.PENDANT, 'pendant.png'),
    ]
    photo = _photo()
    monkeypatch.setattr(pipeline, '_load_rgba', lambda path: Image.new('RGBA', (5, 5)))
    monkeypatch.setattr(pipeline, '_apply_earrings', lambda base, *args: base)

    def missing_neck(*args):
        raise pipeline.TryOnError('Не видна шея')

    def unexpected_save(*args, **kwargs):
        pytest.fail('A partial result must not be encoded')

    monkeypatch.setattr(pipeline, '_apply_neck_item', missing_neck)
    monkeypatch.setattr(Image.Image, 'save', unexpected_save)
    with pytest.raises(pipeline.TryOnError, match='Не видна шея'):
        pipeline.apply_tryon_many(items, ['earrings.png', 'pendant.png'], photo)


def test_combined_render_rejects_mismatched_paths_before_decoding_photo(pipeline):
    item = JewelryItem('earrings', 'Серьги', Category.EARRINGS, 'earrings.png')
    with pytest.raises(pipeline.TryOnError, match='изображение'):
        pipeline.apply_tryon_many([item], [], b'not-a-photo')


def test_unequal_pair_uses_each_physical_hook(monkeypatch, pipeline):
    from types import SimpleNamespace
    item = JewelryItem('pair', 'Неравные серьги', Category.EARRINGS, 'pair.png',
                       pair_image=True, pair_overlay_anchors=((.36, .015), (.72, .015)))
    parts = (Image.new('RGBA', (40, 100)), Image.new('RGBA', (50, 100)))
    monkeypatch.setattr(pipeline.face_mod, 'get_face_anchors',
                        lambda *a, **k: SimpleNamespace(face_width=200, tilt_angle=0), raising=False)
    monkeypatch.setattr(pipeline, 'earring_points', lambda *a: {'left': (20, 40), 'right': (80, 40)})
    monkeypatch.setattr(pipeline, 'split_pair', lambda *a: parts)
    calls = []

    def render(base, ornament, point, width, angle, overlay_anchor):
        calls.append((ornament, point, overlay_anchor))
        return base

    monkeypatch.setattr(pipeline, 'overlay_image', render)
    base = Image.new('RGB', (100, 100))
    pipeline._apply_earrings(base, parts[0], None, item)
    assert calls == [(parts[0], (20, 40), (.36, .015)),
                     (parts[1], (80, 40), (.72, .015))]


@pytest.mark.parametrize('tilt', [-25, 0, 28])
@pytest.mark.parametrize('offset_y', [-.1027699407, 0, .2])
def test_pendant_chain_stays_below_chin_with_catalogue_offsets(monkeypatch, pipeline, tilt, offset_y):
    import math

    rad = math.radians(tilt)
    down = (-math.sin(rad), math.cos(rad))
    neck = np.array((250., 260.))
    anchors = SimpleNamespace(neck_point=tuple(neck), shoulder_width=400,
                              down=down, tilt_angle=-tilt)
    face = SimpleNamespace(chin=tuple(neck - np.array(down) * 30), face_width=160)
    monkeypatch.setattr(pipeline.pose_mod, 'get_neck_anchor', lambda _: anchors, raising=False)
    monkeypatch.setattr(pipeline.face_mod, 'get_face_anchors', lambda _: face, raising=False)
    # The tall curated asset used to put the top .51 shoulder widths above
    # the pendant. Use the same aspect ratio and render pixels through PIL.
    chain = Image.new('RGBA', (82, 131), (255, 0, 0, 255))
    monkeypatch.setattr(pipeline, '_load_chain', lambda _: chain)
    item = JewelryItem('p', 'Кулон', Category.PENDANT, 'p.png',
                       offset_x=-.022464456, offset_y=offset_y, anchor_scale=.8)
    base = Image.new('RGB', (600, 650), 'white')
    # Transparent pendant isolates the actual chain pixels for the assertion.
    result = pipeline._apply_neck_item(base, Image.new('RGBA', (10, 30)), None, item)
    pixels = np.array(result)
    ys, xs = np.nonzero((pixels[:, :, 0] > 220) & (pixels[:, :, 1] < 50))
    assert len(xs) > 20
    projection = xs * down[0] + ys * down[1]
    chin_projection = face.chin[0] * down[0] + face.chin[1] * down[1]
    # Rotation/resampling rounds edges by at most two pixels.
    assert projection.min() >= chin_projection + 160 * pipeline.CHAIN_CHIN_CLEARANCE - 2


def test_chain_matches_calibrated_neck_height_without_changing_pendant(monkeypatch, pipeline):
    anchors = SimpleNamespace(neck_point=(570, 889), shoulder_width=869,
                              down=(0, 1), tilt_angle=0)
    face = SimpleNamespace(chin=(570, 720), face_width=390)
    monkeypatch.setattr(pipeline.pose_mod, 'get_neck_anchor', lambda _: anchors, raising=False)
    monkeypatch.setattr(pipeline.face_mod, 'get_face_anchors', lambda _: face, raising=False)
    monkeypatch.setattr(pipeline, '_load_chain', lambda _: Image.new('RGBA', (824, 1313)))
    calls = []
    monkeypatch.setattr(pipeline, 'overlay_image', lambda base, image, point, width, angle, **kw:
                        calls.append((image.size, point, width, angle, kw['overlay_anchor'])) or base)
    item = JewelryItem('p', 'Кулон', Category.PENDANT, 'p.png',
                       offset_x=-.022464456, offset_y=-.102769941,
                       anchor_scale=.8, rotation_offset=-2.2, overlay_anchor=(.5, .04))
    pipeline._apply_neck_item(Image.new('RGB', (1122, 1402)),
                              Image.new('RGBA', (40, 100)), None, item)
    chain, pendant = calls
    expected_point = (570 + 869 * item.offset_x, 889 + 869 * (.30 + item.offset_y))
    assert chain[0] == (278, 302)
    assert chain[1] == pytest.approx(expected_point)
    assert pendant[1] == pytest.approx(expected_point)
    assert pendant[2] == pytest.approx(869 * .24 * .8 * .4)
    assert pendant[3:] == (-2.2, (.5, .04))


def test_chain_without_visible_face_starts_at_neck_base(pipeline):
    anchors = SimpleNamespace(neck_point=(200, 180), shoulder_width=400, down=(0, 1))
    assert pipeline._neck_chain_height(anchors, (200, 260), None) == 80
    # Preserve the signed origin so an editor snapshot above the neck can
    # move back down without an incorrect jump in chain length.
    assert pipeline._neck_chain_height(anchors, (200, 150), None) == -30
    assert pipeline._fit_neck_chain(Image.new('RGBA', (82, 131)), 128, -30).size == (128, 1)


def test_pendant_frame_uses_measured_neck_instead_of_shoulder_midpoint(monkeypatch, pipeline):
    anchors = SimpleNamespace(neck_point=(70, 180), shoulder_width=400,
                              neck_width=112, down=(0, 1), tilt_angle=0)
    face = SimpleNamespace(chin=(180, 140), forehead_top=(180, 30), face_width=150)
    measured = SimpleNamespace(center=(180, 180), width=140, top=(180, 120))
    masks = {key: np.zeros((400, 400), np.float32) for key in ['body_skin', 'face', 'hair', 'background']}
    masks['background'][:10] = 1
    monkeypatch.setattr(pipeline.hair_placement, 'segment_features', lambda _: masks)
    monkeypatch.setattr(pipeline.neck_placement, 'locate_neck', lambda *a: measured)
    frame = pipeline._pendant_frame(anchors, face, np.zeros((400, 400, 3), np.uint8))
    assert frame.anchors.neck_point == (180, 180)
    assert frame.anchors.neck_width == 140
    assert frame.anchors.chain_top == (180, 120)
    assert frame.anchors.shoulder_width == 400  # Saved scale/offset units stay valid.
    assert anchors.neck_point == (70, 180)  # Other categories retain their anchors.
    assert frame.occlusion_mask[5, 5] == 1  # Chain tails cannot float in the background.
    assert frame.occlusion_mask[20, 20] == 0


def test_face_and_hair_hide_only_chain_preserving_photo_and_pendant(monkeypatch, pipeline):
    anchors = SimpleNamespace(neck_point=(180, 180), shoulder_width=400,
                              neck_width=140, chain_top=(180, 100), down=(0, 1), tilt_angle=0)
    mask = np.zeros((400, 400), np.float32)
    mask[100:200, 100:260] = 1
    mask[300:350, 100:260] = 1
    frame = SimpleNamespace(anchors=anchors, placement=SimpleNamespace(width=140), occlusion_mask=mask)
    monkeypatch.setattr(pipeline.pose_mod, 'get_neck_anchor', lambda _: anchors, raising=False)
    monkeypatch.setattr(pipeline.face_mod, 'get_face_anchors', lambda _: None, raising=False)
    monkeypatch.setattr(pipeline, '_pendant_frame', lambda *a: frame)
    monkeypatch.setattr(pipeline, '_load_chain', lambda _: Image.new('RGBA', (82, 131), (255, 0, 0, 255)))
    item = JewelryItem('p', 'Кулон', Category.PENDANT, 'p.png')
    result = pipeline._apply_neck_item(Image.new('RGB', (400, 400), 'white'),
        Image.new('RGBA', (10, 30), (0, 255, 0, 255)), None, item)
    assert result.getpixel((180, 150))[:3] == (255, 255, 255)
    assert result.getpixel((180, 250))[:3] == (255, 0, 0)
    assert result.getpixel((180, 310))[:3] == (0, 255, 0)
    assert result.getpixel((10, 10))[:3] == (255, 255, 255)
