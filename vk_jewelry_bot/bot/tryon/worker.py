"""One request per process; no networking, credentials or temporary photo files."""
import base64
import json
from pathlib import Path
import sys
from .network_guard import deny_network


def main():
    deny_network()  # Must precede imports of MediaPipe, OpenCV and ONNX Runtime.
    from .pipeline import apply_tryon
    from .errors import TryOnError
    from ..jewelry.models import JewelryItem, Category
    raw = sys.stdin.buffer.read(29 * 1024 * 1024 + 1)
    if len(raw) > 29 * 1024 * 1024:
        raise ValueError("Worker request too large")
    request = json.loads(raw)
    request["item"]["category"] = Category(request["item"]["category"])
    item = JewelryItem(**request["item"])
    photo = base64.b64decode(request["photo"], validate=True)
    if len(photo) > 20 * 1024 * 1024:
        raise ValueError("Photo too large")
    try:
        output = apply_tryon(item, Path(request["overlay"]), photo)
        response = {"photo": base64.b64encode(output).decode("ascii")}
    except TryOnError as exc:
        response = {"error": str(exc)}
    sys.stdout.write(json.dumps(response))


if __name__ == "__main__":
    main()
