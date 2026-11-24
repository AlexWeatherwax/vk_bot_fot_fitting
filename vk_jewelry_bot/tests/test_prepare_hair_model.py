"""Setup cannot install an unverified weight or replace a valid one accidentally."""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest


@pytest.fixture
def setup(monkeypatch):
    source = Path(__file__).resolve().parents[1]/"scripts/prepare_hair_model.py"
    spec = importlib.util.spec_from_file_location("prepare_hair_model_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    content = b"pinned test model"
    monkeypatch.setattr(module, "SIZE", len(content))
    monkeypatch.setattr(module, "SHA256", hashlib.sha256(content).hexdigest())
    return module, content


def test_verified_existing_model_never_opens_network(setup, monkeypatch, tmp_path):
    module, content = setup
    target = tmp_path/"model.tflite"
    target.write_bytes(content)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network call"))
    assert module.prepare(target) == target
    assert module.prepare(target, verify_only=True) == target


def test_setup_verifies_before_atomic_install(setup, monkeypatch, tmp_path):
    module, content = setup
    target = tmp_path/"model.tflite"
    target.write_bytes(b"previous invalid model")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(content))
    assert module.prepare(target) == target
    assert target.read_bytes() == content
    assert not list(tmp_path.glob("*.download"))


@pytest.mark.parametrize("download", [b"wrong model", b"much too large for the pinned model size"])
def test_invalid_download_does_not_replace_existing_file(setup, monkeypatch, tmp_path, download):
    module, _ = setup
    target = tmp_path/"model.tflite"
    target.write_bytes(b"existing")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(download))
    with pytest.raises(ValueError):
        module.prepare(target)
    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob("*.download"))


def test_verify_only_never_downloads_missing_file(setup, monkeypatch, tmp_path):
    module, _ = setup
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network call"))
    with pytest.raises(ValueError):
        module.prepare(tmp_path/"missing.tflite", verify_only=True)
