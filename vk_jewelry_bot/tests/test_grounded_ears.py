import numpy as np
from bot.tryon.grounded_ears import _lobe_from_mask


def test_lobe_maps_crop_coordinates_back_to_photo():
    mask = np.zeros((100, 100), bool)
    mask[20:81, 40:61] = True
    x, y = _lobe_from_mask(mask, (100, 200, 300, 400), (500, 600))
    assert x == 200
    assert 340 <= y <= 350


def test_empty_or_outside_mask_has_no_attachment():
    assert _lobe_from_mask(np.zeros((100, 100), bool), (0, 0, 100, 100), (100, 100)) is None
    assert _lobe_from_mask(np.ones((100, 100), bool), (-200, -200, -100, -100), (100, 100)) is None
