"""
Тесты каталога и нечёткого поиска — не требуют ни VK-токена, ни mediapipe,
можно гонять локально сразу после `pip install -r requirements.txt`
(или даже только с Pillow, т.к. этот модуль их не использует).

Запуск: pytest tests/test_catalog.py
"""
from bot.jewelry.catalog import Catalog, MANIFEST_PATH
from bot.jewelry.models import Category


def test_manifest_loads():
    catalog = Catalog(MANIFEST_PATH)
    assert len(catalog.items) >= 5
    categories = {item.category for item in catalog.items}
    assert categories == set(Category)


def test_exact_match():
    catalog = Catalog(MANIFEST_PATH)
    item, suggestions = catalog.find("Серьги Ягодные")
    assert item is not None
    assert item.id == "imladris_earrings_sergi-yagodnye"
    assert suggestions == []


def test_case_insensitive_and_partial():
    catalog = Catalog(MANIFEST_PATH)
    item, _ = catalog.find("ягодные")
    assert item is not None
    assert item.id == "imladris_earrings_sergi-yagodnye"


def test_typo_tolerant_search():
    catalog = Catalog(MANIFEST_PATH)
    # "Кольцо Обенное" вместо "Кольцо Особенное" — опечатка, должна остаться в кандидатах
    item, suggestions = catalog.find("Кольцо Обенное")
    assert item is not None or any(s.id == "imladris_ring_koltso-osobennoe" for s in suggestions)


def test_unknown_item_returns_no_match():
    catalog = Catalog(MANIFEST_PATH)
    item, suggestions = catalog.find("зжшдлфыва")
    assert item is None
