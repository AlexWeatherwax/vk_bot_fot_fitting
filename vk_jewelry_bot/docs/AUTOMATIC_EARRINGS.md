# Automatic ear placement: Linux / Docker

Grounding DINO detects visible ears, SAM 2.1 segments them, and a calibrated
lower-mask point determines the earring attachment. No manual points or dialogue
are needed. An undetected ear is omitted, not guessed using face geometry.
If neither ear is detected, the existing handler requests another photo.
A segmentation model does not locate an actual piercing: hair, strong head tilt,
small ears and unusual poses can still cause error. This is not a guaranteed
millimetre-accurate detector.

## Install

From `vk_jewelry_bot`, configure `.env` with the existing VK settings and add:

```
EAR_PARSER_BACKEND=grounded-sam2
EAR_PARSER_MODEL=data/models/ear-grounded
```

Then run:

```sh
docker compose build
# Downloads are setup only; this container never receives VK credentials.
docker run --rm -v "$PWD/data/models:/app/data/models" --entrypoint python \
  vk-jewelry-bot:local scripts/download_ear_models.py
docker compose up -d
```

Alternatively download with `python3 scripts/download_ear_models.py` (Python
3.11+; standard library only) before starting Docker. Downloads are approximately
330 MB and require Internet access. Pinned revisions, expected sizes and SHA256
are checked; partial files are removed. Runtime never downloads missing weights.
The model directory is mounted read-only. `.env` and models are excluded from
Docker build context. Keep model notices when distributing weights.

## Runtime

Photo processing runs in a fresh Linux child process. A libseccomp filter denies
network syscalls before importing any native model library. The VK parent retains
network access and passes no VK token to the worker. Photo bytes travel through
pipes, with no temporary photo files. One job per bot process is allowed; a busy
bot asks the sender to retry. The event loop remains responsive. Timeout is 120 s.
A missing library, invalid weights or failed isolation fails closed, without an
insecure fallback. All categories use this worker, not only earrings.

Use Docker Desktop on macOS/Windows: native inference through the new bot service
requires Linux. Direct calls to `pipeline.apply_tryon` from research/editor code
are not this isolation boundary; run such scripts through `offline.py` on Linux.

Two CPU inference threads are configured. Earlier warm inference on the 12-photo
research set took a median ~8 s; each bot request also loads models, so real
latency and RAM are higher. Measure peak RAM before sizing production; GPU is not
required. No VK server deployment or load test is implied by local tests.

Without EAR_PARSER_MODEL the historical geometric backend remains available.
Setting grounded-sam2 requires the downloaded directory and never silently falls
back to geometry. The old EAR_PARSER_MODEL ONNX-file option is research-only unless
its separately supplied weights have appropriate rights.

Public portrait validation images and debug masks were deleted after the earlier
research run and are not served by the bot. This integration uses only the
repository calibration fixtures; it does not train on or retain internet photos.

## Integration validation (2026-10-31)

44 automated tests passed on Linux/Python 3.12, including the existing category
pipeline tests, socket-denial checks, timeout cleanup and model corruption checks.
Actual weights passed both repository synthetic fixtures through the same
service/worker path used by the VK handler. Both output JPEGs were inspected: two
earrings frontally, one on the visible ear in the turned-head fixture. An initial
run took 17.5 and 17.3 seconds; child peak RSS was 2,848,008 KiB (~2.72 GiB).
Plan at least 4 GiB RAM for a single worker, with additional headroom for the bot
and OS; this is a starting estimate, not a production capacity guarantee. Docker
is not installed in this verification environment, so the image build and VK
end-to-end delivery remain untested here.
