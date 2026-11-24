"""Build the first-install runtime archive without credentials or local caches.

Run from any directory: python scripts/build_deploy_bundle.py --output /tmp/imladris.tar.gz
The live catalogue on an existing server must not be replaced by this first-install archive.
"""
import argparse
from contextlib import contextmanager
import fcntl
from pathlib import Path
import tarfile


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = (
    'анфас-v3/reference-front.jpg', '1000013935_profil_ukho_kaffy.jpg',
    '1000013933.jpg', '1000013934.jpg', 'заколки/reference-updo.png',
    'кулоны/reference.jpg', 'броши/reference-blouse.png',
)
RUNTIME_SCRIPTS = (
    'scripts/server_smoke.py',
    'scripts/catalog_import/measure_curated_references.py',
)
DEPLOY_FILES = (
    'deploy/README.md', 'deploy/install.sh', 'deploy/activate.sh', 'deploy/check_config.py',
    'deploy/imladris-bot.service', 'deploy/imladris-editor.service',
    'deploy/bot.env.example', 'deploy/editor.env.example',
    'deploy/configure_owner_ssh.py',
)
EXCLUDED_PARTS = {'__pycache__', '.pytest_cache', '.editor-staging',
                  '.editor-backups', '.git', '.venv', 'windows', 'deploy'}
RUNTIME_SUFFIXES = {'.py', '.png', '.webp', '.jpg', '.jpeg', '.json', '.md',
                    '.txt', '.task', '.tflite', '.onnx', '.npy', '.npz',
                    '.js', '.css', '.html', '.svg'}


def runtime_files(root):
    required = [root / name for name in (
        'run.py', 'requirements.txt', 'requirements.lock.txt',
        'bot/jewelry/gallery/manifest.json', 'jewelry_editor/app.py',
        'jewelry_editor/requirements.txt', *RUNTIME_SCRIPTS, *DEPLOY_FILES,
    )]
    required.extend(root / 'фото для калибровки' / name for name in REFERENCES)
    missing = [str(p.relative_to(root)) for p in required if not p.is_file()]
    if missing:
        raise ValueError('В комплекте отсутствуют файлы: ' + ', '.join(missing))
    selected = set(required)
    for directory in ('bot', 'jewelry_editor'):
        for path in (root / directory).rglob('*'):
            rel = path.relative_to(root)
            if any(part.startswith('.') or part in EXCLUDED_PARTS for part in rel.parts):
                continue
            if path.is_symlink():
                raise ValueError('Символическая ссылка не переносится: ' + str(rel))
            if path.is_file() and path.suffix.lower() in RUNTIME_SUFFIXES:
                selected.add(path)
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Файл выходит за пределы проекта: ' + str(path))
        with path.open('rb') as stream:
            prefix = stream.read(256)
        if b'-----BEGIN ' in prefix and b'PRIVATE KEY-----' in prefix:
            raise ValueError('Приватный ключ не должен входить в комплект: ' + str(path.relative_to(root)))
    return sorted(selected)


@contextmanager
def catalogue_snapshot(root):
    # The editor uses the same advisory lock for its atomic catalogue writes.
    with (root / 'bot/jewelry/gallery/.editor.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def build_bundle(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Архив уже существует; выберите новое имя: ' + str(output))
    with catalogue_snapshot(root):
        paths = runtime_files(root)
        output.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with output.open('xb') as destination:
                created = True
                with tarfile.open(fileobj=destination, mode='w:gz') as archive:
                    for path in paths:
                        arcname = str(Path('vk_jewelry_bot') / path.relative_to(root))
                        archive.add(path, arcname=arcname, recursive=False)
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    count = build_bundle(ROOT, args.output)
    print(f'Архив подготовлен: {args.output.resolve()} ({count} файлов, без ключей и .env)')


if __name__ == '__main__':
    main()
