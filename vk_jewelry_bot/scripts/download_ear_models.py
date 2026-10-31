"""Explicit setup only. Verify pinned downloads before atomic publication."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.tryon.model_manifest import MODELS, valid_model


def download(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for name, (url, size, digest) in MODELS.items():
        destination = directory/name
        if valid_model(destination, size, digest):
            print(name, 'verified', flush=True)
            continue
        fd, temporary = tempfile.mkstemp(prefix=name+'.', suffix='.partial', dir=directory)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, 'wb') as output, urlopen(url, timeout=120) as response:
                total = 0
                while chunk := response.read(1024*1024):
                    total += len(chunk)
                    if total > size:
                        raise ValueError('Download exceeds expected model size')
                    output.write(chunk)
            if not valid_model(temporary, size, digest):
                raise ValueError('Checksum mismatch: '+name)
            temporary.replace(destination)
            print(name, 'downloaded and verified', flush=True)
        finally:
            temporary.unlink(missing_ok=True)
    from shutil import copyfile
    copyfile(ROOT/'docs/EAR_MODELS_NOTICE.md', directory/'NOTICE.md')
    copyfile(ROOT/'docs/APACHE-2.0.txt', directory/'LICENSE.txt')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'data/models/ear-grounded')
    download(parser.parse_args().directory)
