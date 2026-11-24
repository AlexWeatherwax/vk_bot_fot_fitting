"""Verify that a complete runtime transfer never carries local credentials."""
import importlib.util
from pathlib import Path
import tarfile

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/build_deploy_bundle.py'
spec = importlib.util.spec_from_file_location('build_deploy_bundle', SOURCE)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    names = [
        'run.py', 'requirements.txt', 'requirements.lock.txt',
        'bot/jewelry/gallery/manifest.json', 'bot/tryon/models/face.task',
        'bot/jewelry/gallery/custom/owner.png', 'bot/tryon/assets/chain.png',
        'jewelry_editor/app.py', 'jewelry_editor/requirements.txt',
        'jewelry_editor/static/app.js', *bundle.RUNTIME_SCRIPTS, *bundle.DEPLOY_FILES,
    ]
    names += ['фото для калибровки/' + name for name in bundle.REFERENCES]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'[]' if name.endswith('manifest.json') else b'runtime')
    return root


def test_archive_keeps_runtime_and_custom_catalogue_but_excludes_secrets(project, tmp_path):
    for name in ('.env', 'bot/.env', 'bot/private.key', 'bot/owner_ed25519',
                 'bot/jewelry/gallery/.editor-staging/photo.png',
                 'bot/jewelry/gallery/.editor-backups/manifest.json',
                 'jewelry_editor/windows/owner_ed25519',
                 'jewelry_editor/windows/config.json'):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'PRIVATE-CREDENTIAL-OR-USER-PHOTO')
    target = tmp_path / 'runtime.tar.gz'
    bundle.build_bundle(project, target)
    with tarfile.open(target) as archive:
        names = archive.getnames()
        assert 'vk_jewelry_bot/bot/jewelry/gallery/custom/owner.png' in names
        assert 'vk_jewelry_bot/bot/tryon/models/face.task' in names
        assert 'vk_jewelry_bot/jewelry_editor/static/app.js' in names
        assert all('PRIVATE-CREDENTIAL' not in archive.extractfile(member).read().decode()
                   for member in archive.getmembers())
        assert not any('windows/' in name or '/.' in name for name in names)


def test_incomplete_reference_bundle_fails_before_creating_archive(project, tmp_path):
    (project / 'фото для калибровки/броши/reference-blouse.png').unlink()
    target = tmp_path / 'runtime.tar.gz'
    with pytest.raises(ValueError, match='reference-blouse'):
        bundle.build_bundle(project, target)
    assert not target.exists()


def test_symlink_cannot_export_a_file_outside_project(project, tmp_path):
    secret = tmp_path / 'private-key'
    secret.write_text('secret')
    (project / 'bot/key.txt').symlink_to(secret)
    with pytest.raises(ValueError, match='ссылка'):
        bundle.build_bundle(project, tmp_path / 'runtime.tar.gz')


def test_existing_transfer_archive_is_not_overwritten(project, tmp_path):
    target = tmp_path / 'runtime.tar.gz'
    target.write_bytes(b'previous archive')
    with pytest.raises(ValueError, match='существует'):
        bundle.build_bundle(project, target)
    assert target.read_bytes() == b'previous archive'


def test_private_key_header_is_rejected_even_with_runtime_extension(project, tmp_path):
    (project / 'bot/key.txt').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nsecret')
    with pytest.raises(ValueError, match='Приватный ключ'):
        bundle.build_bundle(project, tmp_path / 'runtime.tar.gz')
