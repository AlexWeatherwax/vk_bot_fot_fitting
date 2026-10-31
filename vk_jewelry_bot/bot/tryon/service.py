"""VK-facing entry point. No native model imports or photo files in this process."""
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from .errors import TryOnError

_SLOT = threading.BoundedSemaphore(1)
_PROJECT = Path(__file__).resolve().parents[2]


def apply_tryon(item, overlay_path, photo_bytes):
    if len(photo_bytes) > 20 * 1024 * 1024:
        raise TryOnError("Фото слишком большое: отправьте файл меньше 20 МБ.")
    if not _SLOT.acquire(blocking=False):
        raise TryOnError("Сейчас обрабатывается другая примерка. Повторите через несколько секунд.")
    try:
        # Never pass VK credentials to native inference libraries.
        allowed = {"PATH", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "LANG", "SYSTEMROOT"}
        env = {k: v for k, v in os.environ.items() if k in allowed or k.startswith("EAR_PARSER_")}
        env["ORT_DISABLE_TELEMETRY"] = "1"
        request = {"item": asdict(item), "overlay": str(Path(overlay_path).resolve()),
                   "photo": base64.b64encode(photo_bytes).decode("ascii")}
        result = subprocess.run([sys.executable, "-m", "bot.tryon.worker"],
                                cwd=_PROJECT, env=env, input=json.dumps(request),
                                text=True, capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError("Offline inference worker failed: " + result.stderr[-2000:])
        response = json.loads(result.stdout)
        if "error" in response:
            raise TryOnError(response["error"])
        return base64.b64decode(response["photo"], validate=True)
    except subprocess.TimeoutExpired:
        raise TryOnError("Обработка заняла слишком много времени. Попробуйте другое фото.") from None
    finally:
        _SLOT.release()
