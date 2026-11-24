from dataclasses import asdict
import json

import pytest

from bot.jewelry.models import item_from_dict, item_photo_instruction


BASE = dict(id='pin', name='Шпилька', category='hairpin', image='pin.png')


def test_asset_coordinates_survive_worker_json_roundtrip():
    item = item_from_dict(dict(BASE, overlay_anchor=[.4, .35],
                               hairpin_head_fraction=.43, hairpin_style='bun'))
    assert item_from_dict(json.loads(json.dumps(asdict(item)))) == item
    assert 'пучком' in item_photo_instruction(item)


@pytest.mark.parametrize('anchor', [[-.1, .2], [.5, 1.1], [.1], 'x',
                                  [True, .5], [float('nan'), .5]])
def test_invalid_asset_anchor_is_rejected(anchor):
    with pytest.raises(ValueError, match='Точка крепления'):
        item_from_dict(dict(BASE, overlay_anchor=anchor))


@pytest.mark.parametrize('head', [0, 1, -.5, float('inf'), True])
def test_invalid_hairpin_split_is_rejected(head):
    with pytest.raises(ValueError, match='Граница головки'):
        item_from_dict(dict(BASE, hairpin_head_fraction=head))


def test_sequential_mode_requires_a_set():
    with pytest.raises(ValueError, match='только у набора'):
        item_from_dict(dict(BASE, tryon_mode='sequential'))


def test_unequal_earring_attachments_survive_worker_roundtrip():
    item = item_from_dict(dict(BASE, category='earrings', pair_image=True,
                              pair_overlay_anchors=[[.36, .015], [.72, .015]]))
    assert item_from_dict(json.loads(json.dumps(asdict(item)))) == item


def test_pair_attachments_cannot_be_used_for_a_single_piece():
    with pytest.raises(ValueError, match='только для пары'):
        item_from_dict(dict(BASE, pair_overlay_anchors=[[.36, .015], [.72, .015]]))
