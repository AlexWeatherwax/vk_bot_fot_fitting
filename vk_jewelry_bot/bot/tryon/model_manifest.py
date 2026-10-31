"""Pinned Apache-2.0 ONNX conversions. No automatic downloads during inference."""
import hashlib
from pathlib import Path

SAM = 'https://huggingface.co/akiyamanx/sam2.1-hiera-tiny-onnx/resolve/aa11669045f8d82c74e46f8f77c9b56792c90ebb/'
DINO = 'https://huggingface.co/onnx-community/grounding-dino-tiny-ONNX/resolve/ff690b0a8050566c290287545bd059350f3e9096/'
MODELS = {
    'encoder.onnx': (SAM+'sam2.1_hiera_tiny.encoder.onnx', 109471931, '667384d1e686de6828b841ac8a24db0fafa2b3452494225f82eeedac56141230'),
    'decoder.onnx': (SAM+'sam2.1_hiera_tiny.decoder.onnx', 16519561, 'c40f5aa7d37b681cd500481a85d44839fd81c93dce1e86271a2c866470d22105'),
    'model_quantized.onnx': (DINO+'onnx/model_quantized.onnx', 203824675, '70bf2d3310d1ae73769c96a71e00cbf2861eb33a1f4d97d84a108a7bf02c03c9'),
    'vocab.txt': (DINO+'vocab.txt', 231508, '07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'),
}


def valid_model(path, size, digest):
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == digest


def verify_models(directory):
    for name, (_, size, digest) in MODELS.items():
        if not valid_model(Path(directory)/name, size, digest):
            raise ValueError(f'Missing or corrupt model {name}; run scripts/download_ear_models.py')
