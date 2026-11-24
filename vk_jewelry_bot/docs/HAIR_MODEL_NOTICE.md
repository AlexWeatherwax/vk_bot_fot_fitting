# Hair segmentation model

`bot/tryon/models/selfie_multiclass_256x256.tflite` is the unmodified Google
MediaPipe Multiclass Segmentation model, version `float32/1` (May 10, 2023).
Author: Adel Ahmadyan, Google. The official model card licenses the model under
the Apache License, Version 2.0; a copy is included in
`docs/licenses/Apache-2.0.txt`.

- [Official model documentation and zero-based class indices](https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter)
- [Official model card, license and limitations](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Multiclass%20Segmentation.pdf)
- [Pinned original model](https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite)
- Size: 16,371,837 bytes.
- SHA-256: `c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0`.

Setup: `python scripts/prepare_hair_model.py`. Offline verification:
`python scripts/prepare_hair_model.py --verify-only`. The setup helper is
idempotent and verifies the byte count and checksum before installing a file.
The worker verifies the installed model on lazy initialization and has no
download code or network access.

The model segments hair (class 1) and face skin (class 3); it does not classify
hairstyles. `hair_placement.py` accepts one visible rounded lateral bun with a
distinct neck and rejects uncertain or cropped silhouettes. For profile views
that FaceLandmarker rejects, an independently confident semantic face-skin
region provides a PCA frame; neck/body skin (class 2) is excluded. Long hidden
shafts are represented as inserted into the bun, with only a short projected
entry segment; that segment is occluded using the measured hair confidence.
This is a bounded 2.5D effect, not reconstruction of hidden hair or 3D pin depth.

The model card reports sensitivity to poor lighting, backlight, noise and
occlusion, and does not promise pixel-perfect masks. These limits apply to
the try-on workflow as well. The supplied synthetic reference and its mirrored
and scaled mask variants are checks of this workflow, not an evaluation across
all hairstyles, hair colors or people.
