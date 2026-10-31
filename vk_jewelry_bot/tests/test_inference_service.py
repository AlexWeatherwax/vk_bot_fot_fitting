import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from bot.jewelry.models import JewelryItem, Category
from bot.tryon import service
from bot.tryon.model_manifest import valid_model, verify_models

ITEM = JewelryItem('test', 'test', Category.EARRINGS, 'test.png')


def test_worker_receives_no_vk_credentials(monkeypatch):
    monkeypatch.setenv('VK_TOKEN', 'do-not-pass')
    monkeypatch.setenv('EAR_PARSER_BACKEND', 'grounded-sam2')
    def run(command, **kwargs):
        assert command[-1] == 'bot.tryon.worker'
        assert 'VK_TOKEN' not in kwargs['env']
        assert kwargs['env']['EAR_PARSER_BACKEND'] == 'grounded-sam2'
        request = json.loads(kwargs['input'])
        assert base64.b64decode(request['photo']) == b'photo'
        return SimpleNamespace(returncode=0, stdout=json.dumps({'photo': base64.b64encode(b'jpeg').decode()}))
    monkeypatch.setattr(service.subprocess, 'run', run)
    assert service.apply_tryon(ITEM, Path('test.png'), b'photo') == b'jpeg'


def test_timeout_releases_slot(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 120)
    monkeypatch.setattr(service.subprocess, 'run', run)
    for _ in range(2):
        with pytest.raises(service.TryOnError, match='слишком много времени'):
            service.apply_tryon(ITEM, Path('test.png'), b'photo')


def test_busy_does_not_spawn_worker(monkeypatch):
    service._SLOT.acquire()
    try:
        with pytest.raises(service.TryOnError, match='другая примерка'):
            service.apply_tryon(ITEM, Path('test.png'), b'photo')
    finally:
        service._SLOT.release()


def test_model_corruption_is_rejected(tmp_path):
    import hashlib
    path = tmp_path/'model'
    path.write_bytes(b'good')
    digest = hashlib.sha256(b'good').hexdigest()
    assert valid_model(path, 4, digest)
    path.write_bytes(b'evil')
    assert not valid_model(path, 4, digest)
    with pytest.raises(ValueError, match='Missing or corrupt'):
        verify_models(tmp_path)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux seccomp integration')
def test_native_network_is_denied_in_child():
    script = '''
from bot.tryon.network_guard import deny_network
import socket
import sys
deny_network()
assert 'mediapipe' not in sys.modules
for family in (socket.AF_INET, socket.AF_INET6):
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        try:
            socket.socket(family, kind)
        except PermissionError:
            pass
        else:
            raise AssertionError('network allowed')
print('blocked')
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=service._PROJECT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'blocked'
