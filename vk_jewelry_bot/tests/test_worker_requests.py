"""Worker request parsing without loading native inference or using the network."""
import base64
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from bot.jewelry.models import Category, JewelryItem
from bot.tryon import worker
from bot.tryon.errors import TryOnError


@pytest.mark.parametrize('legacy', [False, True])
def test_worker_decodes_single_and_combined_requests(monkeypatch, legacy):
    earrings = JewelryItem('earrings', 'Серьги', Category.EARRINGS, 'earrings.png')
    pendant = JewelryItem('pendant', 'Кулон', Category.PENDANT, 'pendant.png')
    expected_items = [earrings] if legacy else [earrings, pendant]
    expected_paths = [Path('/gallery') / item.image for item in expected_items]
    request = {'photo': base64.b64encode(b'original-photo').decode()}
    if legacy:
        request.update(item=asdict(earrings), overlay=str(expected_paths[0]))
    else:
        request.update(items=[asdict(item) for item in expected_items], overlays=list(map(str, expected_paths)))
    events = []

    def render(items, paths, photo):
        assert events == ['isolated']
        assert items == expected_items
        assert paths == expected_paths
        assert photo == b'original-photo'
        return b'combined-result'

    pipeline = ModuleType('bot.tryon.pipeline')
    pipeline.apply_tryon_many = render
    monkeypatch.setitem(sys.modules, pipeline.__name__, pipeline)
    monkeypatch.setattr(worker, 'deny_network', lambda: events.append('isolated'))
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    output = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', output)
    worker.main()
    response = json.loads(output.getvalue())
    assert base64.b64decode(response['photo']) == b'combined-result'


def test_worker_returns_combination_error_without_partial_photo(monkeypatch):
    item = JewelryItem('earrings', 'Серьги', Category.EARRINGS, 'earrings.png')
    request = {'items': [asdict(item)], 'overlays': ['/gallery/earrings.png'], 'photo': base64.b64encode(b'photo').decode()}

    def render(*args):
        raise TryOnError('Не видны плечи')

    pipeline = ModuleType('bot.tryon.pipeline')
    pipeline.apply_tryon_many = render
    monkeypatch.setitem(sys.modules, pipeline.__name__, pipeline)
    monkeypatch.setattr(worker, 'deny_network', lambda: None)
    monkeypatch.setattr(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    output = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', output)
    worker.main()
    assert json.loads(output.getvalue()) == {'error': 'Не видны плечи'}
