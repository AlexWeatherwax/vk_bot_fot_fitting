"""Render the active catalog through the actual offline service/worker on Linux.

No VK configuration or API is loaded. Use synthetic calibration photographs.
Run from project root: python scripts/server_smoke.py --output data/audit/linux-smoke
"""
import argparse
import ast
from datetime import datetime, timezone
import importlib.metadata
import io
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from bot.jewelry.catalog import catalog
from bot.jewelry.models import Category
from bot.jewelry.selection import photo_steps
from bot.tryon import service


def editor_settings_check():
    """Validate actual editor schema without starting its authenticated HTTP app."""
    from pydantic import BaseModel, ConfigDict, Field, field_validator
    source = ast.parse((ROOT / 'jewelry_editor/app.py').read_text())
    node = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Settings')
    scope = dict(__name__='editor_schema_check', BaseModel=BaseModel, ConfigDict=ConfigDict,
                 Field=Field, field_validator=field_validator, Category=Category, Literal=Literal)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<editor-schema>', 'exec'), scope)
    settings = scope['Settings']
    entries = json.loads(catalog.manifest_path.read_text())
    for item in entries:
        if item['category'] != Category.SET.value:
            settings.model_validate({k: v for k, v in item.items() if k in settings.model_fields})
    return sum(e['category'] != Category.SET.value for e in entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    references = ROOT / 'фото для калибровки'
    photo_for = {
        Category.KAFFY: references / '1000013935_profil_ukho_kaffy.jpg',
        Category.RING: references / '1000013933.jpg',
        Category.BRACELET: references / '1000013934.jpg',
    }
    # A separate child verifies that the same fail-closed filter denies sockets.
    guard = subprocess.run([sys.executable, '-c',
        'from bot.tryon.network_guard import deny_network; deny_network(); '
        'print("network_denied")'], cwd=ROOT, capture_output=True, text=True, check=True)
    assert guard.stdout.strip() == 'network_denied'
    startup_env = {**os.environ, 'VK_TOKEN': 'offline-validation-placeholder', 'VK_GROUP_ID': '1'}
    startup = subprocess.run([sys.executable, '-c',
        'import bot.app; print("handlers_registered")'], cwd=ROOT, env=startup_env,
        capture_output=True, text=True, timeout=30)
    if startup.returncode:
        raise RuntimeError('Offline application import failed: ' + startup.stderr[-2500:])
    assert startup.stdout.strip() == 'handlers_registered'
    report = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                  platform=platform.platform(), architecture=platform.machine(),
                  python=platform.python_version(), network_filter='verified',
                  application_import='verified_without_VK',
                  editor_individual_schemas_validated=editor_settings_check(),
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [ROOT/'bot/jewelry/gallery/manifest.json',
                                           *sorted((ROOT/'bot/tryon').glob('*.py'))]},
                  versions={p: importlib.metadata.version(p) for p in
                            ['mediapipe', 'numpy', 'Pillow', 'opencv-contrib-python',
                             'vkbottle', 'onnxruntime']}, jobs=[])
    for item in catalog.items[:args.limit]:
        for index, parts in enumerate(photo_steps(item)):
            first = parts[0]
            photo = photo_for.get(first.category, references / 'анфас-v3/reference-front.jpg')
            if first.category == Category.HAIRPIN and first.hairpin_style == 'bun':
                photo = references / 'заколки/reference-updo.png'
            job = dict(id=item.id, name=item.name, step=index,
                       categories=[p.category.value for p in parts],
                       reference=str(photo.relative_to(ROOT)))
            start = time.monotonic()
            try:
                result = service.apply_tryon_many(parts, [catalog.image_path(p) for p in parts],
                                                  photo.read_bytes())
                with Image.open(io.BytesIO(result)) as im:
                    im.verify()
                target = output / f'{item.id}-{index}.jpg'
                target.write_bytes(result)
                job.update(status='ok', image=target.name, bytes=len(result))
            except Exception as exc:
                job.update(status='error', error=f'{type(exc).__name__}: {exc}')
            job['seconds'] = round(time.monotonic() - start, 3)
            report['jobs'].append(job)
            report['peak_worker_rss_mib'] = round(
                resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1)
            report['passed'] = sum(j['status'] == 'ok' for j in report['jobs'])
            report['failed'] = len(report['jobs']) - report['passed']
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps(job, ensure_ascii=False), flush=True)
    (output / 'requirements.freeze.txt').write_text(subprocess.check_output(
        [sys.executable, '-m', 'pip', 'freeze'], text=True))
    if not report['failed']:
        subprocess.run([sys.executable, '-c',
            'from bot.tryon.network_guard import deny_network; deny_network(); '
            'import runpy; runpy.run_path("scripts/catalog_import/measure_curated_references.py", '
            'run_name="__main__")'], cwd=ROOT, check=True)
    print(json.dumps({k: v for k, v in report.items() if k != 'jobs'}, ensure_ascii=False))
    return bool(report['failed'])


if __name__ == '__main__':
    sys.exit(main())
