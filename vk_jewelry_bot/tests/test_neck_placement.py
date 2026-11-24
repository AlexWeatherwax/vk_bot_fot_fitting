"""Neck measurement is tied to exposed skin and the face, not shoulder framing."""
from types import SimpleNamespace

import numpy as np
import pytest

from bot.tryon.neck_placement import fallback_neck, locate_neck


def scene(*, chin=(400, 300), width=200, neck_ratio=.65, down=(0, 1),
          start=.025, end=.45, shape=(750, 850)):
    chin = np.asarray(chin, dtype=float)
    down = np.asarray(down, dtype=float)
    down /= np.linalg.norm(down)
    lateral = np.array([down[1], -down[0]])
    yy, xx = np.indices(shape)
    points = np.stack((xx - chin[0], yy - chin[1]), axis=-1)
    u, v = points @ lateral, points @ down
    skin = ((abs(u) < width * neck_ratio / 2)
            & (v >= width * start) & (v < width * end)).astype(np.float32)
    face = SimpleNamespace(chin=tuple(chin), forehead_top=tuple(chin - down * 220),
                           face_width=width)
    # Deliberately biased/cropped shoulder estimates must not recenter the neck.
    pose = SimpleNamespace(neck_point=(chin[0] - width * .6, chin[1] + width * .4),
                           shoulder_width=width * 7, down=tuple(down))
    return skin, face, pose, u, v


@pytest.mark.parametrize("neck_ratio", [.40, .65, .95])
def test_neck_width_is_measured_for_narrow_and_broad_necks(neck_ratio):
    skin, face, pose, _, _ = scene(neck_ratio=neck_ratio)
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width == pytest.approx(face.face_width * neck_ratio, abs=3)
    assert placement.center[0] == pytest.approx(face.chin[0], abs=2)
    assert placement.base[1] == pytest.approx(face.chin[1] + face.face_width * .45, abs=3)
    assert placement.left[0] < face.chin[0] < placement.right[0]


@pytest.mark.parametrize("chin", [(180, 300), (620, 300)])
def test_off_center_people_and_cropped_shoulders_do_not_move_the_neck(chin):
    skin, face, pose, _, _ = scene(chin=chin)
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.top_center[0] == pytest.approx(chin[0], abs=2)
    assert placement.width == pytest.approx(130, abs=3)
    assert abs(placement.center[0] - pose.neck_point[0]) > 100


def test_tilted_neck_keeps_actual_width_and_oriented_endpoints():
    skin, face, pose, _, _ = scene(down=(-.5, np.sqrt(.75)))
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width == pytest.approx(130, abs=3)
    assert placement.down == pytest.approx(pose.down)
    top = np.asarray(face.chin) + np.asarray(pose.down) * 5
    assert placement.top_center == pytest.approx(top, abs=3)
    assert np.linalg.norm(np.asarray(placement.right) - placement.left) == pytest.approx(placement.width)
    assert np.dot(np.asarray(placement.right) - placement.left, placement.down) == pytest.approx(0, abs=1e-6)


def test_small_chain_occlusion_is_closed_without_measuring_the_narrow_remaining_piece():
    skin, face, pose, u, _ = scene(neck_ratio=.8)
    skin[(u > 30) & (u < 36)] = 0
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width == pytest.approx(160, abs=3)
    assert placement.center[0] == pytest.approx(face.chin[0], abs=2)


def test_v_collar_does_not_turn_the_lower_exposed_triangle_into_neck_width():
    skin, face, pose, u, v = scene(neck_ratio=.8)
    skin[:] = ((v >= 5) & (v < 75) & (abs(u) < 80 - .8 * (v - 5))).astype(np.float32)
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width > 150
    assert placement.center[0] == pytest.approx(face.chin[0], abs=2)
    assert placement.base[1] < face.chin[1] + 75


def test_background_skin_and_lower_forearm_do_not_define_the_neck():
    skin, face, pose, u, v = scene(neck_ratio=.65)
    skin[(u > 120) & (u < 200) & (v > 5) & (v < 200)] = 1
    skin[(abs(u) < 95) & (v > 130) & (v < 200)] = 1
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width == pytest.approx(130, abs=3)
    assert placement.center[0] == pytest.approx(face.chin[0], abs=2)
    assert placement.base[1] < face.chin[1] + 100


