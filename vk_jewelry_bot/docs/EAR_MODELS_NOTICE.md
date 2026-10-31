# Ear placement models

The download script pins and verifies these third-party ONNX conversions:

- SAM 2.1 Hiera Tiny, Meta / Facebook Research: https://github.com/facebookresearch/sam2
  Conversion: https://huggingface.co/akiyamanx/sam2.1-hiera-tiny-onnx
- Grounding DINO Tiny, IDEA Research: https://github.com/IDEA-Research/GroundingDINO
  Conversion: https://huggingface.co/onnx-community/grounding-dino-tiny-ONNX

The original model repositories and conversion model cards declare Apache-2.0.
The license permits commercial use subject to its terms; it is not a warranty
about predictions or every upstream training image. Preserve this notice and
APACHE-2.0.txt with redistributed weights. Exact revisions and SHA256 values
are in bot/tryon/model_manifest.py. No weights are stored in this repository.
No fine-tuning was performed. The previous research face parser is not used
by the grounded-sam2 backend.
