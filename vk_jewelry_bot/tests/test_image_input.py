"""User photos are bounded before allocation and oriented before detection."""
import io

from PIL import Image
import pytest

from bot.tryon.errors import TryOnError
from bot.tryon.image_input import load_photo


def encode(image, format="PNG", **kwargs):
    out = io.BytesIO()
    image.save(out, format=format, **kwargs)
    return out.getvalue()


def test_small_transparent_photo_becomes_detached_rgb():
    result = load_photo(encode(Image.new("RGBA", (123, 99), (200, 80, 40, 255))))
    assert result.mode == "RGB"
    assert result.size == (123, 99)
    assert result.getpixel((0, 0)) == (200, 80, 40)


def test_phone_exif_rotates_before_landmarks():
    exif = Image.Exif()
    exif[274] = 6
    image = Image.new("RGB", (120, 80), "red")
    image.paste("blue", (0, 0, 60, 80))
    result = load_photo(encode(image, "JPEG", exif=exif, quality=100))
    assert result.size == (80, 120)
    assert result.getpixel((40, 20))[2] > 240
    assert result.getpixel((40, 100))[0] > 240


def test_large_phone_jpeg_draft_keeps_exif_rotation_and_aspect():
    exif = Image.Exif()
    exif[274] = 6
    image = Image.new("RGB", (5000, 4500), "red")
    image.paste("blue", (0, 0, 2500, 4500))
    result = load_photo(encode(image, "JPEG", exif=exif, quality=95))
    assert result.size == (1843, 2048)
    assert result.getpixel((900, 100))[2] > 240
    assert result.getpixel((900, 1900))[0] > 240
    assert result.getexif().get(274) is None


@pytest.mark.parametrize("format", ["JPEG", "PNG"])
def test_large_accepted_photo_is_bounded_and_keeps_aspect(format):
    result = load_photo(encode(Image.new("RGB", (4000, 3000)), format))
    assert result.size == (2048, 1536)


def test_compressed_large_dimensions_rejected_before_pixel_decode(monkeypatch):
    raw = encode(Image.new("1", (6000, 5000)))

    def unexpected_decode(*args, **kwargs):
        pytest.fail("Oversized photo must be rejected before pixel decoding")

    monkeypatch.setattr(Image.Image, "load", unexpected_decode)
    with pytest.raises(TryOnError, match="25 мегапикселей"):
        load_photo(raw)


@pytest.mark.parametrize("raw", [b"", b"not-an-image", b"\x89PNG\r\n\x1a\n"])
def test_bad_upload_has_retry_message(raw):
    with pytest.raises(TryOnError, match="Пришлите исправное"):
        load_photo(raw)
