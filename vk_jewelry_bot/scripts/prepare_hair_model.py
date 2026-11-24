"""Setup-only download of one pinned Apache-2.0 MediaPipe model.

The inference worker never imports this module or downloads model weights.
"""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = PROJECT/"bot/tryon/models/selfie_multiclass_256x256.tflite"
URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/"
       "selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite")
SHA256 = "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0"
SIZE = 16371837


def verified(path):
    return (path.is_file() and path.stat().st_size == SIZE
            and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256)


def prepare(path=DEFAULT_PATH, *, verify_only=False):
    path = Path(path)
    if verified(path):
        return path
    if verify_only:
        raise ValueError(f"Missing or invalid pinned hair model: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".download", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(URL, timeout=30) as response:
                total = 0
                while chunk := response.read(1024*1024):
                    total += len(chunk)
                    if total > SIZE:
                        raise ValueError("Hair model exceeds pinned byte length")
                    output.write(chunk)
        if not verified(temporary):
            raise ValueError("Downloaded hair model failed pinned size/SHA-256 verification")
        os.replace(temporary, path)
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    options = parser.parse_args()
    print(prepare(options.path, verify_only=options.verify_only))