def test_lower_exposed_chest_beyond_a_collar_cannot_replace_the_upper_neck():
    skin, face, pose, u, v = scene(end=.2)
    skin[(abs(u) < 90) & (v >= 50) & (v < 190)] = 1
    placement = locate_neck(skin, face, pose)
    assert placement.measured
    assert placement.width == pytest.approx(130, abs=3)
    assert placement.base[1] < face.chin[1] + 45


def test_connected_skin_wings_measure_upper_neck_around_the_face_hole():
    skin, face, pose, u, v = scene(neck_ratio=.6)
    skin[((abs(u) > 55) & (abs(u) < 90)) & (v >= -45) & (v < 6)] = 1
    placement = locate_neck(skin, face, pose)
    assert placement.measured and placement.upper_measured
    assert placement.width == pytest.approx(180, abs=3)
    assert face.chin[1] - 50 < placement.upper_top[1] < face.chin[1] - 30
    assert placement.center[0] == pytest.approx(face.chin[0], abs=2)
    assert placement.center[1] == pose.neck_point[1]


def test_unconnected_upper_skin_patches_are_not_neck_wings():
    skin, face, pose, u, v = scene(neck_ratio=.6)
    skin[((abs(u) > 55) & (abs(u) < 90)) & (v >= -50) & (v < -10)] = 1
    placement = locate_neck(skin, face, pose)
    assert placement.measured and not placement.upper_measured
    assert placement.upper_top is None
    assert placement.width == pytest.approx(120, abs=3)


def test_clipped_upper_wing_keeps_the_safe_lower_neck_measurement():
    skin, face, pose, u, v = scene(chin=(80, 300), neck_ratio=.6)
    skin[((abs(u) > 55) & (abs(u) < 90)) & (v >= -45) & (v < 6)] = 1
    placement = locate_neck(skin, face, pose)
    assert placement.measured and not placement.upper_measured
    assert placement.width == pytest.approx(120, abs=3)


def test_hidden_neck_uses_face_centered_fallback_without_wide_shoulder_scale():
    skin, face, pose, _, _ = scene(chin=(620, 300), end=.06)
    placement = locate_neck(skin, face, pose)
    assert not placement.measured
    assert placement.width == pytest.approx(face.face_width * .62)
    assert placement.center[0] == face.chin[0]
    assert placement.width < pose.shoulder_width * .1


def test_clipped_neck_edges_are_not_reported_as_measured():
    skin, face, pose, _, _ = scene(chin=(30, 300), neck_ratio=.8)
    placement = locate_neck(skin, face, pose)
    assert not placement.measured
    assert placement.center[0] == 30


def test_optional_face_skin_can_supply_skin_split_between_semantic_classes():
    skin, face, pose, _, _ = scene()
    placement = locate_neck(skin * .35, face, pose, face_skin=skin * .6)
    assert placement.measured
    assert placement.width == pytest.approx(130, abs=3)


def test_ambiguous_disjoint_skin_runs_are_rejected():
    skin, face, pose, u, v = scene()
    skin[:] = (((u > -85) & (u < -20) | (u > 20) & (u < 85))
               & (v >= 5) & (v < 90)).astype(np.float32)
    placement = locate_neck(skin, face, pose)
    assert not placement.measured


@pytest.mark.parametrize("invalid", [None, np.zeros((1, 1)), np.full((20, 20), np.nan)])
def test_missing_or_invalid_mask_returns_an_explicit_fallback(invalid):
    _, face, pose, _, _ = scene()
    placement = locate_neck(invalid, face, pose)
    assert not placement.measured
    assert np.isfinite(placement.center).all()


def test_fallback_requires_a_valid_face_instead_of_inventing_an_image_center():
    invalid = SimpleNamespace(chin=(100, 200), forehead_top=(100, 100), face_width=0)
    with pytest.raises(ValueError, match="face frame"):
        fallback_neck(invalid)
