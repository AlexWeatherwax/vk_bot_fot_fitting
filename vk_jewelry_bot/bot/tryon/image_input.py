"""Bound image allocation before native detection; keep phone EXIF orientation."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import TryOnError


MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_SIDE = 2048


def load_photo(photo_bytes: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(photo_bytes)) as source:
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise TryOnError(
                        "Слишком большое разрешение фото. Отправьте снимок до 25 мегапикселей."
                    )
                # JPEG draft reduces the decode buffer before EXIF transposition.
                source.draft("RGB", (MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
                image = ImageOps.exif_transpose(source)
                image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS,
                                reducing_gap=3.0)
                return image.convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise TryOnError(
            "Слишком большое разрешение фото. Отправьте снимок до 25 мегапикселей."
        ) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise TryOnError("Не удалось прочитать фото. Пришлите исправное изображение JPEG или PNG.") from None
