"""Ensure repository cleanup never removes an image used by the real catalog."""
from PIL import Image

from bot.jewelry.catalog import Catalog, MANIFEST_PATH
from bot.jewelry.models import Category


def test_current_catalog_has_unique_ids_and_readable_images():
    catalog = Catalog(MANIFEST_PATH)
    ids = [item.id for item in catalog.items]
    assert len(ids) == len(set(ids))
    assert {item.category for item in catalog.items} == set(Category)

    gallery = MANIFEST_PATH.parent.resolve()
    for item in catalog.items:
        path = catalog.image_path(item).resolve()
        assert path.is_relative_to(gallery), item.id
        assert path.is_file(), f"Missing image for {item.id}: {path}"
        with Image.open(path) as image:
            assert image.format == "PNG", item.id
            image.verify()
