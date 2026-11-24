#!/usr/bin/env bash
# Local Linux verification on macOS using the existing Podman machine.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
mkdir -p data/audit
started=0
finish() {
  if [ "$started" = 1 ]; then
    podman machine stop podman-machine-default
  fi
}
trap finish EXIT
if ! podman info >/dev/null 2>&1; then
  podman machine start podman-machine-default
  started=1
fi
if [ "${1:-}" = "--skip-build" ]; then
  shift
else
  podman build -t localhost/vk-jewelry-bot:validation .
fi
entry=scripts/server_smoke.py
if [ "${1:-}" = "--hair-probe" ]; then
  entry=scripts/probe_hairpin_runtime.py
  shift
fi
podman run --rm --pull=never --network=none \
  -v './bot:/app/bot:ro' \
  -v './scripts:/app/scripts:ro' \
  -v './jewelry_editor:/app/jewelry_editor:ro' \
  -v './фото для калибровки:/app/фото для калибровки:ro' \
  -v './data/audit:/app/data/audit:rw' \
  localhost/vk-jewelry-bot:validation python "$entry" "$@"
