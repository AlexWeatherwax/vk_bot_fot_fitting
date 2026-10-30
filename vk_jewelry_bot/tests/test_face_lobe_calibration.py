"""Geometry checks; no user photos are stored in the test suite."""
from types import SimpleNamespace
import math
import numpy as np
import pytest

pytest.importorskip('mediapipe')
from bot.tryon import landmarks_face as face


@pytest.mark.parametrize('tilt', [0, -20, 20])
def test_earring_correction_follows_face_axis_and_preserves_scale(monkeypatch, tilt):
    angle = math.radians(tilt)
    def point(x, y):
        return SimpleNamespace(x=.5 + x*math.cos(angle)-y*math.sin(angle),
                               y=.5 + x*math.sin(angle)+y*math.cos(angle))
    lm = [point(0, 0) for _ in range(478)]
    for index, xy in {234:(-.2,0),454:(.2,0),10:(0,-.3),152:(0,.3),33:(-.1,-.1),263:(.1,-.1)}.items():
        lm[index] = point(*xy)
    monkeypatch.setattr(face, '_landmarker', SimpleNamespace(detect=lambda image: SimpleNamespace(face_landmarks=[lm])))
    photo = np.zeros((1000,1000,3),dtype=np.uint8)
    legacy = face.get_face_anchors(photo)
    adjusted = face.get_face_anchors(photo,lobe_down=.05)
    assert adjusted.face_width == pytest.approx(400)
    assert adjusted.tilt_angle == legacy.tilt_angle
    down = np.array([-math.sin(angle),math.cos(angle)])
    for old, new in [(legacy.left_lobe, adjusted.left_lobe),(legacy.right_lobe, adjusted.right_lobe)]:
        assert np.array(old)-np.array(new) == pytest.approx(down*56)
    if tilt == 0:
        assert legacy.left_lobe == pytest.approx((288,576))
        assert adjusted.left_lobe == pytest.approx((288,520))


def test_no_face_still_returns_none(monkeypatch):
    monkeypatch.setattr(face, '_landmarker', SimpleNamespace(detect=lambda image: SimpleNamespace(face_landmarks=[])))
    assert face.get_face_anchors(np.zeros((100,100,3),dtype=np.uint8),lobe_down=.05) is None
