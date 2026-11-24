"""The bun workflow rejects ambiguous silhouettes and preserves the ornament."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

cv2 = pytest.importorskip("cv2")
from bot.tryon.errors import TryOnError
from bot.tryon import hair_placement as hair
from bot.tryon.compose import overlay_image


def _scene():
    confidence = np.zeros((600, 700), np.float32)
    cv2.ellipse(confidence, (290, 170), (150, 120), 0, 0, 360, 1, -1)
    cv2.ellipse(confidence, (420, 275), (70, 65), 0, 0, 360, 1, -1)
    anchors = SimpleNamespace(forehead_top=(240, 160), chin=(240, 380),
                              face_width=200, tilt_angle=0)
    return confidence, anchors


def test_round_lower_lobe_is_detected_and_scale_tracks_photo():
    confidence, anchors = _scene()
    placement = hair.locate_visible_bun(confidence, anchors)
    assert placement.center == pytest.approx((420, 275), abs=4)
    assert 60 < placement.radius < 72
    assert placement.point[1] < placement.center[1]
    assert placement.angle < 0  # stem leans inward, rather than outside the bun
    smaller = cv2.resize(confidence, None, fx=.5, fy=.5)
    scaled = SimpleNamespace(forehead_top=(120, 80), chin=(120, 190),
                            face_width=100, tilt_angle=0)
    result = hair.locate_visible_bun(smaller, scaled)
    assert result.center == pytest.approx(np.asarray(placement.center)/2, abs=2)
    assert result.radius == pytest.approx(placement.radius/2, abs=2)


def test_mirrored_bun_uses_mirrored_insertion():
    confidence, anchors = _scene()
    original = hair.locate_visible_bun(confidence, anchors)
    mirrored_anchors = SimpleNamespace(forehead_top=(459, 160), chin=(459, 380),
                                      face_width=200, tilt_angle=0)
    mirrored = hair.locate_visible_bun(confidence[:, ::-1].copy(), mirrored_anchors)
    assert mirrored.center == pytest.approx((699-original.center[0], original.center[1]), abs=3)
    assert mirrored.angle == pytest.approx(-original.angle)


def test_tilted_photo_is_measured_in_face_frame():
    confidence, anchors = _scene()
    original = hair.locate_visible_bun(confidence, anchors)
    angle = 12
    transform = cv2.getRotationMatrix2D((350, 300), angle, 1)
    rotated = cv2.warpAffine(confidence, transform, (700, 600))
    def point(value):
        return tuple(transform @ np.r_[value, 1])
    tilted = SimpleNamespace(forehead_top=point(anchors.forehead_top),
                            chin=point(anchors.chin), face_width=200, tilt_angle=angle)
    result = hair.locate_visible_bun(rotated, tilted)
    assert result.center == pytest.approx(point(original.center), abs=4)
    assert result.radius == pytest.approx(original.radius, abs=3)
    assert result.angle == pytest.approx(original.angle+angle)


@pytest.mark.parametrize("kind", ["front", "loose", "two_buns", "uncertain", "cropped"])
def test_missing_or_ambiguous_bun_requests_another_photo(kind):
    confidence, anchors = _scene()
    if kind == "front":
        confidence[:] = 0
        cv2.ellipse(confidence, (240, 120), (160, 100), 0, 0, 360, 1, -1)
    elif kind == "loose":
        confidence[:] = 0
        cv2.rectangle(confidence, (140, 100), (440, 480), 1, -1)
    elif kind == "two_buns":
        confidence[:] = 0
        cv2.ellipse(confidence, (240, 140), (140, 100), 0, 0, 360, 1, -1)
        cv2.ellipse(confidence, (70, 265), (65, 65), 0, 0, 360, 1, -1)
        cv2.ellipse(confidence, (410, 265), (65, 65), 0, 0, 360, 1, -1)
    elif kind == "uncertain":
        confidence *= .6
    elif kind == "cropped":
        confidence[:, -2:] = 1
    with pytest.raises(TryOnError, match="пучок"):
        hair.locate_visible_bun(confidence, anchors)


def test_insertion_removes_hidden_length_and_hair_occludes_only_entry():
    product = Image.new("RGBA", (40, 160))
    pixels = np.asarray(product).copy()
    pixels[:40, 5:35] = (255, 0, 0, 255)  # ornament
    pixels[40:, 18:22] = (0, 255, 0, 255)  # full shaft
    product = Image.fromarray(pixels)
    visible, shaft = hair.insertion_layers(product, .25)
    assert np.array_equal(np.asarray(visible)[:40], pixels[:40])
    assert not np.asarray(visible)[45:, :, 3].any()
    assert not np.asarray(shaft)[:40, :, 3].any()
    base = Image.new("RGBA", (120, 120), (40, 20, 10, 255))
    point, width, angle, anchor = (60, 60), 40, 0, (.5, .25)
    rendered = overlay_image(base, visible, point, width, angle, anchor)
    placement = SimpleNamespace(hair_confidence=np.ones((120, 120), np.float32))
    occluded = hair.occlude_entry(base, rendered, shaft, placement, point, width, angle, anchor)
    assert occluded.getpixel((60, 40))[:3] == (255, 0, 0)
    assert occluded.getpixel((60, 60)) == base.getpixel((60, 60))
    placement.hair_confidence[:] = 0
    no_hair = hair.occlude_entry(base, rendered, shaft, placement, point, width, angle, anchor)
    assert no_hair.tobytes() == rendered.tobytes()


def test_missing_model_fails_without_any_download(monkeypatch, tmp_path):
    monkeypatch.setattr(hair, "MODEL_PATH", tmp_path / "missing.tflite")
    with pytest.raises(TryOnError, match="Модель волос не установлена"):
        hair.hair_confidence(np.zeros((100, 100, 3), np.uint8))


def test_unpinned_model_is_rejected_before_native_initialization(monkeypatch, tmp_path):
    model = tmp_path/"wrong.tflite"
    model.write_bytes(b"wrong weights")
    monkeypatch.setattr(hair, "MODEL_PATH", model)
    monkeypatch.setattr(hair, "_segmenter", None)
    with pytest.raises(TryOnError, match="модели волос повреждён"):
        hair.hair_confidence(np.zeros((100, 100, 3), np.uint8))


def test_profile_face_frame_comes_from_semantic_face_skin():
    mask = np.zeros((600, 700), np.float32)
    cv2.ellipse(mask, (240, 280), (70, 140), 0, 0, 360, 1, -1)
    frame = hair.face_frame_from_mask(mask)
    assert frame.forehead_top == pytest.approx((240, 147), abs=10)
    assert frame.chin == pytest.approx((240, 413), abs=10)
    assert frame.tilt_angle == pytest.approx(0, abs=.01)
    assert 125 < frame.face_width < 145


@pytest.mark.parametrize("kind", ["two_faces", "tiny", "uncertain", "cropped"])
def test_profile_fallback_requires_one_confident_complete_face(kind):
    mask = np.zeros((600, 700), np.float32)
    cv2.ellipse(mask, (240, 280), (70, 140), 0, 0, 360, 1, -1)
    if kind == "two_faces":
        cv2.ellipse(mask, (490, 280), (70, 140), 0, 0, 360, 1, -1)
    elif kind == "tiny":
        mask[:] = 0
        cv2.ellipse(mask, (240, 280), (10, 20), 0, 0, 360, 1, -1)
    elif kind == "uncertain":
        mask *= .6
    elif kind == "cropped":
        mask[:280, 170:310] = 1
    with pytest.raises(TryOnError):
        hair.face_frame_from_mask(mask)
